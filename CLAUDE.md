# CLAUDE.md — Job Assistant AI

Dự án: AI phân tích CV vs Job Description (JD), chấm điểm phù hợp, gợi ý cải thiện CV.
**`README.md` là living document — nguồn sự thật của project. Đọc nó TRƯỚC khi làm bất kỳ việc gì.**

---

## Về người dùng (calibrate độ sâu giải thích)

Developer mới ra trường, đang **học LLM Engineering** bằng cách tự build project này để đi phỏng vấn.

- Đã biết: C#, Python, C++, ReactJS, React Native, PL/SQL (Oracle + PostgreSQL), Dify, vLLM.
  → **KHÔNG giải thích khái niệm lập trình/OOP cơ bản** (class, dataclass, type hint, decorator...).
- Đang học từ đầu: RAG, embedding, vector DB, chunking, prompt engineering, testing hệ thống LLM.
  → Phần này **giải thích sâu, đầy đủ concept**.

## Cách làm việc (QUAN TRỌNG — áp dụng cho MỌI thay đổi)

1. Đây **KHÔNG phải vibe code**. Mục tiêu là HIỂU SÂU, không phải chỉ xong việc.
2. Code đầy đủ, chạy được, có comment giải thích các dòng quan trọng.
3. Sau mỗi đoạn code phải có phần **"🎓 Giải thích để học"** — tại sao làm vậy, concept đằng sau,
   bẫy liên quan.
4. Có nhiều cách làm → nêu **trade-off** rõ ràng (bảng so sánh nếu cần) và **bàn TRƯỚC khi code**
   nếu là quyết định thiết kế đáng bàn. Chờ người dùng chốt rồi mới viết.
5. **Làm từng bước nhỏ, dừng lại chờ duyệt** — KHÔNG tự chạy một mạch nhiều file/nhiều bước.
   Ví dụ: viết `conftest.py` → giải thích → chờ duyệt → mới viết file test tiếp theo.
6. Gọi hàm/service hiện có phải **khớp 100% chữ ký thật** — đọc file thật trước, KHÔNG đoán tên
   hàm/tham số.
7. Sau mỗi thay đổi có ý nghĩa: cập nhật `README.md` (mục 3, 6, 10) cho khớp.
8. Trả lời bằng tiếng Việt.

---

## Tech stack & môi trường

- Windows, Python **3.12** (KHÔNG 3.14 — thiếu wheel), venv, code tại `D:\job_assistant_ai`.
- Backend: FastAPI. Frontend: ReactJS (chưa làm).
- LLM SDK: **`google-genai` MỚI** (`from google import genai`, client pattern).
  KHÔNG phải `google-generativeai` cũ. Version ghim: `google-genai 2.8.0`.
- Model text: `gemini-2.5-flash`. Model embedding: `gemini-embedding-001`
  (3072 chiều, mỗi request 1 text, có `task_type`).
- Vector DB: ChromaDB local `PersistentClient`, cosine. Version: `chromadb 0.5.23`, ghim `posthog<6.0.0`.
- PDF: `pypdf` (KHÔNG PyPDF2 — deprecated).
- Validation: Pydantic v2 + pydantic-settings.

## Cấu trúc

```
app/config.py, app/main.py
app/api/routes/     health.py, cv.py, analysis.py
app/services/       llm_service.py, embedding_service.py, vector_service.py, document_service.py
app/models/schemas.py
app/core/exceptions.py
data/{uploads, chroma}
tests/              pytest (52 test, fake Gemini — miễn phí)
eval/               eval harness (dataset 20 case nhãn tay + run_eval.py + reports/)
frontend/           Vite + React 19 + TS + Tailwind v4 — hoàn chỉnh (types.ts/api.ts + 4 component)
```

---

## Quyết định thiết kế ĐÃ CHỐT (đừng đề xuất lại trừ khi được hỏi)

- **KHÔNG dùng LangChain** — tự viết chunking để hiểu sâu.
- **Chunking hybrid**: section-based (regex heading CV, Anh + Việt, cần ≥2 section) → sub-chunk
  đoạn/câu có overlap nếu section quá `chunk_size` (600 ký tự) → fallback fixed-size.
- **DocumentChunk (A1)**: định nghĩa 1 nơi duy nhất = `@dataclass` trong `document_service.py`
  (`chunk_id`, `section`, `content`, `char_count`). schemas.py chỉ map sang `ChunkPreview`.
- **Vector store (B3)**: 1 collection chung (`settings.chroma_collection_name` = "cv_chunks") cho
  mọi CV; cô lập bằng metadata `cv_id` + `where={"cv_id": ...}`. Id record = `f"{cv_id}::{chunk_id}"`.
  Metadata giữ: cv_id, section, chunk_id, char_count. `delete_cv` xoá theo metadata.
- **Embedding tự sinh** bằng Gemini rồi đưa vào Chroma (không để Chroma tự embed).
  Document → `RETRIEVAL_DOCUMENT`, query → `RETRIEVAL_QUERY`.
- **Schemas 3 tầng**: internal (dataclass) / API (Pydantic alias camelCase) / LLM (Pydantic
  snake_case cho `response_schema`). LLM chỉ sinh nội dung; backend gắn metadata (cv_id,
  analyzed_at) qua `LLMAnalysis.to_response()`.
- **Exception**: `AppException(message, status_code, error_code)` base; `DocumentProcessingError`
  422, `CVNotFoundError` 404, `LLMResponseError` 502; main.py bắt bằng 1 handler chung → `ErrorResponse`.
- **Analysis**: TOP_K=10, 1 query toàn văn JD, cắt `MAX_QUERY_CHARS=8000` trước khi embed
  (prompt LLM vẫn dùng toàn văn); `generate_structured(response_schema=LLMAnalysis, temperature=0.0)`;
  grounding + rubric + luật chống skill-inflation trong SYSTEM_INSTRUCTION; **verdict do BACKEND
  suy từ overall_score qua `MatchVerdict.from_score()` — LLM KHÔNG chọn verdict** (quyết định A+B
  sau khi đo tay thấy overall rung 90/75/85 ở temp 0.2); **[A+B v2] LLM trả thêm `same_field: bool`,
  backend áp floor cùng-ngành trong `to_response` (`same_field and overall < 30 → 32`) TRƯỚC khi
  suy verdict** — luật floor viết trong prompt đã được eval chứng minh là bị model bỏ qua;
  route là `def` thường
  (KHÔNG `async` — mọi I/O đều blocking sync, để FastAPI chạy threadpool).
- **JD**: chỉ nhận text dán vào (không file). **Upload**: xử lý sync.
- Hằng số cấu hình tập trung ở `config.py` + `.env`; riêng TOP_K, MAX_QUERY_CHARS là hằng nghiệp vụ
  đặt tại `analysis.py`.

## Trạng thái

**✅ Backend hoàn chỉnh, test tay pass hết**: config, main (handler + CORS + lifespan), 4 services,
schemas, exceptions, route cv (POST /cv/upload), route analysis (POST /analysis), health. Chi tiết
xem README mục 10.

**✅ pytest hoàn tất**: 52 test xanh ~5s, coverage 91% (chi tiết README mục 9).

**✅ Eval harness + 3 vòng cải thiện prompt hoàn tất — 20/20 case, verdict 20/20** (thư mục
`eval/`; hành trình 4 lượt đo + bài học: README mục 9, PROGRESS.md). Trong quá trình này đã
2 lần chuyển logic từ prompt về code (verdict `from_score`, floor `same_field`) và tiêm ngày
hiện tại vào prompt. Dừng tinh chỉnh prompt tại đây — tránh overfit vào 20 case.

**✅ Frontend hoàn chỉnh (5 bước, kiểm chứng sống qua browser)** — DỰ ÁN CHẠY ĐẦU-CUỐI:
upload CV → dán JD → báo cáo đầy đủ (verdict, điểm 4 trục, evidence, gợi ý + link học).
Backlog tùy chọn: multi-query, BackgroundTasks, gợi ý ngành nghề, test health/PDF/live,
sinh types.ts từ OpenAPI.

---

## KẾ HOẠCH TEST ĐÃ CHỐT (✅ ĐÃ HOÀN THÀNH — giữ làm tài liệu tham chiếu)

Đã bàn trade-off kỹ trong phiên trước. 4 quyết định:

1. **Mock ở tầng nào**: mặc định mock **hàm service của mình** (`generate_structured`,
   `embed_text`...). RIÊNG `test_llm_service.py` mock ở tầng SDK (`genai.Client`) để test được
   fallback parse + raise `LLMResponseError`.
   ⚠️ Patch tại **nơi tên được dùng**: nếu route viết `from app.services.llm_service import
   generate_structured` thì phải patch `app.api.routes.analysis.generate_structured` — đọc kiểu
   import trong file thật trước khi viết mock.
2. **ChromaDB**: dùng **Chroma thật** persist vào `tmp_path` của pytest. KHÔNG fake, KHÔNG đụng
   `data/chroma` thật. Kiểm tra `PersistentClient` tạo ở module level hay trong hàm để chọn cách
   cô lập persist dir cho đúng (module level → monkeypatch settings sau import là VÔ TÁC DỤNG).
3. **Embedding trong test**: fake tất định bag-of-words hashing, 3072 chiều, đã viết sẵn ở
   `tests/fakes.py` (dùng `hashlib.md5`, KHÔNG dùng `hash()` built-in — hash randomization).
4. **Test gọi Gemini thật**: chỉ 1-2 smoke test, marker `@pytest.mark.live`, mặc định bị loại
   (`addopts = -m "not live"` trong `pytest.ini`). Nguyên tắc: mock cái không tất định / tốn
   tiền / cần mạng; dùng thật cái tất định chạy local.

Nguyên tắc phân loại: **test kiểm tra "dây nối"; eval kiểm tra "chất lượng"** — không trộn.

### Ma trận test

| File | Mock | Case chính |
|---|---|---|
| `test_document_service.py` | không | ≥2 heading → section-based; không heading → fixed-size; section dài → sub-chunk + overlap; clean_text nối từ ngắt dòng; .docx → DocumentProcessingError; char_count đúng |
| `test_vector_service.py` | fake embedder + Chroma tmp_path | cô lập B3 (2 CV trùng chunk_id); query đúng cv_id; giữ section; delete_cv không lây; n_results > số chunk không nổ |
| `test_llm_service.py` | mock SDK | parsed OK → trả thẳng; parsed=None + text hợp lệ → fallback OK; text rác → LLMResponseError |
| `test_schemas.py` | không | camelCase alias; score ngoài range → ValidationError; to_response gắn metadata; enum ra string |
| `test_route_cv.py` | fake embedder + Chroma tmp | upload OK 200; đuôi sai 422; rỗng 422; >5MB 422 (đều ra ErrorResponse) |
| `test_route_analysis.py` | fake embedder + fake generate_structured | happy 200 camelCase; cv_id sai 404; LLM lỗi → 502 không rò stacktrace |

### Đã có sẵn (không viết lại)

- `pytest.ini` (pythonpath=., strict-markers, addopts `-q --strict-markers -m "not live"`, marker `live`)
- `requirements-dev.txt` (pytest, pytest-cov, httpx)
- `tests/fakes.py` (fake_embed / fake_embed_batch, FAKE_DIM=3072)

### Thứ tự thực hiện (mỗi bước dừng chờ duyệt)

1. Đọc thật: `vector_service.py`, `analysis.py`, `cv.py`, `schemas.py`, `config.py`,
   `llm_service.py`, `embedding_service.py`, `document_service.py`, `main.py`.
   Báo lại: client Chroma tạo ở đâu, kiểu import của các route → chốt chiến lược fixture/patch.
2. Viết `tests/conftest.py` + giải thích từng fixture → chờ duyệt.
3. Viết từng file test theo ma trận (mỗi file một lượt), chạy `pytest` xanh rồi mới sang file kế.
4. Xong hết: chạy `pytest --cov=app`, báo coverage; cập nhật README mục 9 + 10; đề xuất danh sách
   file test tạm ở root có thể xoá (chờ duyệt trước khi xoá).

---

## Bẫy đã gặp (tránh lặp lại)

- ChromaDB telemetry posthog gây log nhiễu → ghim `posthog<6.0.0` + tắt logger
  `chromadb.telemetry.product.posthog`.
- Config thiếu biến mà service gọi → nổ NGAY LÚC IMPORT. Thêm field vào `config.py` TRƯỚC,
  smoke test `python -c "import app.main"` sau mỗi bước.
- `gemini-embedding-001` giới hạn ~2048 token → query dài phải cắt trước khi embed.
- Enum dump ra `<Enum.X>` → dùng `(str, Enum)` + `model_dump(mode="json")`.
- `n_results` > số chunk → Chroma chỉ warning, vô hại.

## Quy tắc an toàn

- KHÔNG commit `.env`. KHÔNG in API key ra log/output.
- KHÔNG xoá file khi chưa được duyệt (kể cả file test tạm).
- KHÔNG chạy test có marker `live` trừ khi người dùng yêu cầu rõ.
- KHÔNG đụng `data/chroma` và `data/uploads` thật trong test.
