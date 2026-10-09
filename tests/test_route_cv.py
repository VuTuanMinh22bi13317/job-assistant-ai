# tests/test_route_cv.py
"""
Test route POST /cv/upload qua TestClient — đi XUYÊN cả chồng HTTP thật:
FastAPI routing → parse multipart → validate đuôi/size → document_service
(THẬT) → embedding (FAKE, autouse) → Chroma (THẬT, collection riêng mỗi test)
→ serialize response_model → global exception handler.

Khác test service: ở đây kiểm tra HỢP ĐỒNG HTTP — status code, JSON camelCase,
shape lỗi ErrorResponse — đúng thứ frontend thật sự nhìn thấy.
"""
from pathlib import Path

from app.config import settings
from app.services.vector_service import vector_service

CV_TXT = """\
Nguyen Van A
Email: nguyenvana@example.com

Experience
Hai nam lam backend python fastapi, xay dung REST API cho he thong ban hang.

Skills
Python, FastAPI, PostgreSQL, Docker.
"""


def _upload(client, filename: str, content: bytes, content_type: str = "text/plain"):
    """Helper gửi multipart/form-data đúng như <input type=file> của frontend."""
    return client.post("/cv/upload", files={"file": (filename, content, content_type)})


# ==========================================================================
# 1. Happy path: 200, đủ thông tin camelCase, VÀ dữ liệu thật sự vào Chroma
# ==========================================================================

def test_upload_ok_tra_du_thong_tin_va_index_vao_chroma(client, unique_collection):
    resp = _upload(client, "cv.txt", CV_TXT.encode("utf-8"))

    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "cv.txt"
    assert data["totalChunks"] >= 1
    assert "experience" in data["sectionsDetected"]
    # Preview chunk đúng shape camelCase cho frontend.
    assert {"chunkId", "section", "charCount", "preview"} <= data["chunks"][0].keys()

    cv_id = data["cvId"]

    # Dây nối tận cùng: chunk THẬT SỰ nằm trong Chroma dưới đúng cv_id —
    # response 200 mà index rỗng thì bước analysis sau đó sẽ 404 oan.
    ket_qua = vector_service.query(cv_id, "python backend", n_results=50)
    assert len(ket_qua) == data["totalChunks"]

    # File đã lưu đúng chỗ (upload_dir đã bị conftest trỏ sang thư mục tạm).
    assert (Path(settings.upload_dir) / f"{cv_id}_cv.txt").exists()


# ==========================================================================
# 2-4. Ba đường lỗi: đều 422 + đúng shape ErrorResponse (hợp đồng lỗi thống nhất)
# ==========================================================================

def test_duoi_sai_422_dung_shape_error_response(client):
    resp = _upload(client, "cv.docx", b"gia lap noi dung docx")

    assert resp.status_code == 422
    data = resp.json()
    # Shape ErrorResponse qua global handler: errorCode (camelCase) + message.
    assert data["errorCode"] == "DOCUMENT_PROCESSING_ERROR"
    assert data["message"]  # có thông điệp cho người đọc, không rỗng


def test_file_rong_422(client):
    resp = _upload(client, "cv.txt", b"")

    assert resp.status_code == 422
    assert resp.json()["errorCode"] == "DOCUMENT_PROCESSING_ERROR"


# ==========================================================================
# 5-7. GET /cv (danh sách) + DELETE /cv/{cv_id} (xóa trọn: index + file gốc)
# ==========================================================================

def test_list_cv_tra_du_thong_tin(client, unique_collection):
    # Collection mới tinh (fixture) -> danh sách phải rỗng trước khi upload.
    assert client.get("/cv").json() == []

    id_1 = _upload(client, "cv_mot.txt", CV_TXT.encode("utf-8")).json()["cvId"]
    id_2 = _upload(client, "cv_hai.txt", CV_TXT.encode("utf-8")).json()["cvId"]

    resp = client.get("/cv")
    assert resp.status_code == 200
    data = {item["cvId"]: item for item in resp.json()}

    assert set(data.keys()) == {id_1, id_2}
    # filename tra được từ uploads/ theo prefix cv_id; totalChunks/sections từ Chroma.
    assert data[id_1]["filename"] == "cv_mot.txt"
    assert data[id_2]["filename"] == "cv_hai.txt"
    assert data[id_1]["totalChunks"] >= 1
    assert "experience" in data[id_1]["sections"]


def test_delete_cv_xoa_ca_index_lan_file(client, unique_collection):
    cv_id = _upload(client, "cv_xoa.txt", CV_TXT.encode("utf-8")).json()["cvId"]
    file_goc = Path(settings.upload_dir) / f"{cv_id}_cv_xoa.txt"
    assert file_goc.exists()

    resp = client.delete(f"/cv/{cv_id}")

    assert resp.status_code == 204
    # Sạch cả 3 nơi: danh sách, index Chroma, file gốc.
    assert all(item["cvId"] != cv_id for item in client.get("/cv").json())
    assert vector_service.query(cv_id, "python", n_results=5) == []
    assert not file_goc.exists()


def test_delete_cv_khong_ton_tai_404(client, unique_collection):
    resp = client.delete("/cv/khong_ton_tai_dau")
    assert resp.status_code == 404
    assert resp.json()["errorCode"] == "CV_NOT_FOUND"


def test_qua_5mb_422_va_khong_de_lai_file_do(client):
    uploads = Path(settings.upload_dir)
    uploads.mkdir(parents=True, exist_ok=True)  # phòng khi test này chạy đầu tiên
    truoc = set(uploads.iterdir())

    resp = _upload(client, "cv.txt", b"a" * (6 * 1024 * 1024))  # 6MB > hạn 5MB

    assert resp.status_code == 422
    assert resp.json()["errorCode"] == "DOCUMENT_PROCESSING_ERROR"
    # Route phải DỌN file ghi dở khi fail giữa chừng (dest_path.unlink) —
    # không được để rác tích tụ trong upload_dir sau mỗi lần upload hỏng.
    assert set(uploads.iterdir()) == truoc
