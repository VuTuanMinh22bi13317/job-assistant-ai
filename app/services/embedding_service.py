# app/services/embedding_service.py
"""
Service tạo embedding: chuyển text (chuỗi chữ) thành vector (list số float).
Vector này là "toạ độ ngữ nghĩa" của text — dùng để so sánh mức độ giống nhau
giữa CV và JD, và để lưu vào ChromaDB cho tìm kiếm ngữ nghĩa.
"""
from google import genai
from google.genai import types

from app.config import settings


class EmbeddingService:
    def __init__(self) -> None:
        # Tạo client MỘT lần và tái sử dụng. Client giữ cấu hình + kết nối,
        # nên không nên tạo lại mỗi lần gọi (tốn tài nguyên).
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_embedding_model

    def embed_text(self, text: str, is_query: bool = False) -> list[float]:
        """
        Tạo embedding cho MỘT đoạn text.

        Args:
            text: đoạn văn bản cần chuyển thành vector.
            is_query: True nếu đây là câu truy vấn (JD đi tìm),
                      False nếu đây là tài liệu được lưu trữ (đoạn CV).
                      Xem phần giải thích task_type bên dưới.

        Returns:
            list[float]: vector embedding.
        """
        # task_type giúp model tối ưu embedding cho đúng mục đích:
        # - RETRIEVAL_QUERY: text là câu hỏi/truy vấn đi tìm
        # - RETRIEVAL_DOCUMENT: text là tài liệu nằm trong kho để bị tìm
        task_type = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"

        result = self.client.models.embed_content(
            model=self.model,
            contents=text,  # gemini-embedding-001 chỉ nhận 1 text/request
            config=types.EmbedContentConfig(task_type=task_type),
        )
        # result.embeddings là list; lấy phần tử đầu, thuộc tính .values là vector
        return result.embeddings[0].values

    def embed_batch(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        """
        Tạo embedding cho NHIỀU đoạn text.
        Vì gemini-embedding-001 chỉ nhận 1 text/request, ta lặp qua từng đoạn.
        (Đây là điểm đánh đổi — xem phần trade-off.)
        """
        return [self.embed_text(t, is_query=is_query) for t in texts]


# Instance dùng chung toàn app
embedding_service = EmbeddingService()