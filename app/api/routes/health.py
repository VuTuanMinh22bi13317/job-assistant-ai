"""
app/api/routes/health.py

Health check cho Job Assistant AI.
- GET /health         -> liveness: process còn sống không (luôn nhanh, không side-effect)
- GET /health/ready   -> readiness: dependency (ChromaDB) có sẵn sàng phục vụ không

Lưu ý thiết kế: KHÔNG gọi Gemini LLM trong health check (tốn quota, rate limit,
latency không ổn định -> không phản ánh đúng "server có ổn không").
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.services.vector_service import vector_service

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Response đơn giản, không cần alias camelCase vì đây không phải domain data
    trả cho frontend hiển thị -- chỉ phục vụ monitoring/devops."""
    status: str


@router.get("", response_model=HealthResponse)
def liveness() -> HealthResponse:
    """
    Liveness probe: chỉ xác nhận app đang chạy và có thể trả response.
    Không kiểm tra dependency (Chroma, Gemini...) -> luôn nhanh, luôn 200
    nếu process FastAPI còn sống.
    """
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
def readiness() -> HealthResponse:
    """
    Readiness probe: xác nhận app không chỉ SỐNG mà còn PHỤC VỤ ĐƯỢC.

    Chroma của ta là PersistentClient NHÚNG trong process (không phải server
    riêng), nên heartbeat() gần như luôn OK miễn process còn sống. Cái có thể
    hỏng thật sự là TẦNG LƯU TRỮ (data/chroma bị xóa, khóa quyền, hỏng file)
    -> phải chạm hẳn vào collection: mở + count() để đi qua đường đọc index thật.

    Route là `def` thường (không async): count() đọc đĩa blocking -> threadpool.
    """
    try:
        vector_service.client.heartbeat()  # client trong process còn hoạt động
        collection = vector_service.get_or_create_collection(
            settings.chroma_collection_name
        )
        collection.count()  # chạm vào index/persist dir thật trên đĩa
    except Exception as exc:
        # Gom MỌI lỗi hạ tầng về một tín hiệu "chưa sẵn sàng" — monitoring chỉ
        # cần biết 503; chi tiết để trong detail cho người debug đọc.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ChromaDB chưa sẵn sàng: {exc}",
        ) from exc
    return HealthResponse(status="ok")
