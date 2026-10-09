# tests/test_schemas.py
"""
Test schemas — không mock: Pydantic là logic thuần, tất định.

Trọng tâm: các "hợp đồng" mà tầng khác dựa vào:
1. API model serialize ra camelCase (hợp đồng với frontend React).
2. Ràng buộc range chặn điểm rác từ LLM ngay lúc parse.
3. to_response — điểm ráp "LLM sinh nội dung, backend gắn metadata".
4. Enum ra string sạch khi dump mode="json" (bẫy đã gặp, README mục 11).
"""
import pytest
from pydantic import ValidationError

from app.models.schemas import (
    ChunkPreview,
    CVUploadResponse,
    LLMAnalysis,
    LLMSkillMatch,
    LLMSuggestion,
    MatchScore,
    MatchVerdict,
    Priority,
)
from app.services.document_service import DocumentChunk


# ==========================================================================
# 1. camelCase alias — hợp đồng với frontend
# ==========================================================================

def test_api_model_serialize_camel_case():
    # populate_by_name=True: code Python vẫn khởi tạo bằng snake_case bình thường.
    resp = CVUploadResponse(
        cv_id="abc123",
        filename="cv.pdf",
        total_chunks=3,
        sections_detected=["skills", "experience"],
        chunks=[],
    )

    data = resp.model_dump(by_alias=True, mode="json")

    # Serialize ra JSON thì key phải là camelCase (chuẩn JS/React)...
    assert {"cvId", "totalChunks", "sectionsDetected", "createdAt"} <= data.keys()
    # ...và KHÔNG được lộ key snake_case song song.
    assert "cv_id" not in data and "total_chunks" not in data


def test_chunk_preview_map_tu_dataclass_that():
    # Quyết định A1: DocumentChunk (dataclass) là nguồn sự thật duy nhất,
    # schemas chỉ MAP sang ChunkPreview — test chính điểm ráp nối đó.
    chunk = DocumentChunk(chunk_id="skills_0", section="skills", content="x" * 300)

    preview = ChunkPreview.from_chunk(chunk, preview_len=200)

    assert preview.chunk_id == "skills_0"
    assert preview.section == "skills"
    assert preview.char_count == 300          # giữ char_count THẬT của chunk gốc
    assert len(preview.preview) == 200        # nhưng nội dung bị cắt để hiển thị


# ==========================================================================
# 2. Ràng buộc range — LLM trả điểm rác phải nổ ngay lúc parse
# ==========================================================================

@pytest.mark.parametrize("diem_rac", [150, -1])
def test_match_score_ngoai_range_validation_error(diem_rac):
    with pytest.raises(ValidationError):
        MatchScore(
            overall=diem_rac, skills_match=50, experience_match=50, education_match=50
        )


def test_llm_analysis_diem_rac_no_ngay_luc_validate():
    # Đây là hàng rào THẬT sự quan trọng: dict này mô phỏng JSON Gemini trả về.
    # Nhờ Field(ge=0, le=100), điểm 150 chết ở tầng parse — không bao giờ
    # chảy xuống frontend thành thanh điểm 150%.
    du_lieu_llm = {
        "same_field": True,
        "overall_score": 150,   # <-- rác
        "skills_score": 70,
        "experience_score": 70,
        "education_score": 70,
        "summary": "Ung vien kha phu hop.",
    }
    with pytest.raises(ValidationError):
        LLMAnalysis.model_validate(du_lieu_llm)


# ==========================================================================
# 3. Verdict tự suy từ điểm (quyết định A+B) — test đủ BIÊN của từng band
# ==========================================================================

@pytest.mark.parametrize(
    "diem, band",
    [
        (100, MatchVerdict.STRONG_MATCH), (85, MatchVerdict.STRONG_MATCH),
        (84, MatchVerdict.GOOD_MATCH),    (70, MatchVerdict.GOOD_MATCH),
        (69, MatchVerdict.PARTIAL_MATCH), (50, MatchVerdict.PARTIAL_MATCH),
        (49, MatchVerdict.WEAK_MATCH),    (30, MatchVerdict.WEAK_MATCH),
        (29, MatchVerdict.NOT_A_MATCH),   (0, MatchVerdict.NOT_A_MATCH),
    ],
)
def test_verdict_tu_suy_dung_band(diem, band):
    # Test cả 2 MÉP của mỗi band (85 và 100 đều strong, 84 và 70 đều good...)
    # — lỗi ranh giới (>= viết nhầm thành >) là loại bug kinh điển của mapping.
    assert MatchVerdict.from_score(diem) is band


@pytest.mark.parametrize(
    "same_field, diem_llm, overall_mong_doi, verdict_mong_doi",
    [
        (True, 17, 32, MatchVerdict.WEAK_MATCH),    # cùng ngành + điểm đè quá thấp -> floor kéo lên
        (True, 29, 32, MatchVerdict.WEAK_MATCH),    # mép dưới band: 29 vẫn được floor
        (True, 30, 30, MatchVerdict.WEAK_MATCH),    # đã đạt 30 -> floor không đụng vào
        (False, 17, 17, MatchVerdict.NOT_A_MATCH),  # TRÁI ngành -> giữ nguyên điểm thấp
    ],
)
def test_floor_cung_nganh_ap_o_backend(same_field, diem_llm, overall_mong_doi, verdict_mong_doi):
    # [A+B v2] Floor là logic tất định ở backend (vòng eval #1 chứng minh
    # luật floor viết trong prompt bị model bỏ qua) — LLM chỉ cấp same_field.
    llm = LLMAnalysis(
        same_field=same_field,
        overall_score=diem_llm,
        skills_score=10,
        experience_score=10,
        education_score=50,
        summary="Test floor.",
    )
    resp = llm.to_response(cv_id="cv1", jd_title=None)
    assert resp.score.overall == overall_mong_doi   # overall trả về là bản ĐÃ floor
    assert resp.verdict is verdict_mong_doi          # verdict suy từ điểm đã floor


# ==========================================================================
# 4. to_response — backend gắn metadata, nội dung LLM giữ nguyên vẹn
# ==========================================================================

def _llm_analysis_mau() -> LLMAnalysis:
    return LLMAnalysis(
        same_field=True,
        overall_score=75,
        skills_score=71,
        experience_score=70,
        education_score=100,
        summary="Ung vien kha phu hop voi vi tri.",
        matched_skills=[
            LLMSkillMatch(skill="Python", present_in_cv=True, evidence="dung Python 2 nam"),
            LLMSkillMatch(skill="AWS", present_in_cv=False, evidence=None),
        ],
        missing_skills=["AWS"],
        suggestions=[
            LLMSuggestion(priority=Priority.HIGH, title="Hoc AWS", detail="...", related_skill="AWS"),
        ],
    )


def test_to_response_gan_metadata_backend():
    resp = _llm_analysis_mau().to_response(cv_id="cv123", jd_title="Backend Dev")

    # Metadata do BACKEND gắn (LLM không sinh — nguyên tắc đã chốt):
    assert resp.cv_id == "cv123"
    assert resp.jd_title == "Backend Dev"
    assert resp.analyzed_at.tzinfo is not None  # timestamp timezone-aware (UTC)

    # [B] Verdict do backend SUY từ overall_score=75 -> good_match (band 70-84),
    # không phải do LLM chọn:
    assert resp.verdict is MatchVerdict.GOOD_MATCH
    # Nội dung LLM được ráp sang đúng cấu trúc API, không rơi rụng:
    assert resp.score == MatchScore(
        overall=75, skills_match=71, experience_match=70, education_match=100
    )
    assert [s.skill for s in resp.matched_skills] == ["Python", "AWS"]
    assert resp.matched_skills[1].present_in_cv is False
    assert resp.missing_skills == ["AWS"]
    assert resp.suggestions[0].priority is Priority.HIGH


# ==========================================================================
# 4. Enum ra string sạch — bẫy đã gặp (README mục 11)
# ==========================================================================

def test_enum_ra_string_khi_dump_mode_json():
    resp = _llm_analysis_mau().to_response(cv_id="cv123", jd_title=None)

    data = resp.model_dump(by_alias=True, mode="json")

    # mode="json": enum → string sạch đúng như FastAPI serialize qua response_model.
    assert data["verdict"] == "good_match"
    assert data["suggestions"][0]["priority"] == "high"

    # Đối chứng — chính là cái bẫy: model_dump() KHÔNG mode="json" giữ nguyên
    # enum OBJECT (tiện so sánh trong code Python, nhưng đem json.dumps là vỡ).
    assert isinstance(resp.model_dump()["verdict"], MatchVerdict)
