# PROGRESS — Job Assistant AI (checkpoint)

> File recap để mở phiên làm việc mới là nắm được ngay tiến độ. Chi tiết kiến trúc,
> quyết định thiết kế, bẫy đã gặp: xem `README.md` (nguồn sự thật). Kế hoạch test đã
> chốt: xem `CLAUDE.md`. Cập nhật file này + README mục 10 sau mỗi bước lớn.
>
> Checkpoint này lập sau khi: hoàn thành `POST /analysis` (RAG end-to-end pass) và
> rà soát lại TOÀN BỘ repo trên đĩa (phát hiện 3 điểm lệch — xem mục ⚠️).

---

## Bức tranh tổng

**Backend RAG đã hoàn chỉnh và test tay pass hết.** Luồng đầy đủ đang chạy:
upload CV → parse/chunk hybrid → embed (Gemini) → index (ChromaDB, cô lập theo cv_id)
→ dán JD → retrieve top-k → prompt grounding + rubric → Gemini structured output
→ điểm số + bằng chứng + gợi ý cải thiện.

**Backend + pytest (52 test) + eval 3 vòng cải thiện (20/20) ĐÃ XONG.** Việc lớn còn lại: **frontend ReactJS**.

---

## ✅ Đã xong (kiểm chứng trực tiếp trên đĩa + test)

| # | Hạng mục | Ghi chú |
|---|---|---|
| 1 | Môi trường | venv Python 3.12, google-genai 2.8.0, chromadb 0.5.23, pypdf, posthog<6 ghim |
| 2 | `app/config.py` | Đủ biến: gemini_*, chroma_persist_dir, **chroma_collection_name**, **chunk_size/chunk_overlap**, upload_dir, **cors_origins** |
| 3 | `app/main.py` | Lifespan + CORS + global exception handler (AppException → ErrorResponse) + router `cv`, `analysis` |
| 4 | `embedding_service.py` | embed_text/embed_batch, phân biệt RETRIEVAL_QUERY vs RETRIEVAL_DOCUMENT (type hint đã sửa `list[str]`) |
| 5 | `llm_service.py` | generate / generate_json / **generate_structured(response_schema)** — constrained decoding, fallback validate, LLMResponseError |
| 6 | `vector_service.py` | Kiến trúc B3: 1 collection chung, filter cv_id, id `{cv_id}::{chunk_id}`, delete_cv theo metadata. Test cô lập pass |
| 7 | `document_service.py` | extract PDF/TXT → clean_text → chunk hybrid (section-based ≥2 heading → sub-chunk overlap → fallback fixed). Test kỹ |
| 8 | `schemas.py` | 3 tầng (internal dataclass / API camelCase / LLM snake_case), enum MatchVerdict + Priority, `LLMAnalysis.to_response()` |
| 9 | `core/exceptions.py` | AppException + DocumentProcessingError 422 + CVNotFoundError 404 + LLMResponseError 502 |
| 10 | `routes/cv.py` — POST /cv/upload | Validate đuôi/5MB/rỗng → uuid → lưu file → chunk → index. Test 3 case pass |
| 11 | `routes/analysis.py` — POST /analysis | RAG 4 bước, TOP_K=10, MAX_QUERY_CHARS=8000, SYSTEM_INSTRUCTION (grounding + rubric + verdict↔score), route `def` sync. **Test end-to-end với Gemini thật pass**: evidence trích nguyên văn, missing_skills đúng, 404 khi cv_id sai |
| 12 | Tài liệu | README cập nhật đến hiện trạng (mục 3, 4.8, 4.9, 6, 7, 10, 11); `.env.example` đã gỡ API key thật |
| 13 | `routes/health.py` — GET /health + /health/ready | Liveness + readiness (heartbeat + mở collection + count() chạm đĩa; Chroma hỏng → 503). Đã đăng ký router trong main.py. Test 5 case pass |
| 14 | Hạ tầng pytest | `pytest.ini` (testpaths=tests — chặn gom 3 file test tạm ở root gọi API thật; `-m "not live"`), `requirements-dev.txt` (pytest 9.1.1 + pytest-cov 7.1.0 + httpx), `tests/fakes.py` (bag-of-words md5, 3072 chiều, đã kiểm chứng tất định + similarity đúng chiều), `tests/conftest.py` (env cô lập TRƯỚC import, 2 lưới autouse chặn Gemini thật, unique_collection, TestClient). Sửa lề: requirements.txt pypdf2→pypdf |
| 15 | **pytest — ma trận 6 file HOÀN TẤT** | **32 test xanh ~3s, coverage 91%** (`pytest --cov=app`). document (8) / vector (5) / llm_service (5) / schemas (7) / route_cv (4) / route_analysis (3). Chỗ trắng cố ý: thân hàm gọi Gemini thật (fake trong test), đường đọc PDF, route health (test tay), generate/generate_json (chưa route nào dùng). Chi tiết: README mục 9 |
| 16 | Dọn dẹp root | Đã xóa 3 file test tạm (test_document_service / test_gemini / test_vector) sau khi được duyệt; suite vẫn 32/32 xanh |
| 17 | Chống LLM-as-judge variance (A+B) | Đo TRƯỚC (temp 0.2): overall 90/75/85 (±15, verdict nhảy band). Fix: temperature 0.0 + verdict backend suy từ overall_score (`MatchVerdict.from_score`, 10 test biên). Đo SAU: **79/81/81 (±1, 2/3 lần giống hệt)** → ĐẠT, không cần self-consistency. Suite 42 test xanh |
| 18 | Giảm điểm trừ khi test — phần 1 | Refactor `ingest_cv` (validate→lưu→chunk→index, blocking bọc threadpool; 42 test cũ xanh nguyên) + `POST /analysis/direct` multipart (file + jdTitle + jdContent): upload + phân tích 1 request, JD form field khỏi escape `\n`. Phần 2: `GET /cv` (danh sách từ Chroma + filename tra uploads/) + `DELETE /cv/{cv_id}` 204 (xóa index + file; 404 nếu không có; vector_service thêm list_cvs/has_cv). **Gói HOÀN TẤT — suite 48 test xanh** |
| 19 | Eval harness — bước 1a: dataset | `eval/dataset/`: 12 CV (4 trục đa dạng: cấu trúc heading chuẩn EN/VN / văn xuôi không heading / heading phi chuẩn / text kiểu PDF xấu / song ngữ; 6 ngành; intern→senior) + 6 JD + `cases.json` 20 cặp có chủ đích với nhãn verdict_in / must_matched / must_missing. Đã validate JSON + file tồn tại. Bước 1b: `eval/run_eval.py` — TestClient, embed mỗi CV 1 lần, 5 metric tự động (grounding fuzzy 0.8 / section detection / must_matched-missing / verdict window / variance), báo cáo markdown vào `eval/reports/`, cờ `--limit`/`--runs`. Smoke test 1 case PASS trong 33s; grounding 5/6 (83%) — đã đánh hơi thấy vết evidence lai JD. Bước 1c: baseline chạy 10/20 case thì CẠN QUOTA NGÀY gemini-2.5-flash (429; embedding không sao). Kết quả 10 case: 8 pass; section detection 12/12; variance ≤5; **grounding sụp 51%** — nghi evidence bị DỊCH sang tiếng Việt với CV tiếng Anh (2/14, 2/8 ở CV EN vs 5/6 ở CV VN); model quá gắt với ứng viên non tay cùng ngành (bj_vs_senior + intern_vs_junior ra not_a_match thay vì weak). Đã gia cố run_eval: retry 429 backoff + circuit breaker ngắt sớm + `--only` + lưu raw JSON. Đợt 2 (10 case còn lại): **10/10 PASS, variance ≤1**; 3 case bẫy chunking (vanxuoi 82 / headingla 76 / pdfxau 78) chứng minh fallback KHÔNG hại điểm. Soi raw JSON → giả thuyết "dịch evidence" BỊ BÁC: 5 evidence trượt đều là TRÍCH THẬT GHÉP NHIỀU MẢNH bằng ';'/'.' — lỗi thước đo, không phải model. Đã sửa `is_grounded` thành tách-mảnh (mỗi mảnh ≥10 ký tự tự chứng minh, bảo vệ dấu chấm giữa chữ số) → chấm lại hậu kỳ đợt 2: **48/48 = 100%**. **Baseline đủ 20: 18 pass / 2 fail đều do model quá gắt với ứng viên cùng ngành non tay (bj_vs_senior 22/17, intern_vs_junior 22 → not_a_match thay vì weak). Việc kế (chờ duyệt): sửa rubric calibration + chạy lại full 20 (--runs 1 cho vừa quota ngày) so trước/sau** |
| 20 | Vòng cải thiện prompt #1 (đang đo dở) | ĐÃ SỬA PROMPT (được duyệt): luật CALIBRATION (cùng ngành non tay → 30-49; dưới 30 chỉ cho trái ngành) + evidence nguyên ngữ gốc, cấm câu chữ JD. Lượt đo "sau" chạy 1/20 case thì cạn quota (đợt 2 cùng ngày đã ăn trần ~20 call flash/ngày của key) — **circuit breaker ngắt sau 36s** (so 519s hồi chưa có) + in sẵn lệnh `--only` 19 case còn lại. Case đo được: bj_vs_junior 82 PASS (baseline 81 — prompt mới không phá case tốt); 1/7 evidence trượt là "trích dẫn bị nén nhẹ" (sàn nhiễu metric, không phải bịa). Lượt đo "sau" đủ 20 case (02/10): **17/20 pass** (so baseline 18/20) — intern_vs_junior ĐƯỢC CHỮA (22→37 weak ✓ đúng mục tiêu calibration); bj_vs_senior VẪN LÌ (17 — luật floor thua công thức trọng số khi điểm trục quá thấp); da_vs_data TỤT BIÊN (32→24, analyst→DE lẽ ra hưởng floor cùng-ngành); qa_vs_backend fail mới vì model NÂNG "SQL cơ bản" thành thỏa "PostgreSQL: thiết kế schema, tối ưu" (skill inflation). Grounding 89% — soi raw: 10/10 ca trượt đều là "nén danh sách" vô hại → grounding thực ~100%, 85-90% là sàn nhiễu metric. Section 12/12, điểm 16 case còn lại lệch ≤3 so baseline (prompt mới không phá diện rộng). Vòng #2 ĐÃ LÀM theo phương án KIẾN TRÚC (được duyệt): `LLMAnalysis` thêm `same_field: bool` (dữ kiện rời rạc, chỉ xét lĩnh vực); `to_response` áp floor tất định `same_field and overall < 30 → FLOOR_CUNG_NGANH=32` TRƯỚC khi suy verdict; prompt bỏ luật calibration cũ (vô dụng), thêm mô tả same_field + luật chống skill-inflation (mức "cơ bản" không thỏa "thành thạo"). 4 test biên floor mới — suite 52 xanh. ĐO VÒNG #2 (05/10): **verdict đúng 19/20 — tốt nhất từ đầu; floor backend hoạt động HOÀN HẢO** (bj_vs_senior 17→32 weak ✓, da_vs_data 24→32 ✓, intern_vs_senior 13→32 ✓, không floor nhầm case trái ngành nào — kt/mk_vs_khác-ngành vẫn 0). Nhưng case pass 14/20 vì 2 nguyên nhân gốc mới: (1) **luật chống inflation QUÁ TAY** — "có kỹ năng nhưng dưới mức yêu cầu" bị phủ nhận thành "không có" (intern "Python cơ bản" → false; tệ nhất: senior 8 năm PostgreSQL bị false vì CV không ghi nguyên văn "thiết kế schema") → 5 case fail nhãn must_matched; (2) **model KHÔNG BIẾT ngày hiện tại** — CV ghi "09/2024 - nay" nên không tính được số năm, kt_vs_ketoan experienceMatch sụp còn 20 (overall 86→62). Grounding 78% lại là nhiễu metric (ghép trích thật bằng dấu phẩy). ĐO VÒNG #3 (08/10, luật 3-trạng-thái + tiêm ngày hiện tại): **19/19 case chạy được đều PASS, verdict 19/19** — cả 5 nhãn hồi sinh đúng kỳ vọng (intern 31 / da 32 / qa 36 / bs_vs_junior 75), **kt_vs_ketoan 62→97** (tiêm ngày chữa dứt điểm — model biết "09/2024-nay" = 2 năm), grounding 90%, section 12/12. Case bj_vs_senior chết vì 503 UNAVAILABLE (transient) → chạy bù thì cạn quota ngày. Tiện thể LỘ BUG THẬT: `goi_co_retry` bắt `RuntimeError` nhưng lỗi Gemini xuyên TestClient là `ClientError` của SDK → retry CHƯA BAO GIỜ chạy — đã sửa thành bắt Exception chung + phân loại theo message (429/503). CHẠY BÙ (09/10): bj_vs_senior **32 weak PASS, grounding 2/2 → VÒNG #3 CHỐT 20/20, verdict 20/20 — VÒNG LẶP EVAL KHÉP LẠI**. Tổng kết 4 lượt đo (18→17→14/19→20) đã viết vào README mục 9; CLAUDE.md cập nhật trạng thái. Dừng tinh chỉnh prompt tại đây (tránh overfit 20 case) |

---

## ⚠️ Các điểm lệch tài liệu vs thực tế — TẤT CẢ ĐÃ XỬ LÝ ✅

~~1. `health.py` mới xong một nửa~~ → **ĐÃ XỬ LÝ XONG**: viết readiness thật (heartbeat +
   mở collection + count()), đăng ký router vào main.py, test 5 case pass.

~~2. CLAUDE.md ghi pytest.ini / requirements-dev.txt / tests/fakes.py "đã có sẵn" nhưng chưa tồn tại~~
   → **ĐÃ XỬ LÝ XONG**: tạo đủ 3 file theo đúng spec trong CLAUDE.md, kèm conftest.py.

~~3. 3 file test tạm còn ở root~~ → **ĐÃ XỬ LÝ XONG**: được duyệt và đã xóa
   (`test_document_service.py`, `test_gemini.py`, `test_vector.py`); suite vẫn 32/32 xanh.

---

> 🗄️ **Git**: repo đã init (09/10/2026) và push lên `github.com/VuTuanMinh22bi13317/job-assistant-ai`
> (private). Identity commit set CỤC BỘ cho repo: `Tuan Minh <hkpotatoman@gmail.com>` (đừng
> commit bằng config global của máy; nếu sau này chuyển repo public, cân nhắc đổi sang địa chỉ
> noreply của GitHub để khỏi lộ email). `.env` + `data/` + `venv/` đã gitignore,
> API key đã rà không lọt. Từ giờ: commit sau mỗi cột mốc lớn.

> 📚 **Kho bài học**: toàn bộ phần "🎓 Giải thích để học" của 4 giai đoạn đã được đúc vào
> README **mục 5.7-5.10** (testing hệ LLM / LLM-as-judge & variance / eval harness / vận hành
> API) và **mục 12** (30 câu hỏi phỏng vấn, câu có ★ = có số liệu thật từ project để kể).

| 21 | Resources cho suggestions (bước 0 frontend) | `ResourceLink` schema + `resource_service.py`: catalog ~30 skill biên soạn tay (docs/roadmap/course, ưu tiên tiếng Việt) + fallback search-link TỰ RÁP — **LLM không bao giờ sinh URL** (chống bịa link). Match chứa-chuỗi + lọc key chuỗi-con. Enrich tất định trong `_run_analysis`. Suite 58 test xanh. Hợp đồng API chốt xong TRƯỚC khi viết types.ts frontend |

## ⏳ Chưa làm (theo thứ tự ưu tiên)

1. **Frontend ReactJS — ĐANG LÀM, xong bước 1/5**:
   - [x] Bước 1: scaffold Vite + React 19 + TS 6 + Tailwind 4 (`frontend/`), proxy `/api`→:8000,
     build sạch, preview chạy `localhost:5173`. Node 24.20 LTS đã có trên máy.
   - [x] Bước 2: `types.ts` (tầng thứ 4 của hệ schema — interface khớp 1-1 response camelCase)
     + `api.ts` (fetch thuần: ApiError thống nhất 3 shape lỗi + status 0 cho network/timeout,
     AbortController 120s, 5 hàm cho 5 endpoint, FormData không tự set Content-Type). Build sạch.
   - [ ] Bước 3: màn upload CV + danh sách CV (GET/DELETE)
   - [ ] Bước 4: form JD + gọi phân tích (loading UX 5-15s)
   - [ ] Bước 5: trang kết quả (verdict, score 4 trục, skills + evidence, suggestions + resources)
2. **Nâng cấp cân nhắc sau** (đã ghi trade-off ở README 4.9): multi-query theo khía cạnh JD
   nếu thấy retrieval sót; BackgroundTasks cho upload nếu CV dài; RAG hai chiều cho JD file;
   test route health + fixture PDF + 1-2 smoke test `@pytest.mark.live` phủ nốt chỗ trắng coverage.

---

## ▶️ Chạy lại nhanh

```bash
# từ D:\Job_Assistant_AI
venv\Scripts\activate
uvicorn app.main:app --reload
# Swagger: http://localhost:8000/docs
```

Smoke test sau mỗi thay đổi: `python -c "import app.main"` (bắt lỗi config/import sớm).

Flow test tay: `POST /cv/upload` (file .pdf/.txt/.md ≤5MB) → lấy `cvId` →
`POST /analysis` body `{"cvId": "...", "jd": {"title": "...", "content": "..."}}` (≥30 ký tự).

---

## 🚀 Mở phiên mới

Chỉ cần nói: **"Đọc PROGRESS.md + README.md rồi làm tiếp mục N"** — không cần dán lại context.
Memory của Claude Code đã lưu sẵn: bạn là ai, format hỗ trợ (code đầy đủ + 🎓 giải thích,
bàn trade-off trước khi code, đọc file thật để khớp chữ ký, làm từng bước chờ duyệt).
