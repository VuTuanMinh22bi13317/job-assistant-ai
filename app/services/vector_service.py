# app/services/vector_service.py
"""
Service quản lý ChromaDB — nơi lưu trữ và truy vấn vector.

Vai trò trong Job Assistant:
- Lưu các đoạn CV (đã biến thành vector 3072 chiều bằng Gemini) vào kho.
- Khi có JD, tìm những đoạn CV gần nghĩa nhất để phục vụ chấm điểm/gợi ý.

Điểm quan trọng: ta TỰ tạo vector bằng embedding_service (Gemini),
rồi đưa vector đã tính sẵn vào Chroma — KHÔNG để Chroma tự sinh embedding.

--- Kiến trúc lưu trữ (quyết định B3) ---
- DÙNG 1 COLLECTION CHUNG (tên cố định trong settings) cho MỌI CV.
- Cô lập từng CV bằng metadata `cv_id` + filter `where={"cv_id": ...}` lúc query.
- Mỗi record giữ đủ metadata: cv_id, section, chunk_id, char_count
  -> bước analysis (chấm điểm) cần `section` để đưa bằng chứng vào prompt.
- Id trong Chroma = f"{cv_id}::{chunk.chunk_id}" để không đụng nhau giữa các CV
  (chunk_id như "experience_0" lặp lại ở nhiều CV khác nhau).
"""
from typing import TYPE_CHECKING

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.services.embedding_service import embedding_service

if TYPE_CHECKING:
    # Chỉ import để type-hint, tránh vòng import lúc chạy thật.
    from app.services.document_service import DocumentChunk


class VectorService:
    def __init__(self) -> None:
        # PersistentClient: lưu dữ liệu xuống ổ đĩa (thư mục CHROMA_PERSIST_DIR),
        # nên tắt server rồi bật lại vẫn còn dữ liệu. Khác với Client() thường
        # (chỉ giữ trong RAM, tắt là mất).
        self.client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),  # tắt telemetry
        )

    def get_or_create_collection(self, name: str):
        """
        Lấy collection theo tên; nếu chưa có thì tạo mới.

        'Collection' trong Chroma giống như một 'bảng' trong DB thường —
        một nhóm vector cùng loại. Ở đây ta dùng MỘT collection chung cho mọi CV,
        phân biệt bằng metadata cv_id (xem docstring đầu file).

        metadata hnsw:space='cosine' báo Chroma dùng 'cosine similarity'
        để đo độ gần giữa các vector.
        """
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(
        self,
        cv_id: str,
        chunks: "list[DocumentChunk]",
        collection_name: str | None = None,
    ) -> int:
        """
        Thêm các chunk của MỘT CV vào collection chung.

        Args:
            cv_id: định danh CV (uuid), gắn vào metadata + prefix id để cô lập.
            chunks: list DocumentChunk (dataclass từ document_service) — mỗi cái
                    có .chunk_id, .section, .content, .char_count.
            collection_name: tên collection; None -> lấy mặc định từ settings.

        Returns:
            số chunk đã thêm.

        Vì sao nhận DocumentChunk thay vì list[str]?
        - Giữ được .section (bước chấm điểm cần) và .chunk_id thật vào metadata.
        - Tránh mất thông tin như bản cũ (chỉ có source + chunk_index).
        """
        if not chunks:
            return 0

        name = collection_name or settings.chroma_collection_name
        collection = self.get_or_create_collection(name)

        # 1) Lấy text từng chunk để embed (đây là 'document' -> is_query=False).
        contents = [c.content for c in chunks]
        embeddings = embedding_service.embed_batch(contents, is_query=False)

        # 2) Id duy nhất toàn collection: prefix cv_id để không đụng CV khác.
        ids = [f"{cv_id}::{c.chunk_id}" for c in chunks]

        # 3) Metadata đầy đủ để filter (cv_id) và phục vụ analysis (section).
        metadatas = [
            {
                "cv_id": cv_id,
                "section": c.section,
                "chunk_id": c.chunk_id,
                "char_count": c.char_count,
            }
            for c in chunks
        ]

        # 4) Đưa vào Chroma. Đã có embeddings -> Chroma KHÔNG tự sinh vector.
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=contents,   # lưu kèm text gốc để lấy lại khi truy vấn
            metadatas=metadatas,
        )
        return len(chunks)

    def query(
        self,
        cv_id: str,
        query_text: str,
        n_results: int = 5,
        collection_name: str | None = None,
    ) -> list[dict]:
        """
        Tìm các chunk CV gần nghĩa nhất với query_text, CHỈ trong CV cv_id.

        Args:
            cv_id: chỉ tìm trong CV này (filter metadata).
            query_text: câu truy vấn (vd một đoạn JD).
            n_results: lấy tối đa bao nhiêu kết quả gần nhất.
            collection_name: None -> mặc định từ settings.

        Returns:
            list dict {text, section, chunk_id, distance}, gần nhất xếp trước.

        `where={"cv_id": cv_id}`: Chroma lọc theo metadata TRƯỚC khi so khoảng
        cách -> đảm bảo không lẫn chunk của CV khác.
        """
        name = collection_name or settings.chroma_collection_name
        collection = self.get_or_create_collection(name)

        # Tạo vector cho câu truy vấn (đây là 'query' -> is_query=True).
        query_embedding = embedding_service.embed_text(query_text, is_query=True)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"cv_id": cv_id},   # <-- cô lập theo CV
        )

        # Chroma trả về list-lồng-list (mỗi query một danh sách). Ta có 1 query
        # nên lấy [0]. Guard trường hợp rỗng (CV chưa có chunk nào khớp).
        if not results["documents"] or not results["documents"][0]:
            return []

        output = []
        for text, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append(
                {
                    "text": text,
                    "section": meta.get("section"),
                    "chunk_id": meta.get("chunk_id"),
                    "distance": dist,
                }
            )
        return output

    def list_cvs(self, collection_name: str | None = None) -> list[dict]:
        """
        Liệt kê các CV đang có trong index (gom theo metadata cv_id).

        Returns:
            list dict {cv_id, chunk_count, sections} — sections giữ thứ tự
            lần đầu gặp. Chroma là NGUỒN SỰ THẬT: CV nào lỡ index hỏng/đã xóa
            sẽ không xuất hiện, dù file có còn nằm trong uploads/.

        Lưu ý hiệu năng: collection.get() kéo TOÀN BỘ metadata về rồi gom bằng
        Python — ổn cho quy mô local (nghìn chunk); nếu sau này CV nhiều tới
        mức đáng kể thì chuyển sang giữ bảng CV riêng (SQLite) thay vì gom.
        """
        name = collection_name or settings.chroma_collection_name
        collection = self.get_or_create_collection(name)

        records = collection.get(include=["metadatas"])  # ids luôn được trả kèm
        tong_hop: dict[str, dict] = {}
        for meta in records["metadatas"]:
            cv_id = meta.get("cv_id")
            if cv_id is None:
                continue  # phòng record lạ không theo chuẩn B3
            item = tong_hop.setdefault(cv_id, {"cv_id": cv_id, "chunk_count": 0, "sections": []})
            item["chunk_count"] += 1
            section = meta.get("section")
            if section and section not in item["sections"]:
                item["sections"].append(section)

        return list(tong_hop.values())

    def has_cv(self, cv_id: str, collection_name: str | None = None) -> bool:
        """CV này có ít nhất 1 chunk trong index không? (limit=1 — rẻ nhất có thể)."""
        name = collection_name or settings.chroma_collection_name
        collection = self.get_or_create_collection(name)
        result = collection.get(where={"cv_id": cv_id}, limit=1)
        return len(result["ids"]) > 0

    def delete_cv(self, cv_id: str, collection_name: str | None = None) -> None:
        """
        Xóa mọi chunk của một CV (dùng khi re-upload hoặc dọn dẹp).
        Xóa theo metadata, KHÔNG xóa cả collection (các CV khác vẫn còn).
        """
        name = collection_name or settings.chroma_collection_name
        collection = self.get_or_create_collection(name)
        collection.delete(where={"cv_id": cv_id})

    def delete_collection(self, name: str) -> None:
        """Xóa hẳn một collection (dùng khi cần làm lại từ đầu toàn bộ)."""
        self.client.delete_collection(name=name)


# Instance dùng chung toàn app
vector_service = VectorService()