# eval/run_eval.py
"""
Eval harness — đo CHẤT LƯỢNG pipeline phân tích CV vs JD bằng Gemini THẬT.

Khác pytest (48 test, fake hết, miễn phí): script này tiêu tiền CÓ CHỦ ĐÍCH
để trả lời "hệ chấm có đúng không" trên dataset đa dạng, và lưu báo cáo để
so sánh giữa các version prompt.

Chạy:
    python eval/run_eval.py                 # full: 20 case x 2 lần chạy
    python eval/run_eval.py --limit 1       # smoke: 1 case (kiểm tra script)
    python eval/run_eval.py --runs 1        # bỏ đo variance cho rẻ
    python eval/run_eval.py --only a,b,c    # chỉ chạy các case id này (chạy nốt phần lỗi)

Chống 429 (bài học từ lần chạy baseline đầu — cạn quota ngày của Gemini):
- Mỗi call API retry tối đa 3 lần với backoff (cứu được rate-limit theo phút).
- 2 case LIÊN TIẾP chết vì 429 -> quota kiểu theo NGÀY, retry vô ích -> ngắt
  sớm cả lượt (circuit breaker) + in sẵn lệnh --only để chạy nốt sau.
- Raw JSON response từng case được lưu cạnh báo cáo -> soi evidence/phân tích
  hậu kỳ KHÔNG tốn thêm call API nào.

Kiến trúc (các quyết định đã chốt ở bước thiết kế):
- Gọi qua TestClient -> đi đúng đường HTTP thật, không cần bật uvicorn.
- Mỗi CV chỉ upload (embed) MỘT lần, tái dùng cv_id cho mọi case + mọi run.
- Cô lập dữ liệu như tests/conftest.py: env trỏ Chroma/uploads sang thư mục
  tạm TRƯỚC khi import app -> không bao giờ đụng data/ thật.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# --- Cô lập môi trường: PHẢI đứng trước mọi import app.* (xem conftest.py) ---
_TMP = tempfile.mkdtemp(prefix="job_assistant_eval_")
os.environ["CHROMA_PERSIST_DIR"] = os.path.join(_TMP, "chroma")
os.environ["UPLOAD_DIR"] = os.path.join(_TMP, "uploads")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services.document_service import clean_text  # noqa: E402

DATASET = ROOT / "eval" / "dataset"
REPORTS = ROOT / "eval" / "reports"

VARIANCE_NGUONG = 5  # |Δoverall| giữa các lần chạy vượt mức này = đáng lo


# ==========================================================================
# Chuẩn hóa & so khớp
# ==========================================================================

def normalize(text: str) -> str:
    """NFKC + lowercase + gộp khoảng trắng — mọi phép so sánh đều qua đây
    để không fail oan vì hoa/thường hay xuống dòng."""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def _manh_grounded(manh: str, cv_norm: str) -> bool:
    """Một mảnh trích dẫn có nằm trong CV không: chứa-chuỗi tuyệt đối, hoặc
    >=80% ký tự khớp thành đoạn LIÊN TỤC (LLM hay cắt đầu/đuôi câu)."""
    if manh in cv_norm:
        return True
    m = SequenceMatcher(None, manh, cv_norm, autojunk=False).find_longest_match(
        0, len(manh), 0, len(cv_norm)
    )
    return m.size / len(manh) >= 0.8


def is_grounded(evidence: str, cv_norm: str) -> bool:
    """Evidence có THẬT trong CV không (bắt bịa/lai chữ JD).

    Bài học từ baseline đầu: LLM hay GHÉP nhiều trích dẫn thật bằng '; ' hoặc
    '. ' — chuỗi ghép không liền mạch trong CV nên check "một trích liên tục"
    đánh trượt OAN (5/5 ca soi tay từ raw đều là ghép-thật, không phải bịa).
    → Tách evidence thành từng mảnh (theo ';' và '.' — trừ dấu chấm giữa 2
    chữ số như "3.12"), MỌI mảnh đáng kể (>=10 ký tự) phải tự chứng minh.
    """
    ev = normalize(evidence)
    if not ev:
        return False
    cac_manh = [
        m.strip() for m in re.split(r";|(?<!\d)\.(?!\d)", ev) if len(m.strip()) >= 10
    ]
    if not cac_manh:          # evidence quá ngắn sau khi tách -> chấm cả chuỗi
        cac_manh = [ev]
    return all(_manh_grounded(m, cv_norm) for m in cac_manh)


def keyword_hit(keyword: str, candidates: list[str]) -> bool:
    """Nhãn ghi keyword ngắn ('Python'); tên skill LLM viết dài ngắn tùy hứng
    ('Python (3.12)', 'PostgreSQL hoặc MySQL') -> so bằng chứa-chuỗi normalize."""
    kw = normalize(keyword)
    return any(kw in normalize(c) for c in candidates)


# ==========================================================================
# Chạy pipeline qua TestClient
# ==========================================================================

def goi_co_retry(fn, *args, mo_ta: str = "", so_lan: int = 3):
    """
    Gọi API có retry khi 429.

    429 có 2 họ: rate-limit theo PHÚT (nghỉ một lúc là hồi — retry cứu được)
    và quota theo NGÀY (retry vô ích). Nên chỉ thử lại {so_lan} lần với
    backoff 15s/30s rồi bỏ cuộc — quota ngày để circuit breaker ở main lo.
    """
    for lan in range(so_lan):
        try:
            return fn(*args)
        # Bắt Exception CHUNG rồi phân loại theo MESSAGE, không theo type:
        # lỗi 429/503 của Gemini xuyên qua TestClient dưới dạng ClientError
        # của SDK google-genai (TestClient re-raise exception gốc chứ không
        # trả HTTP response) — bắt RuntimeError như bản đầu là trượt hết,
        # retry chưa bao giờ chạy mà không ai biết (bug lộ ra ở vòng #3).
        except Exception as exc:
            # 503 UNAVAILABLE ("high demand") cũng là lỗi TẠM THỜI đáng retry.
            tam_thoi = any(ma in str(exc) for ma in ("429", "503"))
            if not tam_thoi or lan == so_lan - 1:
                raise
            cho = 15 * (2 ** lan)  # 15s rồi 30s
            print(f"    ... loi tam thoi ({mo_ta}) — thử lại sau {cho}s [{lan + 1}/{so_lan - 1}]")
            time.sleep(cho)


def upload_cv(client: TestClient, cv_path: Path) -> dict:
    resp = client.post(
        "/cv/upload",
        files={"file": (cv_path.name, cv_path.read_bytes(), "text/plain")},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Upload {cv_path.name} loi {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    # cv_norm: chuẩn hóa cùng đường với pipeline (clean_text) để so evidence công bằng.
    raw = cv_path.read_text(encoding="utf-8")
    return {
        "cv_id": data["cvId"],
        "sections": data["sectionsDetected"],
        "total_chunks": data["totalChunks"],
        "cv_norm": normalize(clean_text(raw)),
    }


def read_jd(jd_path: Path) -> tuple[str | None, str]:
    """JD file dòng đầu dạng 'Vị trí: X' -> tách làm title; content = toàn văn."""
    content = jd_path.read_text(encoding="utf-8")
    first = content.split("\n", 1)[0].strip()
    title = first.removeprefix("Vị trí:").strip() if first.startswith("Vị trí:") else None
    return title, content


def analyze(client: TestClient, cv_id: str, title: str | None, content: str) -> dict:
    resp = client.post(
        "/analysis", json={"cvId": cv_id, "jd": {"title": title, "content": content}}
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Analysis loi {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ==========================================================================
# Chấm một case
# ==========================================================================

def eval_case(case: dict, runs_data: list[dict], cv_norm: str) -> dict:
    expect = case["expect"]
    d = runs_data[0]  # các check nội dung chấm trên lần chạy đầu

    matched_names = [s["skill"] for s in d["matchedSkills"] if s["presentInCv"]]
    missing_names = d["missingSkills"]
    evidences = [
        s["evidence"] for s in d["matchedSkills"] if s["presentInCv"] and s["evidence"]
    ]

    grounded = sum(1 for ev in evidences if is_grounded(ev, cv_norm))
    overalls = [r["score"]["overall"] for r in runs_data]

    verdict_ok = d["verdict"] in expect["verdict_in"]
    matched_miss = [k for k in expect["must_matched"] if not keyword_hit(k, matched_names)]
    missing_miss = [k for k in expect["must_missing"] if not keyword_hit(k, missing_names)]

    return {
        "id": case["id"],
        "note": case.get("note", ""),
        "verdict": d["verdict"],
        "verdict_expect": expect["verdict_in"],
        "verdict_ok": verdict_ok,
        "overalls": overalls,
        "variance": max(overalls) - min(overalls),
        "matched_miss": matched_miss,   # nhãn must_matched bị SÓT
        "missing_miss": missing_miss,   # nhãn must_missing bị SÓT
        "n_evidence": len(evidences),
        "n_grounded": grounded,
        "suggestions": d["suggestions"],
        "passed": verdict_ok and not matched_miss and not missing_miss,
        "error": None,
    }


# ==========================================================================
# Báo cáo
# ==========================================================================

def render_report(results: list[dict], cv_reports: dict, runs: int, elapsed: float) -> str:
    ok = [r for r in results if r["error"] is None]
    passed = sum(1 for r in ok if r["passed"])
    verdict_ok = sum(1 for r in ok if r["verdict_ok"])
    tong_ev = sum(r["n_evidence"] for r in ok)
    tong_gr = sum(r["n_grounded"] for r in ok)
    max_var = max((r["variance"] for r in ok), default=0)
    sec_ok = sum(1 for c in cv_reports.values() if c["section_ok"])

    lines = [
        f"# Eval report — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Model: `{settings.gemini_model}` | temperature 0.0 | TOP_K 10 | "
        f"runs/case: {runs} | thời gian: {elapsed:.0f}s | case lỗi: {len(results) - len(ok)}",
        "",
        "## Tổng hợp (dòng này là 'điểm số' của version prompt hiện tại)",
        "",
        f"- **Case pass** (verdict + must_matched + must_missing): **{passed}/{len(ok)}**",
        f"- Verdict đúng cửa sổ kỳ vọng: {verdict_ok}/{len(ok)}",
        f"- **Grounding**: {tong_gr}/{tong_ev} evidence có thật trong CV = "
        f"**{(100 * tong_gr / tong_ev if tong_ev else 0):.0f}%**",
        f"- Section detection đúng kỳ vọng: {sec_ok}/{len(cv_reports)} CV",
        f"- Variance |Δoverall| lớn nhất: {max_var} (ngưỡng {VARIANCE_NGUONG})",
        "",
        "## Chi tiết từng case",
        "",
        "| case | verdict (kỳ vọng) | overall | Δ | sót matched | sót missing | grounding | KQ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["error"]:
            lines.append(f"| {r['id']} | LỖI: {r['error']} | | | | | | ❌ |")
            continue
        lines.append(
            f"| {r['id']} | {r['verdict']} ({'/'.join(r['verdict_expect'])}) "
            f"| {r['overalls']} | {r['variance']} "
            f"| {', '.join(r['matched_miss']) or '—'} "
            f"| {', '.join(r['missing_miss']) or '—'} "
            f"| {r['n_grounded']}/{r['n_evidence']} "
            f"| {'✅' if r['passed'] else '❌'} |"
        )

    lines += ["", "## Section detection theo CV", "",
              "| cv | sections phát hiện | kỳ vọng có section? | KQ |", "|---|---|---|---|"]
    for cv, c in cv_reports.items():
        lines.append(
            f"| {cv} | {', '.join(c['sections'])} | {'có' if c['expect'] else 'fallback'} "
            f"| {'✅' if c['section_ok'] else '❌'} |"
        )

    # 3 case tệ nhất (overall thấp nhất trong nhóm fail, rồi tới nhóm pass) để
    # người đọc soi suggestions bằng mắt — thứ máy không chấm được.
    xau_nhat = sorted(ok, key=lambda r: (r["passed"], min(r["overalls"])))[:3]
    lines += ["", "## Suggestions của 3 case đáng soi nhất (chấm tay: có hành động cụ thể? có gắn với CV thật?)"]
    for r in xau_nhat:
        lines.append(f"\n### {r['id']} — {r['note']}")
        for s in r["suggestions"]:
            lines.append(f"- [{s['priority']}] **{s['title']}**: {s['detail']}")

    return "\n".join(lines) + "\n"


# ==========================================================================
# Main
# ==========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Eval harness Job Assistant AI")
    parser.add_argument("--runs", type=int, default=2, help="số lần chạy mỗi case (đo variance)")
    parser.add_argument("--limit", type=int, default=None, help="chỉ chạy N case đầu (smoke test)")
    parser.add_argument("--only", type=str, default=None,
                        help="chỉ chạy các case id này, phân cách bằng dấu phẩy")
    args = parser.parse_args()

    data = json.loads((DATASET / "cases.json").read_text(encoding="utf-8"))
    if args.only:
        muon = [x.strip() for x in args.only.split(",") if x.strip()]
        id_hop_le = {c["id"] for c in data["cases"]}
        id_la = [m for m in muon if m not in id_hop_le]
        if id_la:
            sys.exit(f"Case id không tồn tại: {id_la}\nHợp lệ: {sorted(id_hop_le)}")
        cases = [c for c in data["cases"] if c["id"] in muon]
    elif args.limit:
        cases = data["cases"][: args.limit]
    else:
        cases = data["cases"]
    cv_meta = data["cv_meta"]

    client = TestClient(app)
    uploaded: dict[str, dict] = {}   # cv path -> thông tin upload (embed 1 lần duy nhất)
    cv_reports: dict[str, dict] = {}
    results: list[dict] = []
    raw_dump: dict[str, dict] = {}   # case id -> response thô (phân tích hậu kỳ miễn phí)
    lien_tiep_429 = 0                # đếm case chết vì 429 liên tục (circuit breaker)
    t0 = time.time()

    for i, case in enumerate(cases, 1):
        try:
            # 1. Upload CV nếu chưa (cache theo path — tiết kiệm embed)
            if case["cv"] not in uploaded:
                info = goi_co_retry(upload_cv, client, DATASET / case["cv"], mo_ta="upload")
                uploaded[case["cv"]] = info
                expect_sec = cv_meta.get(case["cv"], {}).get("expect_sections", True)
                co_section = info["sections"] != ["other"]
                cv_reports[case["cv"]] = {
                    "sections": info["sections"],
                    "expect": expect_sec,
                    "section_ok": co_section == expect_sec,
                }
            info = uploaded[case["cv"]]

            # 2. Chạy analysis N lần
            title, content = read_jd(DATASET / case["jd"])
            runs_data = [
                goi_co_retry(analyze, client, info["cv_id"], title, content, mo_ta="analysis")
                for _ in range(args.runs)
            ]
            raw_dump[case["id"]] = {"cv": case["cv"], "jd": case["jd"], "runs": runs_data}

            # 3. Chấm
            r = eval_case(case, runs_data, info["cv_norm"])
            lien_tiep_429 = 0
        except Exception as exc:  # 1 case hỏng không được giết cả lượt eval
            r = {"id": case["id"], "error": str(exc)[:150], "passed": False}
            r.setdefault("note", case.get("note", ""))
            lien_tiep_429 = lien_tiep_429 + 1 if "429" in str(exc) else 0
        results.append(r)

        trang_thai = "LỖI" if r.get("error") else ("PASS" if r["passed"] else "FAIL")
        overalls = r.get("overalls", "-")
        print(f"[{i}/{len(cases)}] {case['id']:<24} overall={overalls} -> {trang_thai}")

        # Circuit breaker: 2 case liên tiếp 429 = quota NGÀY đã cạn, chạy tiếp
        # chỉ đốt thời gian retry vô ích -> ngắt sớm, in sẵn lệnh chạy nốt.
        if lien_tiep_429 >= 2:
            chua_xong = [c["id"] for c in cases[i:]] + [
                r2["id"] for r2 in results if r2.get("error") and "429" in r2["error"]
            ]
            print("\n!! 2 case liên tiếp lỗi 429 — quota ngày có vẻ đã cạn. NGẮT SỚM.")
            print("   Chạy nốt sau khi quota reset (≈14:00 giờ VN):")
            print(f"   python eval/run_eval.py --only {','.join(chua_xong)}")
            break

    elapsed = time.time() - t0
    report = render_report(results, cv_reports, args.runs, elapsed)

    REPORTS.mkdir(parents=True, exist_ok=True)
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    out = REPORTS / f"eval_{ts}.md"
    out.write_text(report, encoding="utf-8")
    # Raw response để soi evidence/phân tích lại mà không tốn call API nào.
    raw_out = REPORTS / f"eval_{ts}_raw.json"
    raw_out.write_text(json.dumps(raw_dump, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    # In lại phần tổng hợp ra console cho tiện
    print("\n".join(report.split("\n## Chi tiết")[0].split("\n")[2:]))
    print(f"Báo cáo đầy đủ: {out}")
    print(f"Raw response:   {raw_out}")


if __name__ == "__main__":
    main()
