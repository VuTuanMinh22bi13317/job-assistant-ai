# tests/test_vector_service.py
"""
Test vector_service — Chroma THẬT (persist vào dir tạm, xem conftest) +
embedding FAKE tất định (autouse fixture fake_embeddings).

Vì sao Chroma thật mà embedding fake:
- Chroma: hành vi filter `where`, id trùng, delete theo metadata... là THỨ TA
  ĐANG TEST — fake Chroma thì test tự nói chuyện với chính mình, vô nghĩa.
  Nó tất định + chạy local → đủ tiêu chuẩn "dùng thật".
- Embedding: gọi Gemini thật thì tốn tiền/mạng/không tất định → fake, nhưng
  fake BẢO TOÀN quan hệ "giống nhau hơn thì gần nhau hơn" để test ranking.

Mọi test dùng fixture `unique_collection`: mỗi test một collection riêng,
route/service tự rơi vào đó vì tên collection resolve LÚC GỌI qua settings.
"""
from app.services.document_service import DocumentChunk
from app.services.vector_service import vector_service


def _chunks(*contents: str, section: str = "skills") -> list[DocumentChunk]:
    """Helper dựng DocumentChunk thật (đúng dataclass A1), chunk_id đánh số
    theo section — cố tình để 2 CV khác nhau sinh ra chunk_id TRÙNG NHAU
    (skills_0, skills_1...) như ngoài đời."""
    return [
        DocumentChunk(chunk_id=f"{section}_{i}", section=section, content=c)
        for i, c in enumerate(contents)
    ]


# ==========================================================================
# 1. Cô lập B3: 2 CV trùng chunk_id không được đè/lẫn nhau
# ==========================================================================

def test_hai_cv_trung_chunk_id_khong_dung_nhau(unique_collection):
    # Cả 2 CV đều có chunk_id "skills_0" — nếu id trong Chroma không được
    # prefix cv_id (f"{cv_id}::{chunk_id}"), bản add sau sẽ ĐÈ bản trước.
    vector_service.add_documents("cv_a", _chunks("python fastapi backend"))
    vector_service.add_documents("cv_b", _chunks("java spring boot enterprise"))

    ket_qua_a = vector_service.query("cv_a", "lap trinh python", n_results=5)
    ket_qua_b = vector_service.query("cv_b", "lap trinh java", n_results=5)

    # Mỗi CV chỉ thấy đúng chunk CỦA MÌNH — không đè, không lẫn.
    assert {r["text"] for r in ket_qua_a} == {"python fastapi backend"}
    assert {r["text"] for r in ket_qua_b} == {"java spring boot enterprise"}


# ==========================================================================
# 2. Query trả đúng thứ hạng ngữ nghĩa trong phạm vi 1 cv_id
# ==========================================================================

def test_query_xep_chunk_lien_quan_len_dau(unique_collection):
    vector_service.add_documents(
        "cv_a",
        _chunks(
            "python fastapi xay dung REST API backend",   # liên quan tới query
            "nau an lam banh ngot va pha che cafe",        # hoàn toàn không
        ),
    )

    ket_qua = vector_service.query("cv_a", "python backend API", n_results=2)

    assert len(ket_qua) == 2
    # Chunk gần nghĩa nhất đứng đầu (distance nhỏ hơn).
    assert "python" in ket_qua[0]["text"]
    assert ket_qua[0]["distance"] < ket_qua[1]["distance"]


# ==========================================================================
# 3. Metadata `section` + `chunk_id` được giữ nguyên qua vòng lưu-truy vấn
# ==========================================================================

def test_giu_section_va_chunk_id_trong_ket_qua(unique_collection):
    chunks = _chunks("python fastapi postgresql", section="skills")
    chunks += _chunks("hai nam lam backend tai cong ty X", section="experience")
    vector_service.add_documents("cv_a", chunks)

    ket_qua = vector_service.query("cv_a", "kinh nghiem lam viec backend", n_results=5)

    # Bước analysis cần section để dán nhãn trích đoạn trong prompt —
    # nếu metadata rơi rụng ở đây, prompt hạ nguồn sẽ mù thông tin.
    tra_ve = {(r["section"], r["chunk_id"]) for r in ket_qua}
    assert tra_ve == {("skills", "skills_0"), ("experience", "experience_0")}


# ==========================================================================
# 4. delete_cv chỉ xóa đúng CV đó, không lây sang CV khác
# ==========================================================================

def test_delete_cv_khong_lay_sang_cv_khac(unique_collection):
    vector_service.add_documents("cv_a", _chunks("python fastapi backend"))
    vector_service.add_documents("cv_b", _chunks("java spring boot enterprise"))

    vector_service.delete_cv("cv_a")

    # CV đã xóa → query rỗng (đây cũng chính là bất biến mà route analysis
    # dựa vào để suy ra 404 CVNotFoundError).
    assert vector_service.query("cv_a", "python", n_results=5) == []
    # CV còn lại không bị ảnh hưởng.
    assert len(vector_service.query("cv_b", "java", n_results=5)) == 1


# ==========================================================================
# 5. n_results lớn hơn số chunk trong CV → không nổ, trả hết những gì có
# ==========================================================================

def test_n_results_lon_hon_so_chunk_khong_no(unique_collection):
    vector_service.add_documents("cv_a", _chunks("python backend", "sql database"))

    # Chroma chỉ in warning "updating n_results" (vô hại — xem README mục 11),
    # code không được crash và phải trả đủ 2 chunk đang có.
    ket_qua = vector_service.query("cv_a", "python", n_results=10)

    assert len(ket_qua) == 2
