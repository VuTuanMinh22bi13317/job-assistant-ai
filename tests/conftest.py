# tests/conftest.py
"""
Fixture dùng chung cho toàn bộ test suite.

⚠️ THỨ TỰ TỐI QUAN TRỌNG: khối "cô lập môi trường" bên dưới phải chạy TRƯỚC
mọi dòng `import app.*` — vì `settings` (đọc env) và `PersistentClient` (mở
persist dir) đều được tạo NGAY LÚC IMPORT module. Set env sau khi import là
vô tác dụng (client đã trỏ vào data/chroma thật rồi).
"""
import atexit
import os
import shutil
import tempfile
import uuid

# ==========================================================================
# 1. CÔ LẬP MÔI TRƯỜNG — chạy ngay khi pytest import conftest.py này,
#    TRƯỚC khi bất kỳ module app.* nào được import ở bất cứ đâu.
# ==========================================================================
# pydantic-settings ưu tiên: env var thật > file .env > default trong code.
# → set env var ở đây để Settings() (tạo lúc import app.config) nhận đường
#   dẫn TEST, tuyệt đối không đụng data/chroma và data/uploads thật.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="job_assistant_test_")
os.environ["CHROMA_PERSIST_DIR"] = os.path.join(_TEST_DATA_DIR, "chroma")
os.environ["UPLOAD_DIR"] = os.path.join(_TEST_DATA_DIR, "uploads")

# Dọn thư mục tạm khi process pytest thoát (best-effort: ignore_errors=True vì
# trên Windows file SQLite của Chroma đôi khi còn bị giữ handle — sót lại chút
# rác trong %TEMP% vô hại, OS sẽ tự dọn sau).
atexit.register(shutil.rmtree, _TEST_DATA_DIR, True)

# Các import app.* CHỈ ĐƯỢC PHÉP đứng sau khối env bên trên (noqa: E402 là vì vậy).
import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.embedding_service import embedding_service  # noqa: E402
from app.services.llm_service import llm_service  # noqa: E402
from app.services.vector_service import vector_service  # noqa: E402
from tests.fakes import fake_embed, fake_embed_batch  # noqa: E402


# ==========================================================================
# 2. LƯỚI AN TOÀN (autouse) — không test thường nào gọi được Gemini thật
# ==========================================================================

@pytest.fixture(autouse=True)
def fake_embeddings(request, monkeypatch):
    """
    Thay embedding thật bằng fake tất định cho MỌI test (autouse).

    Patch trên INSTANCE embedding_service — vector_service đã import chính
    object này nên mọi nơi dùng chung một bản vá, không cần patch từng module.

    Test đánh dấu @pytest.mark.live được miễn (cần Gemini thật).
    """
    if "live" in request.keywords:
        yield  # test live: giữ nguyên embedding thật
        return
    monkeypatch.setattr(embedding_service, "embed_text", fake_embed)
    monkeypatch.setattr(embedding_service, "embed_batch", fake_embed_batch)
    yield


class _NoRealLLMClient:
    """Chạm vào là nổ — bắt tại trận test nào lỡ gọi Gemini LLM thật."""

    def __getattr__(self, name: str):
        raise AssertionError(
            "Test đang cố gọi Gemini LLM thật! Hãy mock llm_service "
            "(generate_structured/...) hoặc gán stub cho llm_service.client."
        )


@pytest.fixture(autouse=True)
def no_real_llm(request, monkeypatch):
    """
    Chặn đường gọi LLM thật ở tầng client (autouse).

    test_llm_service.py vẫn test được generate_structured THẬT: nó monkeypatch
    llm_service.client bằng stub RIÊNG bên trong test → bản vá của test đè lên
    bản vá guard này (cùng attribute, patch sau thắng), còn logic parse/fallback
    của generate_structured thì chạy nguyên bản.
    """
    if "live" in request.keywords:
        yield
        return
    monkeypatch.setattr(llm_service, "client", _NoRealLLMClient())
    yield


# ==========================================================================
# 3. CÔ LẬP DỮ LIỆU TỪNG TEST
# ==========================================================================

@pytest.fixture
def unique_collection(monkeypatch):
    """
    Mỗi test một collection Chroma riêng (trong cùng persist dir tạm).

    Vì sao làm được dù client đã "đóng băng" lúc import: TÊN collection được
    đọc TẠI THỜI ĐIỂM GỌI (`collection_name or settings.chroma_collection_name`
    nằm TRONG thân hàm) → monkeypatch settings là route/service tự rơi vào
    collection test, không cần truyền tham số.

    Trả về tên collection để test nào cần thì dùng; dọn sạch sau test.
    """
    name = f"test_{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(settings, "chroma_collection_name", name)
    yield name
    try:
        vector_service.delete_collection(name)
    except Exception:
        pass  # test không tạo collection nào → không có gì để dọn


# ==========================================================================
# 4. HTTP CLIENT cho test route
# ==========================================================================

@pytest.fixture
def client():
    """
    FastAPI TestClient — giả lập HTTP request không cần chạy uvicorn.

    Import app.main LƯỜI (trong fixture) để các test thuần logic
    (document_service, schemas) không phải trả giá import cả FastAPI app.
    Dùng `with` để lifespan (startup/shutdown) chạy đúng như server thật.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
