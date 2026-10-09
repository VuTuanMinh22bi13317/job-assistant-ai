# app/main.py
"""
Điểm khởi động FastAPI.

Chứa:
- Tạo app + CORS cho frontend (localhost:3000).
- GLOBAL EXCEPTION HANDLER: bắt mọi AppException -> trả JSON ErrorResponse thống nhất.
- Đăng ký các router: health, cv, analysis.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import analysis, cv, health
from app.config import settings
from app.core.exceptions import AppException
from app.models.schemas import ErrorResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Nơi khởi tạo/giải phóng tài nguyên dùng chung (vd warm-up client).
    # vector_service/embedding_service đã tạo instance ở tầng module nên
    # hiện chưa cần làm gì ở đây; giữ chỗ để mở rộng sau.
    yield


app = FastAPI(title="Job Assistant AI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================================================
# GLOBAL EXCEPTION HANDLER
# ==========================================================================
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Bắt MỌI exception kế thừa AppException (DocumentProcessingError, ...).

    Vì sao gom về một chỗ:
    - Mọi lỗi nghiệp vụ trả JSON cùng HÌNH DẠNG (ErrorResponse) -> frontend chỉ
      cần xử lý 1 kiểu body lỗi.
    - status_code + error_code lấy thẳng từ exception -> route KHÔNG phải tự
      dựng JSONResponse mỗi lần, chỉ việc `raise DocumentProcessingError(...)`.

    Lưu ý: dùng mode="json" khi dump để enum -> string sạch (xem schemas).
    """
    body = ErrorResponse(error_code=exc.error_code, message=exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(by_alias=True, mode="json"),
    )


# ==========================================================================
# ROUTERS
# ==========================================================================
app.include_router(health.router)
app.include_router(cv.router)
app.include_router(analysis.router)


@app.get("/")
async def root():
    return {"service": "Job Assistant AI", "status": "ok"}