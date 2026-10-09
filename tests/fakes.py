# tests/fakes.py
"""
Fake embedding TẤT ĐỊNH cho test — thay thế Gemini embedding.

Vì sao fake thay vì gọi thật:
- Gemini embedding tốn tiền + cần mạng + rate limit -> test chậm, mong manh, tốn quota.
- Fake tất định: cùng input -> cùng vector, MÃI MÃI -> test lặp lại được, chạy offline.

Cơ chế: bag-of-words hashing.
- Mỗi từ được hash (md5) -> 1 vị trí trong vector FAKE_DIM chiều -> cộng 1 tại đó.
- Hai text chung nhiều từ -> vector gần nhau (cosine) -> giữ được tính chất
  "text giống nhau thì nằm gần nhau", đủ để test retrieval hoạt động đúng chiều.
- Chuẩn hóa L2 để cosine distance của Chroma nằm trong khoảng [0, 2] đẹp.

⚠️ Dùng hashlib.md5 chứ KHÔNG dùng hash() built-in: hash() của Python bị
RANDOMIZE theo process (hash randomization / PYTHONHASHSEED) -> cùng một từ
cho giá trị khác nhau giữa 2 lần chạy pytest -> test hết tất định. md5 thì
ổn định vĩnh viễn trên mọi máy, mọi lần chạy.
"""
import hashlib
import math

# Khớp số chiều thật của gemini-embedding-001 — để nếu sau này có test nào
# so sánh dimension với config/Chroma thì fake không bị lệch.
FAKE_DIM = 3072


def fake_embed(text: str, is_query: bool = False) -> list[float]:
    """Chữ ký khớp 100% embedding_service.embed_text(text, is_query)."""
    vec = [0.0] * FAKE_DIM
    for word in text.lower().split():
        digest = hashlib.md5(word.encode("utf-8")).digest()
        # Lấy 4 byte đầu của digest làm số nguyên -> chọn "ô" trong vector.
        idx = int.from_bytes(digest[:4], "little") % FAKE_DIM
        vec[idx] += 1.0

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        # Text rỗng/toàn khoảng trắng -> trả vector đơn vị cố định,
        # tránh chia 0 và tránh NaN khi Chroma tính cosine với vector 0.
        vec[0] = 1.0
        return vec
    return [v / norm for v in vec]


def fake_embed_batch(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """Chữ ký khớp 100% embedding_service.embed_batch(texts, is_query)."""
    return [fake_embed(t, is_query=is_query) for t in texts]
