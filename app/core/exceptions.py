class AppException(Exception):
    """Base exception cho toàn bộ app. Mọi custom exception nên kế thừa từ đây
    để main.py có thể bắt bằng 1 exception handler DUY NHẤT (sẽ thêm khi làm
    routes ở bước 3) và trả JSON response thống nhất cho toàn bộ API, thay vì
    mỗi route tự try/except và tự format lỗi theo ý riêng.
    """

    def __init__(self, message: str, status_code: int = 400, error_code: str = "APP_ERROR"):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


class DocumentProcessingError(AppException):
    """Lỗi khi đọc/parse file CV: PDF hỏng, định dạng không hỗ trợ, file rỗng..."""

    def __init__(self, message: str):
        super().__init__(message, status_code=422, error_code="DOCUMENT_PROCESSING_ERROR")


class CVNotFoundError(AppException):
    """cv_id không có chunk nào trong ChromaDB: chưa upload, gõ sai id, hoặc đã bị xóa.

    404 (Not Found) chứ không phải 422: request hợp lệ về hình thức,
    chỉ là tài nguyên được trỏ tới không tồn tại.
    """

    def __init__(self, cv_id: str):
        super().__init__(
            f"Không tìm thấy CV '{cv_id}'. Hãy upload CV trước qua POST /cv/upload.",
            status_code=404,
            error_code="CV_NOT_FOUND",
        )


class LLMResponseError(AppException):
    """Gemini trả về output không parse/validate được theo schema mong đợi.

    502 (Bad Gateway): lỗi nằm ở dịch vụ upstream (Gemini) chứ không phải
    do client gửi sai — client thử lại sau là hợp lý.
    """

    def __init__(self, message: str):
        super().__init__(message, status_code=502, error_code="LLM_RESPONSE_ERROR")