# app/api/routes/cv.py
"""
Route upload CV: nhận file -> lưu đĩa -> parse+chunk (document_service)
-> embed+index vào ChromaDB (vector_service) -> trả cv_id + preview chunk.

Luồng A trong README. Xử lý ĐỒNG BỘ (sync): client chờ xong mới nhận response.
Nếu sau này CV rất dài/nhiều chunk khiến embed chậm -> cân nhắc BackgroundTasks.

[Refactor gói "giảm điểm trừ khi test"] Ruột của luồng nạp CV được tách thành
`ingest_cv()` để /analysis/direct (upload + phân tích 1 phát) tái dùng —
MỘT nguồn sự thật cho việc nạp CV, các route chỉ là "cửa" mỏng đắp lên.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.core.exceptions import CVNotFoundError, DocumentProcessingError
from app.models.schemas import CVListItem, CVUploadResponse, ChunkPreview
from app.services.document_service import DocumentChunk, DocumentService
from app.services.vector_service import vector_service

# prefix + tags: gom nhóm endpoint, hiện đẹp trong /docs (OpenAPI).
router = APIRouter(prefix="/cv", tags=["CV"])

# DocumentService không giữ state theo request -> tạo 1 instance dùng chung.
# chunk_size/overlap lấy từ config để chỉnh tập trung, không hardcode.
document_service = DocumentService(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
)

# Giới hạn phòng thủ ngay tại tầng route (fail sớm, thông điệp rõ).
ALLOWED_SUFFIXES = {".pdf", ".txt", ".md"}
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB — CV bình thường nhỏ hơn nhiều


@dataclass
class IngestedCV:
    """Kết quả nạp một CV vào hệ thống — đủ cho mọi route dựng response riêng."""
    cv_id: str
    filename: str
    chunks: list[DocumentChunk]


async def ingest_cv(file: UploadFile) -> IngestedCV:
    """
    Toàn bộ luồng nạp CV: validate -> lưu đĩa -> chunk -> embed + index Chroma.

    Dùng chung bởi POST /cv/upload và POST /analysis/direct. Là `async` vì cần
    `await file.read()`; các bước blocking (parse file, gọi Gemini embed) được
    đẩy sang threadpool để không chặn event loop.

    Raises:
        DocumentProcessingError (422): đuôi không hỗ trợ / file rỗng / quá 5MB
                                       / không trích xuất được text.
    """
    # --- 1. Validate đuôi file ---
    original_name = file.filename or "cv"
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentProcessingError(
            f"Định dạng không hỗ trợ: '{suffix}'. Chỉ nhận: {', '.join(sorted(ALLOWED_SUFFIXES))}."
        )

    # --- 2. Sinh cv_id + đường dẫn lưu ---
    cv_id = uuid.uuid4().hex  # 32 ký tự hex, không gạch nối -> gọn cho id/tên file
    uploads_dir = Path(settings.upload_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    dest_path = uploads_dir / f"{cv_id}_{original_name}"

    # Đọc + kiểm dung lượng trong lúc ghi (tránh giữ cả file lớn trong RAM 2 lần).
    size = 0
    with dest_path.open("wb") as buffer:
        while True:
            block = await file.read(1024 * 1024)  # đọc 1MB mỗi lần
            if not block:
                break
            size += len(block)
            if size > MAX_FILE_BYTES:
                buffer.close()
                dest_path.unlink(missing_ok=True)  # dọn file dở
                raise DocumentProcessingError(
                    f"File quá lớn (>{MAX_FILE_BYTES // (1024*1024)}MB)."
                )
            buffer.write(block)

    if size == 0:
        dest_path.unlink(missing_ok=True)
        raise DocumentProcessingError("File rỗng.")

    # --- 3. Parse + chunk ---
    # process_file đọc đĩa + chạy regex (blocking) -> threadpool. Nó tự raise
    # DocumentProcessingError nếu format lạ / PDF scan ảnh.
    chunks = await run_in_threadpool(document_service.process_file, dest_path)
    if not chunks:
        raise DocumentProcessingError("Không tạo được chunk nào từ CV.")

    # --- 4. Embed + index vào Chroma (B3) ---
    # add_documents gọi Gemini embed từng chunk (blocking network) -> threadpool,
    # nếu để trần trong async def sẽ chặn event loop suốt nhiều giây.
    await run_in_threadpool(vector_service.add_documents, cv_id=cv_id, chunks=chunks)

    return IngestedCV(cv_id=cv_id, filename=original_name, chunks=chunks)


@router.post("/upload", response_model=CVUploadResponse)
async def upload_cv(file: UploadFile = File(...)) -> CVUploadResponse:
    """
    Upload + index một CV (không phân tích — dùng khi muốn 1 CV chạy nhiều JD).

    Ruột nằm ở ingest_cv(); route chỉ dựng CVUploadResponse (preview chunk
    để client kiểm chứng chất lượng chunking).

    Lỗi -> DocumentProcessingError (422), global handler trả ErrorResponse.
    """
    ingested = await ingest_cv(file)

    # sections_detected: tập các section xuất hiện, giữ thứ tự lần đầu gặp.
    seen: list[str] = []
    for c in ingested.chunks:
        if c.section not in seen:
            seen.append(c.section)

    return CVUploadResponse(
        cv_id=ingested.cv_id,
        filename=ingested.filename,
        total_chunks=len(ingested.chunks),
        sections_detected=seen,
        chunks=[ChunkPreview.from_chunk(c) for c in ingested.chunks],
    )


def _tim_filename(cv_id: str) -> str | None:
    """Tra tên file gốc trong uploads/ theo quy ước '{cv_id}_{filename}'.
    Trả None nếu file đã bị xóa tay — index Chroma vẫn là nguồn sự thật."""
    uploads_dir = Path(settings.upload_dir)
    if not uploads_dir.exists():
        return None
    for f in uploads_dir.glob(f"{cv_id}_*"):
        return f.name[len(cv_id) + 1:]  # cắt prefix "cv_id_"
    return None


@router.get("", response_model=list[CVListItem])
def list_cvs() -> list[CVListItem]:
    """
    Danh sách CV đang có trong index — hết cảnh quên cvId phải upload lại.

    Nguồn sự thật: metadata Chroma (vector_service.list_cvs); tên file chỉ là
    thông tin trang trí tra thêm từ uploads/. Route `def` thường: Chroma đọc
    đĩa blocking -> FastAPI tự chạy threadpool.
    """
    return [
        CVListItem(
            cv_id=item["cv_id"],
            filename=_tim_filename(item["cv_id"]),
            total_chunks=item["chunk_count"],
            sections=item["sections"],
        )
        for item in vector_service.list_cvs()
    ]


# response_model=None TƯỜNG MINH: vì file này dùng `from __future__ import
# annotations`, FastAPI đọc annotation `-> None` thành class NoneType và tưởng
# đó là response model -> nổ assertion "204 must not have a response body"
# ngay lúc đăng ký route. Khai None tường minh thì FastAPI bỏ qua hẳn.
@router.delete("/{cv_id}", status_code=204, response_model=None)
def delete_cv(cv_id: str) -> None:
    """
    Xóa hẳn một CV: chunk trong Chroma + file gốc trong uploads/.

    - 404 CV_NOT_FOUND nếu cv_id không có trong index (check trước, không xóa mù).
    - 204 No Content khi xong — chuẩn REST cho delete thành công, không cần body.
    """
    if not vector_service.has_cv(cv_id):
        raise CVNotFoundError(cv_id)

    vector_service.delete_cv(cv_id)

    # Dọn cả file gốc (best-effort — file bị xóa tay từ trước cũng không sao).
    uploads_dir = Path(settings.upload_dir)
    if uploads_dir.exists():
        for f in uploads_dir.glob(f"{cv_id}_*"):
            f.unlink(missing_ok=True)
