# tests/test_route_analysis.py
"""
Test route POST /analysis qua TestClient.

Ở đây ĐƠN VỊ TEST là route (retrieve → augment → generate → assemble + mã lỗi),
nên llm_service là DEPENDENCY → mock `generate_structured` (khác test_llm_service
mock tầng SDK vì ở đó generate_structured chính là đơn vị test).

Retrieve vẫn chạy THẬT: fake embedding (autouse) + Chroma thật (collection riêng)
→ test được cả dây nối "chunk lấy từ Chroma có thật sự vào prompt không".
Guard autouse `no_real_llm` kiêm luôn vai trò khẳng định: nhánh 404 KHÔNG được
đụng tới LLM (đụng là poison object nổ AssertionError ngay).
"""
import pytest

from app.core.exceptions import LLMResponseError
from app.models.schemas import (
    LLMAnalysis,
    LLMSkillMatch,
    LLMSuggestion,
    Priority,
)
from app.services.document_service import DocumentChunk
from app.services.llm_service import llm_service
from app.services.vector_service import vector_service

JD_BODY = {
    "title": "Junior Backend Engineer",
    "content": "Tuyen junior backend python fastapi, yeu cau postgresql, docker va git.",
}


def _index_cv(cv_id: str) -> list[DocumentChunk]:
    """Nạp sẵn 1 CV nhỏ vào Chroma (đường tắt qua service — route upload đã
    có test riêng, không cần đi lại từ đầu)."""
    chunks = [
        DocumentChunk(
            chunk_id="skills_0", section="skills",
            content="python fastapi postgresql docker",
        ),
        DocumentChunk(
            chunk_id="experience_0", section="experience",
            content="hai nam lam backend xay dung REST API ban hang",
        ),
    ]
    vector_service.add_documents(cv_id, chunks)
    return chunks


def _phan_tich_mau() -> LLMAnalysis:
    """Kết quả LLM giả — hợp lệ theo schema, đủ nhánh dữ liệu để test serialize."""
    return LLMAnalysis(
        same_field=True,
        overall_score=75,  # -> backend tự suy verdict "good_match" (band 70-84)
        skills_score=71,
        experience_score=70,
        education_score=100,
        summary="Ung vien kha phu hop voi vi tri.",
        matched_skills=[
            LLMSkillMatch(skill="Python", present_in_cv=True, evidence="python fastapi"),
        ],
        missing_skills=["AWS"],
        suggestions=[
            LLMSuggestion(priority=Priority.HIGH, title="Hoc AWS", detail="...", related_skill="AWS"),
        ],
    )


# ==========================================================================
# 1. Happy path: 200 camelCase + chunk từ Chroma thật sự đi vào prompt
# ==========================================================================

def test_analysis_200_camel_case_va_prompt_nhan_dung_chunk(
    client, unique_collection, monkeypatch
):
    chunks = _index_cv("cv_hp")

    goi_llm = {}  # "ghi âm" cuộc gọi để assert dây nối retrieve → prompt

    def fake_generate_structured(*, prompt, response_schema, system_instruction=None,
                                 temperature=0.2):
        goi_llm.update(
            prompt=prompt, response_schema=response_schema,
            system_instruction=system_instruction, temperature=temperature,
        )
        return _phan_tich_mau()

    monkeypatch.setattr(llm_service, "generate_structured", fake_generate_structured)

    resp = client.post("/analysis", json={"cvId": "cv_hp", "jd": JD_BODY})

    assert resp.status_code == 200
    data = resp.json()
    # Metadata backend gắn qua to_response:
    assert data["cvId"] == "cv_hp"
    assert data["jdTitle"] == "Junior Backend Engineer"
    assert "analyzedAt" in data
    # Nội dung LLM serialize camelCase + enum ra string sạch:
    assert data["verdict"] == "good_match"
    assert data["score"] == {
        "overall": 75, "skillsMatch": 71, "experienceMatch": 70, "educationMatch": 100,
    }
    assert data["matchedSkills"][0]["presentInCv"] is True
    assert data["missingSkills"] == ["AWS"]
    assert data["suggestions"][0]["priority"] == "high"
    # Dây nối enrich: suggestion có related_skill="AWS" phải được backend gắn
    # link học tập (catalog tất định) ngay trong _run_analysis.
    assert data["suggestions"][0]["resources"]
    assert data["suggestions"][0]["resources"][0]["url"].startswith("https://")

    # Dây nối RAG: prompt phải chứa JD + nội dung chunk lấy từ Chroma,
    # kèm nhãn section (thứ SYSTEM_INSTRUCTION cần để chấm đúng trục).
    assert JD_BODY["content"] in goi_llm["prompt"]
    for c in chunks:
        assert c.content in goi_llm["prompt"]
    assert "section: skills" in goi_llm["prompt"]
    # Và cấu hình gọi LLM đúng như quyết định đã chốt:
    assert goi_llm["response_schema"] is LLMAnalysis
    assert goi_llm["temperature"] == 0.0  # [A] hạ từ 0.2 sau khi đo variance ±15
    assert goi_llm["system_instruction"]  # có system instruction, không rỗng


# ==========================================================================
# 2. cv_id không tồn tại → 404 CV_NOT_FOUND, KHÔNG đụng tới LLM
# ==========================================================================

def test_cv_id_khong_ton_tai_404(client, unique_collection):
    # Không mock generate_structured: nếu route lỡ gọi LLM trước khi check 404,
    # guard autouse no_real_llm sẽ nổ AssertionError → test đỏ đúng chỗ.
    resp = client.post("/analysis", json={"cvId": "khong_ton_tai", "jd": JD_BODY})

    assert resp.status_code == 404
    assert resp.json()["errorCode"] == "CV_NOT_FOUND"


# ==========================================================================
# 3. LLM lỗi → 502 đúng shape ErrorResponse, không rò stacktrace
# ==========================================================================

def test_llm_loi_502_khong_ro_stacktrace(client, unique_collection, monkeypatch):
    _index_cv("cv_loi")

    def fake_fail(**kwargs):
        raise LLMResponseError("Output cua Gemini khong khop schema LLMAnalysis")

    monkeypatch.setattr(llm_service, "generate_structured", fake_fail)

    resp = client.post("/analysis", json={"cvId": "cv_loi", "jd": JD_BODY})

    assert resp.status_code == 502
    data = resp.json()
    assert data["errorCode"] == "LLM_RESPONSE_ERROR"
    # Body lỗi CHỈ có shape ErrorResponse — không lộ nội bộ ra client:
    assert set(data.keys()) == {"errorCode", "message", "detail"}
    assert "Traceback" not in resp.text


# ==========================================================================
# 4-6. POST /analysis/direct — upload + phân tích trong MỘT request (multipart)
# ==========================================================================

CV_DIRECT = """\
Nguyen Van B
Email: b@example.com

Experience
Ba nam lam backend python fastapi cho cong ty thuong mai dien tu.

Skills
Python, FastAPI, PostgreSQL.
"""


def test_direct_200_upload_va_phan_tich_mot_phat(client, unique_collection, monkeypatch):
    monkeypatch.setattr(
        llm_service, "generate_structured", lambda **kwargs: _phan_tich_mau()
    )

    # multipart: file + form fields — đúng cách frontend gửi <form>; JD nhiều
    # dòng đi qua form field nên KHÔNG cần escape \n (điểm trừ #2 đã chết).
    resp = client.post(
        "/analysis/direct",
        files={"file": ("cv.txt", CV_DIRECT.encode("utf-8"), "text/plain")},
        data={"jdTitle": "Junior Backend Engineer", "jdContent": JD_BODY["content"]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["verdict"] == "good_match"
    assert data["jdTitle"] == "Junior Backend Engineer"
    # cvId do backend sinh trong lúc ingest (uuid4().hex = 32 ký tự hex)...
    cv_id = data["cvId"]
    assert len(cv_id) == 32
    # ...và CV THẬT SỰ được index dưới cv_id đó (ingest_cv dùng chung với
    # /cv/upload) — client tái dùng cvId này cho /analysis lần sau được ngay.
    assert vector_service.query(cv_id, "python backend", n_results=5)


def test_direct_jd_qua_ngan_422(client):
    resp = client.post(
        "/analysis/direct",
        files={"file": ("cv.txt", CV_DIRECT.encode("utf-8"), "text/plain")},
        data={"jdContent": "ngan qua"},  # < min_length 30 -> FastAPI chặn ở tầng form
    )
    assert resp.status_code == 422


def test_direct_duoi_file_sai_422_di_qua_duong_ingest_chung(client):
    resp = client.post(
        "/analysis/direct",
        files={"file": ("cv.docx", b"gia lap docx", "application/octet-stream")},
        data={"jdContent": JD_BODY["content"]},
    )
    # Lỗi từ ingest_cv (đường dùng chung) -> vẫn đúng shape ErrorResponse.
    assert resp.status_code == 422
    assert resp.json()["errorCode"] == "DOCUMENT_PROCESSING_ERROR"
