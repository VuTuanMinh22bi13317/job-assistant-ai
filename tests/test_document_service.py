# tests/test_document_service.py
"""
Test document_service — KHÔNG mock gì cả.

Vì sao không mock: toàn bộ là logic thuần (regex, cắt chuỗi), tất định, chạy
local, không tốn tiền — đúng nguyên tắc phân loại đã chốt: "mock cái không
tất định / tốn tiền / cần mạng; dùng thật cái tất định chạy local".
"""
import pytest

from app.core.exceptions import DocumentProcessingError
from app.services.document_service import DocumentService, chunk_cv_text, clean_text

# CV mẫu CÓ CẤU TRÚC: 2 heading nhận diện được (Experience, Skills)
# + phần preamble (tên, email) trước heading đầu tiên.
CV_CO_CAU_TRUC = """\
Nguyen Van A
Email: nguyenvana@example.com

Experience
Lam backend Python 2 nam tai cong ty X, xay dung REST API voi FastAPI.

Skills
Python, FastAPI, PostgreSQL, Docker.
"""


# ==========================================================================
# 1. ≥2 heading → đi đường section-based (test qua facade process_file)
# ==========================================================================

def test_cv_co_heading_chunk_theo_section(tmp_path):
    cv_file = tmp_path / "cv.txt"
    cv_file.write_text(CV_CO_CAU_TRUC, encoding="utf-8")

    chunks = DocumentService().process_file(cv_file)

    # Preamble (tên, email) trước heading đầu tiên được gộp vào "summary".
    assert {c.section for c in chunks} == {"summary", "experience", "skills"}
    # chunk_id theo format "{section}_{index}".
    assert any(c.chunk_id == "experience_0" for c in chunks)
    # Đường section-based thì KHÔNG chunk nào rơi vào "other".
    assert all(c.section != "other" for c in chunks)


def test_heading_tieng_viet_cung_nhan_dien():
    text = "Kinh nghiệm\nLam viec tai cong ty X hai nam.\n\nKỹ năng\nPython va SQL."
    chunks = chunk_cv_text(text)
    assert {c.section for c in chunks} == {"experience", "skills"}


# ==========================================================================
# 2. Không heading → fallback fixed-size, section = "other"
# ==========================================================================

def test_khong_heading_fallback_fixed_size():
    # Một đoạn văn dài, KHÔNG dòng nào là heading đứng riêng. Chữ "kinh nghiem"
    # nằm GIỮA câu dài (>40 ký tự) nên không được tính là heading —
    # đây chính là cơ chế chống false-positive của _find_section_headings.
    text = (
        "Toi la lap trinh vien backend co hai nam kinh nghiem lam viec thuc te "
        "voi Python va FastAPI, tung xay dung nhieu he thong API cho doanh nghiep."
    )
    chunks = chunk_cv_text(text)

    assert chunks, "Fallback van phai tao ra it nhat 1 chunk"
    assert all(c.section == "other" for c in chunks)
    assert chunks[0].chunk_id == "chunk_0"  # id_prefix của đường fallback


# ==========================================================================
# 3. Section dài hơn chunk_size → sub-chunk + overlap
# ==========================================================================

def test_section_dai_sub_chunk_co_overlap():
    # 5 đoạn văn KHÁC NHAU (đánh số để phân biệt) — nếu dùng text lặp giống
    # hệt nhau thì assert overlap sẽ pass "giả" dù không có overlap.
    paras = [
        f"Doan van so {i}: xay dung he thong backend so {i} cho cong ty, "
        f"toi uu hieu nang truy van va trien khai giam sat loi tren production."
        for i in range(5)
    ]
    long_experience = "\n\n".join(paras)  # ~700 ký tự > chunk_size 600
    text = f"Experience\n{long_experience}\n\nSkills\nPython, FastAPI."

    chunks = chunk_cv_text(text, chunk_size=600, overlap=100)
    exp_chunks = [c for c in chunks if c.section == "experience"]

    # Section dài phải bị tách thành nhiều sub-chunk, đánh số tăng dần.
    assert len(exp_chunks) >= 2
    assert [c.chunk_id for c in exp_chunks] == [
        f"experience_{i}" for i in range(len(exp_chunks))
    ]
    # Overlap: đuôi chunk trước phải xuất hiện lại ở chunk sau
    # (không có overlap thì chunk sau bắt đầu thẳng bằng đoạn văn kế tiếp).
    assert exp_chunks[0].content[-50:] in exp_chunks[1].content
    # Section ngắn đi kèm vẫn nguyên vẹn 1 chunk.
    assert [c.chunk_id for c in chunks if c.section == "skills"] == ["skills_0"]


# ==========================================================================
# 4. clean_text: nối từ ngắt dòng, gộp khoảng trắng, chuẩn hóa NFKC
# ==========================================================================

def test_clean_text_noi_tu_ngat_dong_va_don_dep():
    raw = "Chuyen sau ve develop-\nment  he   thong.\n\n\n\n\nDong cuoi."
    cleaned = clean_text(raw)

    assert "development" in cleaned      # "develop-\nment" được nối lại
    assert "he thong." in cleaned        # khoảng trắng thừa được gộp
    assert "\n\n\n" not in cleaned       # 3+ dòng trống gộp còn tối đa 2


def test_clean_text_chuan_hoa_ligature_nfkc():
    # PDF hay trả về ligature: "ﬁ" (1 ký tự U+FB01) thay vì "fi" (2 ký tự).
    assert clean_text("ﬁnance") == "finance"


# ==========================================================================
# 5. Định dạng không hỗ trợ (.docx) → DocumentProcessingError 422
# ==========================================================================

def test_docx_khong_ho_tro_raise_dung_loai_loi(tmp_path):
    docx = tmp_path / "cv.docx"
    docx.write_bytes(b"gia lap noi dung docx")

    with pytest.raises(DocumentProcessingError) as excinfo:
        DocumentService().process_file(docx)

    assert excinfo.value.status_code == 422
    assert excinfo.value.error_code == "DOCUMENT_PROCESSING_ERROR"


# ==========================================================================
# 6. char_count tự tính đúng (dataclass __post_init__)
# ==========================================================================

def test_char_count_tu_tinh_dung():
    chunks = chunk_cv_text(CV_CO_CAU_TRUC)
    assert chunks
    for c in chunks:
        assert c.char_count == len(c.content)
