# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Tập trung toàn bộ config vào một class.
    pydantic-settings sẽ TỰ ĐỘNG đọc từ file .env và ép kiểu.
    Nếu thiếu biến bắt buộc -> app báo lỗi ngay khi khởi động,
    thay vì lỗi mơ hồ lúc chạy giữa chừng.
    """
    # Gemini
    gemini_api_key: str                              # bắt buộc, không có default
    gemini_model: str = "gemini-2.0-flash"           # có default nếu .env không khai báo
    gemini_embedding_model: str = "text-embedding-004"

    # ChromaDB
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "cv_chunks"        # 1 collection CHUNG cho mọi CV (quyết định B3)

    # Chunking (document_service dùng qua cv.py)
    chunk_size: int = 600                            # ~ ký tự mỗi chunk (xấp xỉ token, không phải token thật)
    chunk_overlap: int = 100                         # số ký tự cuối chunk trước lặp lại ở đầu chunk sau

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000                             # tự ép "8000" (string) -> int
    upload_dir: str = "./data/uploads"

    # CORS — main.py dùng cho frontend React.
    # LƯU Ý: nếu muốn override qua .env, list[str] phải viết dạng JSON:
    # CORS_ORIGINS=["http://localhost:3000"]
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Nói cho pydantic biết đọc file nào, encoding gì
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


# Tạo MỘT instance dùng chung toàn app (import nó ở mọi nơi cần config)
settings = Settings()