# Job Assistant AI

AI phân tích CV và Job Description (JD), chấm điểm mức độ phù hợp, gợi ý cải thiện CV.

Đây là **living document** — nguồn sự thật (source of truth) cho toàn bộ dự án. Mục tiêu: khi cần
thay đổi bất kỳ thứ gì, đọc file này là biết *đổi ở đâu, đổi cái gì kéo theo cái gì*. Mỗi khi thêm
tính năng hoặc đổi quyết định thiết kế, cập nhật lại các mục liên quan bên dưới.

---

## Mục lục

1. [Tổng quan & luồng dữ liệu](#1-tổng-quan--luồng-dữ-liệu)
2. [Tech stack](#2-tech-stack)
3. [Cấu trúc thư mục & bản đồ "đổi ở đâu"](#3-cấu-trúc-thư-mục--bản-đồ-đổi-ở-đâu)
4. [Các quyết định thiết kế đã chốt](#4-các-quyết-định-thiết-kế-đã-chốt)
5. [🎓 LLM Engineering — concept nền tảng](#5--llm-engineering--concept-nền-tảng)
6. [Chi tiết từng module](#6-chi-tiết-từng-module)
7. [Data model (schemas) — 3 tầng](#7-data-model-schemas--3-tầng)
8. [Cấu hình & môi trường](#8-cấu-hình--môi-trường)
9. [Chạy & test](#9-chạy--test)
10. [Trạng thái tiến độ](#10-trạng-thái-tiến-độ)
11. [Bẫy đã gặp & cách xử lý](#11-bẫy-đã-gặp--cách-xử-lý)
12. [Câu hỏi phỏng vấn tự kiểm tra](#12-câu-hỏi-phỏng-vấn-tự-kiểm-tra)

---

## 1. Tổng quan & luồng dữ liệu

Hệ thống gồm 2 luồng chính:

**Luồng A — Upload & Index CV** (chạy 1 lần khi user nộp CV):

```
File CV (PDF/TXT)
  → document_service: extract text → clean_text → chunk_cv_text  (list[DocumentChunk])
  → embedding_service: mỗi chunk → vector 3072 chiều (task_type=RETRIEVAL_DOCUMENT)
  → vector_service: lưu (vector + text + metadata) vào ChromaDB, gắn cv_id
  → trả CVUploadResponse (cv_id, số chunk, sections, preview)
```

**Luồng B — Analyze CV vs JD** (chạy mỗi lần chấm điểm):

```
AnalysisRequest (cv_id + JD text)
  → embedding_service: embed JD (task_type=RETRIEVAL_QUERY)
  → vector_service: query top-k chunk CV gần nghĩa JD nhất (cosine)
  → llm_service.generate_json: đưa (JD + chunk CV liên quan) + response_schema=LLMAnalysis
  → LLMAnalysis.to_response(): ráp thêm cv_id, jd_title, analyzed_at
  → trả AnalysisResponse (verdict, score, matched/missing skills, suggestions)
```

> Điểm cốt lõi: đây là **RAG** (Retrieval-Augmented Generation). Ta không nhét cả CV vào prompt,
> mà chỉ lấy các đoạn CV *liên quan nhất* tới JD rồi mới hỏi LLM. Xem [mục 5](#5--llm-engineering--concept-nền-tảng).

---

## 2. Tech stack

| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| Ngôn ngữ | Python 3.12 | KHÔNG dùng 3.14 (thiếu wheel cho vài lib) |
| Web framework | FastAPI | async, tự sinh OpenAPI docs |
| LLM SDK | `google-genai` (SDK mới) | `from google import genai`, dùng **client pattern**, KHÔNG phải `google-generativeai` cũ |
| Model sinh text | `gemini-2.5-flash` | nhanh, rẻ, đủ cho chấm điểm |
| Model embedding | `gemini-embedding-001` | vector **3072 chiều**, mỗi request 1 text, có `task_type` |
| Vector DB | ChromaDB local | `PersistentClient`, cosine similarity |
| Validation | Pydantic v2 + pydantic-settings | type-safe config + request/response |
| PDF | `pypdf` | KHÔNG dùng `PyPDF2` (deprecated, đã merge vào pypdf) |
| Frontend | ReactJS | chưa làm |
| OS dev | Windows, venv, code tại `D:\job_assistant_ai` | |

Phiên bản đã cài (giữ ổn định): `google-genai 2.8.0`, `chromadb 0.5.23`, `posthog<6.0.0` (xem [mục 11](#11-bẫy-đã-gặp--cách-xử-lý)).

---

## 3. Cấu trúc thư mục & bản đồ "đổi ở đâu"

```
app/
  config.py            # đọc .env type-safe (pydantic-settings)
  main.py              # khởi tạo FastAPI, lifespan, CORS, global exception handler
  api/routes/
    health.py          # liveness + readiness (check ChromaDB)                              
    cv.py              # upload + index CV; GET / danh sách; DELETE /{cv_id}
    analysis.py        # RAG: retrieve top-k → prompt → chấm điểm; /direct = upload+phân tích 1 request
  services/
    llm_service.py         # gọi Gemini sinh text / JSON
    embedding_service.py   # sinh vector embedding
    vector_service.py      # CRUD ChromaDB
    document_service.py    # đọc file → clean → chunk
  models/schemas.py    # toàn bộ Pydantic model (3 tầng)
  core/exceptions.py   # AppException base + custom exceptions
data/
  uploads/             # file CV người dùng upload
  chroma/              # ChromaDB persist ở đây
frontend/              # ReactJS                                   [CHƯA LÀM]
tests/                 # pytest thật                               [CHƯA LÀM]
.env / .env.example / .gitignore / requirements.txt
```

### Bản đồ "muốn đổi X thì sửa file nào"

| Muốn thay đổi... | Sửa ở... |
|---|---|
| Model Gemini, API key, chunk_size, tên collection Chroma, CORS origin | `app/config.py` + `.env` |
| Cách đọc PDF/TXT, logic chunking, nhận diện section | `app/services/document_service.py` |
| Cách sinh vector, phân biệt query/document | `app/services/embedding_service.py` |
| Lưu/truy vấn vector, tên collection, filter theo cv_id | `app/services/vector_service.py` |
| Prompt chấm điểm, rubric, TOP_K, system instruction | `app/api/routes/analysis.py` |
| Cách gọi Gemini, structured output (`response_schema`) | `app/services/llm_service.py` |
| Hình dạng dữ liệu request/response, ràng buộc validation | `app/models/schemas.py` |
| Thêm loại lỗi mới, mã lỗi, status code | `app/core/exceptions.py` |
| Cách trả JSON lỗi thống nhất | exception handler trong `app/main.py` |
| Thêm endpoint mới | tạo file trong `app/api/routes/` + đăng ký router ở `main.py` |

> **Quy tắc phụ thuộc**: `routes` gọi `services`, `services` gọi lẫn nhau qua interface rõ ràng,
> `schemas` được cả hai dùng nhưng **không phụ thuộc ngược** vào chúng. Đổi service không được
> làm vỡ schema; đổi schema (thêm field optional) không làm vỡ service.

---

## 4. Các quyết định thiết kế đã chốt

Những mục này **đã cân nhắc trade-off và chốt** — chỉ đổi khi có lý do mới rõ ràng.

### 4.1 PDF: dùng `pypdf`
`PyPDF2` deprecated, đã merge vào `pypdf`. Không quay lại PyPDF2.

### 4.2 Chunking: hybrid section-based → fixed-size fallback
- Ưu tiên **section-based**: regex nhận diện heading CV (summary, experience, education, skills,
  projects, certifications), hỗ trợ **cả tiếng Anh + tiếng Việt**.
- Cần nhận diện **≥2 section** mới coi là "CV có cấu trúc".
- Section dài quá `chunk_size` → **sub-chunk** tiếp theo đoạn văn → câu, có **overlap**.
- Không nhận diện được section nào → **fallback fixed-size** trên toàn bộ text.
- `chunk_size` mặc định **600 ký tự** (xấp xỉ token, KHÔNG phải token thật của Gemini).

**Vì sao hybrid?** Xem [mục 5.3](#53-chunking--vì-sao-quan-trọng).

### 4.3 KHÔNG dùng LangChain
Tự viết chunking để hiểu sâu cơ chế → trả phỏng vấn thuyết phục hơn là "tôi gọi
`RecursiveCharacterTextSplitter()`". Có thể revisit nếu cần scale/nhiều loader.

**Trade-off:**

| | Tự viết (đang chọn) | LangChain |
|---|---|---|
| Hiểu cơ chế | Sâu, kiểm soát hoàn toàn | Bị trừu tượng hoá, dễ thành hộp đen |
| Tốc độ dựng | Chậm hơn | Nhanh (có sẵn splitter/loader) |
| Phụ thuộc | Ít, nhẹ | Nặng, hay breaking change |
| Phù hợp mục tiêu học | ✅ | ❌ (giai đoạn này) |

### 4.4 Exception pattern: `AppException` base class
`AppException(message, status_code, error_code)` trong `core/exceptions.py`. Mọi custom exception
(vd `DocumentProcessingError`, status 422) kế thừa từ đó → `main.py` bắt bằng **một** handler
chung, trả JSON `ErrorResponse` thống nhất.

### 4.5 Embedding: tự đưa vector vào Chroma
Không để ChromaDB tự sinh embedding — ta sinh bằng Gemini rồi đưa vector vào trực tiếp. Lý do:
kiểm soát model, `task_type`, và đảm bảo cùng model cho cả index lẫn query.

### 4.6 Schemas: 3 tầng (internal / API / LLM)
Xem [mục 7](#7-data-model-schemas--3-tầng). Tách để mỗi tầng đổi độc lập.

### 4.7 JD: chỉ nhận text dán vào (không nhận file)
Đơn giản hoá luồng. Nếu sau cần upload JD dạng PDF: thêm route tái dùng `DocumentService`, và
quyết định có embed JD vào Chroma không (RAG hai chiều) hay chỉ giữ text tạm.

### 4.7b Resources cho suggestions: LLM KHÔNG BAO GIỜ sinh URL
Mỗi suggestion có `resources: list[ResourceLink]` (link học tập). URL do **backend sở hữu**:
catalog ~30 skill biên soạn tay trong `resource_service.py` (docs chính thức, roadmap.sh,
nguồn miễn phí, ưu tiên bản tiếng Việt) + fallback link tìm kiếm TỰ RÁP cho skill lạ —
không bao giờ trả link rỗng, không bao giờ chết link. Match catalog theo chứa-chuỗi normalize,
có luật lọc key chuỗi-con ("PostgreSQL" không kéo nhầm link "sql"; "GitHub Actions" không kéo
nhầm "git"). Vì sao không để LLM sinh link: bịa URL là bệnh kinh điển và URL không grounding
được như evidence — đây là phiên bản thứ 3 của triết lý "LLM sinh dữ kiện, backend quyết phần
tất định" (sau verdict và floor).

### 4.8 Vector store: 1 collection chung + filter `cv_id` (quyết định B3)
- MỘT collection (`settings.chroma_collection_name` = "cv_chunks") cho MỌI CV.
- Cô lập bằng metadata `cv_id` + `where={"cv_id": ...}` khi query.
- Id record = `f"{cv_id}::{chunk.chunk_id}"` (chunk_id như "experience_0" lặp giữa các CV).
- Metadata giữ: `cv_id`, `section`, `chunk_id`, `char_count` — vì analysis cần `section`.
- `delete_cv(cv_id)` xóa theo metadata, không đụng CV khác.

**Vì sao không tách collection mỗi CV?** Collection trong Chroma đắt hơn record (mỗi cái một
HNSW index); hàng nghìn CV = hàng nghìn index. Filter metadata là pattern multi-tenant chuẩn.

### 4.9 Analysis (POST /analysis): các lựa chọn đã chốt
- **TOP_K = 10, 1 query duy nhất bằng toàn văn JD** (title + content). CV thường chỉ có ~8-20
  chunk nên k=10 phủ gần hết; multi-query theo từng khía cạnh JD để dành khi thấy retrieval sót
  (trade-off: n lần embed + code merge/dedupe, đổi lấy coverage đều hơn cho education/certs).
- **Cắt query ở 8000 ký tự trước khi embed** (`gemini-embedding-001` giới hạn ~2048 token);
  prompt cho LLM vẫn dùng toàn văn JD.
- **Grounding trong prompt**: LLM chỉ được dùng trích đoạn được cấp; skill khớp phải kèm
  `evidence` nguyên văn; không suy diễn từ chức danh. Rubric 0-100 từng trục.
- **[A+B — chống LLM-as-judge variance]** Đo tay cùng CV+JD chạy 3 lần ở temperature 0.2:
  overall ra 90/75/85 (±15, verdict nhảy band). Xử lý: **temperature 0.0** + **LLM KHÔNG chọn
  verdict nữa** — backend tự suy từ overall_score qua `MatchVerdict.from_score()` (≥85 strong /
  ≥70 good / ≥50 partial / ≥30 weak / còn lại not_a_match; 10 test biên).
  **Đo sau khi fix: 79/81/81 (±1, 2/3 lần trùng hệt) → ĐẠT**, không cần self-consistency
  (median 3 lần gọi — để dành nếu sau này đổi model thấy rung lại).
- **[A+B v2 — từ vòng eval #1] Floor cùng-ngành áp ở BACKEND**: luật "cùng ngành non tay
  → ≥30" viết trong prompt bị model bỏ qua khi công thức trọng số cho điểm quá thấp
  (bj_vs_senior vẫn 17). Fix kiến trúc: LLM trả thêm dữ kiện rời rạc `same_field: bool`
  (chỉ xét lĩnh vực, không xét cấp bậc); `to_response` áp floor tất định
  (`same_field and overall < 30 → FLOOR_CUNG_NGANH = 32`, đặt 32 để không sát mép band)
  TRƯỚC khi suy verdict — client thấy overall đã floor, verdict nhất quán. 4 test biên.
  Kèm luật chống skill-inflation trong prompt (mức "cơ bản" không thỏa yêu cầu "thành thạo").
- **Route là `def` thường (không `async`)**: embed/Chroma/Gemini đều blocking sync → FastAPI
  tự chạy trong threadpool; bỏ vào `async def` sẽ chặn event loop.
- **Lỗi**: cv_id không có chunk → `CVNotFoundError` 404; output LLM không khớp schema →
  `LLMResponseError` 502.

---

## 5. 🎓 LLM Engineering — concept nền tảng

Phần này giải thích sâu các khái niệm cốt lõi. Đây là "phần học" — đọc kỹ để đi phỏng vấn.

### 5.1 Embedding — biến text thành vector

**Embedding** là ánh xạ một đoạn text → một vector số thực nhiều chiều (ở đây **3072 chiều**).
Ý tưởng: text *gần nghĩa nhau* → vector *gần nhau trong không gian*. "Python developer" và "lập
trình viên Python" nằm sát nhau; "đầu bếp" nằm xa.

- **Chiều (dimension)**: `gemini-embedding-001` cho vector 3072 số. Mỗi số là một "toạ độ" trong
  không gian ngữ nghĩa. Ta không đọc hiểu từng số — chỉ dùng để đo *khoảng cách* giữa các text.
- **task_type** (rất quan trọng, dễ bỏ sót):
  - `RETRIEVAL_DOCUMENT`: dùng khi embed **tài liệu để lưu trữ/index** (các chunk CV).
  - `RETRIEVAL_QUERY`: dùng khi embed **câu truy vấn để đi tìm** (JD).
  - Cùng một text nhưng embed với 2 task_type khác nhau → 2 vector khác nhau, được Gemini tối ưu
    cho vai trò tương ứng. Dùng sai task_type → chất lượng retrieval giảm.

**Vì sao cần embedding?** Máy không "hiểu" chữ. Muốn tìm đoạn CV *liên quan* JD, ta không so khớp
từ khoá (fragile, "JS" ≠ "JavaScript") mà so khớp **ý nghĩa** qua khoảng cách vector.

### 5.2 Vector DB & cosine similarity

**Vector DB** (ChromaDB) lưu các vector + text gốc + metadata, và cho phép truy vấn *"cho tôi k
vector gần nhất với vector này"* cực nhanh.

- **Cosine similarity**: đo góc giữa 2 vector (không quan tâm độ dài). Giá trị càng gần 1 → càng
  giống nghĩa; gần 0 → không liên quan; âm → ngược nghĩa. Ta chọn cosine (không phải Euclidean) vì
  với embedding, *hướng* của vector mang nghĩa, độ lớn thì không.
- **Metadata + filter**: mỗi chunk lưu kèm `cv_id`, `section_type`... Khi query CV nào, ta filter
  `where={"cv_id": ...}` để chỉ tìm trong đúng CV đó, không lẫn CV người khác.
- **PersistentClient**: lưu xuống đĩa (`data/chroma/`) để không mất khi restart. Khác với client
  in-memory (mất khi tắt).

### 5.3 Chunking — vì sao quan trọng

**Chunking** = cắt tài liệu dài thành các mẩu nhỏ trước khi embed. Vì sao không embed cả CV làm 1
vector?

1. **Giới hạn ngữ cảnh**: model embedding có giới hạn độ dài đầu vào.
2. **Độ chính xác retrieval**: 1 vector cho cả CV sẽ "trung bình hoá" mọi thứ → mờ nghĩa. Cắt nhỏ
   → mỗi vector đại diện 1 ý cụ thể → tìm được đúng đoạn liên quan JD.
3. **Đưa đúng đoạn vào prompt**: chỉ nhét chunk liên quan vào LLM → prompt gọn, rẻ token, model
   tập trung.

**Trade-off kích thước chunk:**

| Chunk nhỏ | Chunk lớn |
|---|---|
| Retrieval chính xác, nhắm trúng ý | Giữ được ngữ cảnh dài |
| Dễ mất ngữ cảnh xung quanh | Retrieval mờ, kéo theo nhiễu |
| Nhiều vector hơn (tốn lưu trữ) | Ít vector |

→ **Overlap** (chồng lấn giữa 2 chunk kề nhau) để một ý bị cắt ngang không mất ngữ cảnh ở ranh giới.

**Vì sao hybrid section-based?** CV có cấu trúc tự nhiên (các mục). Cắt theo section giữ nguyên
ngữ nghĩa "khối kinh nghiệm", "khối kỹ năng" — tốt hơn cắt mù theo số ký tự cắt ngang giữa câu.
Chỉ khi CV không có cấu trúc rõ (nhận diện <2 section) mới fallback fixed-size.

### 5.4 RAG — Retrieval-Augmented Generation

**RAG** = trước khi hỏi LLM, đi *truy xuất* (retrieve) thông tin liên quan từ nguồn ngoài (vector
DB), rồi *đưa kèm* vào prompt (augment) để LLM *sinh* (generate) câu trả lời có căn cứ.

Trong dự án: thay vì hỏi "chấm điểm CV này với JD này" kèm toàn bộ CV, ta:
1. Embed JD → query vector DB → lấy top-k chunk CV liên quan nhất.
2. Đưa (JD + chỉ những chunk đó) vào prompt.
3. LLM chấm điểm dựa trên bằng chứng cụ thể được đưa vào.

**Lợi ích:** prompt ngắn (rẻ + nhanh), giảm "ảo giác" (LLM bám vào text thật của CV), và scale
được với CV dài. **Đánh đổi:** chất lượng phụ thuộc chất lượng retrieval — retrieve trượt thì LLM
cũng trả sai. Đây là lý do chunking + embedding + task_type phải làm chuẩn.

### 5.5 Prompt engineering & Structured Output

- **`response_mime_type="application/json"`** (đang có trong `generate_json`): ép Gemini trả JSON
  thay vì văn xuôi. Nhưng *hình dạng* JSON không được đảm bảo — model tự do đặt key.
- **`response_schema`** (bước nâng cấp sắp làm): đưa hẳn một **Pydantic model** (`LLMAnalysis`)
  làm schema. Gemini bị **buộc** trả đúng cấu trúc + đúng kiểu + enum đúng tập giá trị. Kết quả:
  luôn `parse` được, không cần regex dọn dẹp, ít lỗi.

| | `response_mime_type=json` | `response_schema=Pydantic` |
|---|---|---|
| Đảm bảo là JSON | ✅ | ✅ |
| Đảm bảo đúng cấu trúc/kiểu | ❌ (model tự do) | ✅ |
| Enum constrain giá trị | ❌ | ✅ |
| Cần validate/parse thủ công | Nhiều | Ít |

→ Kế hoạch: chuyển logic chấm điểm sang `response_schema=LLMAnalysis`.

### 5.6 Vì sao LLM chỉ sinh nội dung, backend gắn metadata

`LLMAnalysis` (schema đưa Gemini) **không** chứa `cv_id`, `analyzed_at`. Nguyên tắc: chỉ để LLM
sinh thứ nó *suy luận được từ dữ liệu*. `cv_id` backend đã biết; `analyzed_at` là `datetime.now()`
— bắt LLM sinh chỉ tốn token và nó sẽ bịa (model không biết giờ thật). Method
`LLMAnalysis.to_response()` là chỗ ráp: **LLM sinh phân tích + backend gắn metadata**.

### 5.7 Testing hệ thống LLM — test ≠ eval

- **Test kiểm "dây nối", eval kiểm "chất lượng"** — không trộn. Test: tất định, fake mọi thứ
  tốn tiền/cần mạng, chạy miễn phí sau mỗi lần sửa code (52 test / ~5s). Eval: model thật,
  dataset có nhãn, tốn tiền CÓ CHỦ ĐÍCH, chạy khi đổi prompt/model.
- **Mock theo TIÊU CHÍ, không theo thói quen**: mock cái *không tất định / tốn tiền / cần mạng*
  (Gemini); dùng thật cái *tất định chạy local* (Chroma — hành vi filter/id/delete chính là thứ
  đang test, fake nó là "test tự nói chuyện với chính mình").
- **Mock dependency của đơn vị test, không mock chính nó**: route test mock `generate_structured`;
  `test_llm_service` test chính hàm đó nên phải mock tầng dưới (stub `client` SDK).
- **Fake embedding tất định**: bag-of-words + `hashlib.md5` (KHÔNG dùng `hash()` — bị randomize
  mỗi process), bảo toàn quan hệ "giống nhau hơn thì gần nhau hơn" — đủ cho test retrieval,
  không đo được chất lượng ngữ nghĩa (việc của eval).
- **Lưới an toàn autouse + poison object**: quên mock thì nổ ngay với thông điệp rõ, không âm thầm
  gọi API thật. **Side effect lúc import là kẻ thù test isolation** (PersistentClient tạo ở module
  level → phải set env TRƯỚC khi import app, trong conftest).
- **Test phải fail được**: tự hỏi "nếu cố tình phá code, test này có đỏ không?" (bài học test
  overlap với văn bản lặp). Test hợp đồng (≥2 chunk, có overlap) chứ không test cài đặt (đúng
  ranh giới ký tự X) — refactor không được làm đỏ test nếu hành vi cam kết còn nguyên.

### 5.8 LLM-as-judge — chấm điểm bằng LLM và bài toán variance

- LLM chấm thang 0-100 là hệ *sinh*, không phải hàm *tính*: đo tay 3 lần ra 90/75/85 (±15,
  verdict nhảy band). **Không bao giờ tin 1 lần chạy** — variance là chỉ số hạng nhất.
- Xử lý theo tầng: **tham số** (temperature 0.0 — greedy, nhưng vẫn còn nhiễu hạ tầng
  floating-point/batching, sàn ±1-2) → **kiến trúc** (logic tất định về code) → **thống kê**
  (self-consistency median N lần — chưa cần dùng).
- **Nguyên tắc rời rạc hóa**: LLM trả lời có/không, enum, đếm — ổn định hơn nhiều so với thang
  liên tục. Đã áp dụng 2 lần: verdict do backend suy từ overall (`MatchVerdict.from_score`),
  floor cùng-ngành do backend áp từ dữ kiện `same_field: bool` (luật floor viết trong prompt
  bị model bỏ qua khi xung đột với công thức trọng số — **hai mệnh lệnh xung đột trong prompt
  phải ghi rõ thứ tự ưu tiên, còn tốt nhất là đưa về code**).
- Rubric phải NEO điểm (định nghĩa từng band, công thức trọng số) — không thì điểm là "vibe".
- Ngữ nghĩa khó của skill matching: **"có nhưng dưới mức yêu cầu" là trạng thái thứ ba** mà
  schema bool ép về có/không — phải định nghĩa rõ trong prompt (tồn tại → bool; mức độ →
  evidence + trừ điểm), lệch về phía nào cũng vỡ một nhóm case.

### 5.9 Eval harness — đo chất lượng có kỷ luật

- Dataset nhãn theo triết lý **"chỉ ghi thứ chắc chắn"**: cửa sổ verdict 2 nấc, keyword
  must_matched/must_missing so fuzzy — eval quá nghiêm ở chỗ không quan trọng chết vì noise,
  quá lỏng ở chỗ quan trọng thì mù.
- **Grounding đo tự động được**: evidence phải là chuỗi con (fuzzy ≥0.8) của CV. Metric có
  SÀN NHIỄU ~10-20% do LLM nén/ghép trích dẫn thật — **nghi ngờ thước đo trước khi nghi ngờ
  model** (giả thuyết "dịch evidence" nghe rất thuyết phục và sai hoàn toàn khi soi raw).
- **Lưu raw response mỗi lượt eval**: dữ liệu đắt (tốn tiền/thời gian) thì lưu; phân tích rẻ thì
  làm lại bao nhiêu lần cũng được — toàn bộ điều tra grounding sau đó tốn 0 call API.
- **Sửa prompt không bao giờ miễn phí**: thêm 1 luật là xô cả trường trọng lực — case biên lật
  band, hành vi đổi ở chỗ không liên quan. Eval 20 case = regression suite cho prompt. Đổi ngữ
  nghĩa hệ thống thì NHÃN cũ cũng stale theo (label drift).
- Vòng lặp chuẩn: baseline → chẩn đoán bằng bằng chứng thô → sửa CÓ MỤC TIÊU → đo lại cùng
  thước — và biết điểm dừng để không overfit vào bộ case nhỏ.

### 5.10 Vận hành API LLM ngoài đời thật

- **429 có hai họ, hai vũ khí**: rate-limit theo phút (tự hồi phục → retry + backoff) vs quota
  theo ngày (retry vô ích → circuit breaker ngắt sớm + in sẵn lệnh chạy nốt). Free tier
  gemini-2.5-flash trần ~20-25 call/ngày; embedding có quota RIÊNG nên upload vẫn chạy khi
  LLM chết — nhìn lỗi phải phân loại trước khi xử lý.
- **LLM không có đồng hồ**: không biết "nay" trong "09/2024 - nay" là bao giờ → tính sai số năm
  kinh nghiệm. Tài liệu có mốc thời gian tương đối thì phải TIÊM ngày hiện tại vào prompt.
- **Hai giới hạn khác nhau dễ nhầm**: input limit của model embedding (~2048 token) ≠ context
  limit của LLM (hàng trăm nghìn token) — query dài phải cắt trước khi embed, prompt thì không.
- Batch job gọi API phải **sống sót từng phần**: 1 case hỏng không được giết cả lượt; tiến độ in
  console cho người-đang-chờ, báo cáo lưu file timestamp cho người-tuần-sau so sánh.

---

## 6. Chi tiết từng module

### `config.py`
Đọc `.env` type-safe bằng `pydantic-settings`. Chứa: API key Gemini, tên model text/embedding,
`chroma_persist_dir` + `chroma_collection_name`, `chunk_size`/`chunk_overlap`, `upload_dir`,
`cors_origins`. **Mọi hằng số cấu hình tập trung ở đây** — không hardcode rải rác trong service.
(Riêng `TOP_K` và `MAX_QUERY_CHARS` là hằng số nghiệp vụ của analysis, đặt tại `analysis.py`.)

### `main.py`
Khởi tạo FastAPI, `lifespan`, CORS. **Global exception handler**: bắt mọi `AppException` →
trả JSON `ErrorResponse` thống nhất (`model_dump(by_alias=True, mode="json")`). Đăng ký router
`cv` + `analysis`.

### `embedding_service.py`
- `embed_text(text, is_query)`: 1 text → 1 vector. `is_query=True` → `RETRIEVAL_QUERY`, ngược lại
  `RETRIEVAL_DOCUMENT`.
- `embed_batch(texts)`: nhiều text (lưu ý `gemini-embedding-001` mỗi request 1 text → batch là
  vòng lặp gọi tuần tự, cân nhắc rate limit).

### `llm_service.py`
- `generate(prompt, system_instruction, temperature)`: sinh text thô.
- `generate_json(prompt, system_instruction)`: JSON "hình dạng tự do" (`response_mime_type`).
- `generate_structured(prompt, response_schema, system_instruction, temperature)`: structured
  output chuẩn — truyền class Pydantic (vd `LLMAnalysis`) làm `response_schema`, Gemini bị ràng
  buộc lúc decode, SDK trả `response.parsed` là instance model. Có fallback tự
  `model_validate_json(response.text)`; thất bại → `LLMResponseError` 502.

### `vector_service.py`
ChromaDB `PersistentClient`, kiến trúc B3 (xem [4.8](#48-vector-store-1-collection-chung--filter-cv_id-quyết-định-b3)):
- `add_documents(cv_id, chunks: list[DocumentChunk], collection_name=None) -> int`
- `query(cv_id, query_text, n_results=5, collection_name=None) -> list[dict]`
  (dict: `text`, `section`, `chunk_id`, `distance`; filter `where={"cv_id": ...}`)
- `list_cvs(collection_name=None) -> list[dict]` (gom metadata theo cv_id: chunk_count, sections)
  / `has_cv(cv_id) -> bool` (get where + limit=1 — check tồn tại rẻ nhất).
- `delete_cv(cv_id)` (xóa theo metadata) / `delete_collection(name)`.
Đã xử lý bug telemetry posthog (xem [mục 11](#11-bẫy-đã-gặp--cách-xử-lý)).

### `document_service.py`
- `extract_text_from_pdf` (pypdf) / `extract_text_from_txt`.
- `clean_text`: NFKC normalize, nối từ bị ngắt dòng, gộp khoảng trắng thừa.
- `chunk_cv_text`: hybrid, gồm `_find_section_headings`, `_slice_sections`, `_split_fixed_size`.
- `DocumentService`: facade, `process_file(path) -> list[DocumentChunk]`.
- Raise `DocumentProcessingError` khi format không hỗ trợ.

### `core/exceptions.py`
`AppException` (base: message, status_code, error_code) + `DocumentProcessingError` (422)
+ `CVNotFoundError` (404) + `LLMResponseError` (502).

### `api/routes/health.py`
- `GET /health` — **liveness**: process còn sống không; không đụng dependency, luôn nhanh.
- `GET /health/ready` — **readiness**: Chroma là PersistentClient NHÚNG nên `heartbeat()`
  gần như vô nghĩa một mình; check thật = mở collection + `count()` (chạm persist dir trên
  đĩa). Lỗi hạ tầng bất kỳ → `HTTPException` 503 (monitoring chỉ cần status code, không cần
  body `ErrorResponse` như frontend).

### `api/routes/cv.py`
`POST /cv/upload`: validate đuôi (.pdf/.txt/.md) + dung lượng (5MB, đọc khối 1MB) + chặn rỗng
→ `cv_id = uuid4().hex` → lưu `data/uploads/{cv_id}_{filename}` → `process_file` →
`add_documents(cv_id, chunks)` → `CVUploadResponse` (cv_id, total_chunks, sections_detected,
preview chunks). Xử lý **sync** — client chờ parse+embed xong.
**Ruột nằm ở `ingest_cv(file) -> IngestedCV`** (validate → lưu → chunk → index; các bước blocking
bọc `run_in_threadpool` vì hàm là async) — dùng chung với `/analysis/direct`, route chỉ là cửa mỏng.

Thêm 2 route quản lý vòng đời CV:
- `GET /cv` → `list[CVListItem]` (cvId, filename, totalChunks, sections). Nguồn sự thật:
  metadata Chroma; filename chỉ tra thêm từ `uploads/` theo prefix, có thể null.
- `DELETE /cv/{cv_id}` → 204: xóa chunk trong Chroma (`delete_cv`) + file gốc; 404 `CV_NOT_FOUND`
  nếu cv_id không có trong index (check bằng `has_cv`, không xóa mù).

### `api/routes/analysis.py`
`POST /analysis` — luồng RAG hoàn chỉnh, nhận `AnalysisRequest` (cv_id + jd):
1. **Retrieve**: embed JD (cắt 8000 ký tự) → `vector_service.query(cv_id, ..., n_results=10)`.
   Rỗng → `CVNotFoundError` 404.
2. **Augment**: `_build_prompt` ráp JD + trích đoạn CV (kèm nhãn `section`/`chunk_id`).
3. **Generate**: `generate_structured(response_schema=LLMAnalysis, temperature=0.0)` với
   `SYSTEM_INSTRUCTION` chứa luật grounding + rubric (LLM KHÔNG chọn verdict).
4. **Assemble**: `LLMAnalysis.to_response(cv_id, jd_title)` gắn metadata backend + tự suy
   verdict từ overall_score (`MatchVerdict.from_score` — quyết định A+B, xem 4.9).

Lõi 4 bước nằm ở `_run_analysis(cv_id, jd)` — dùng chung cho 2 route:
- `POST /analysis` (JSON, cv_id đã upload trước) — 1 CV chạy nhiều JD, không re-embed.
- `POST /analysis/direct` (multipart: `file` + `jdTitle` + `jdContent`) — upload + phân tích
  MỘT request; JD là form field nên dán nhiều dòng không cần escape `\n`. Trade-off: mỗi lần
  gọi re-embed cả CV. Route async (await đọc file) nên `_run_analysis` được bọc `run_in_threadpool`.

---

## 7. Data model (schemas) — 3 tầng

Ba tầng model **tách rời có chủ đích** để mỗi tầng đổi độc lập:

| Tầng | Model tiêu biểu | Naming | Vai trò |
|---|---|---|---|
| **Internal** | `DocumentChunk` | snake_case | Dữ liệu giữa các service, KHÔNG lộ ra client |
| **API request** | `JDInput`, `AnalysisRequest` | camelCase alias | Client gửi lên |
| **API response** | `CVUploadResponse`, `AnalysisResponse` | camelCase alias | Hợp đồng với frontend |
| **LLM output** | `LLMAnalysis` (+ `LLMSkillMatch`, `LLMSuggestion`) | snake_case | Schema ép Gemini tuân theo |
| **Error** | `ErrorResponse` | camelCase alias | JSON lỗi thống nhất |

**Enums** (constrain giá trị, đặc biệt để giới hạn LLM): `MatchVerdict`, `Priority`.
(`SectionType`/`ChunkStrategy` đã bỏ — không dùng; loại section do `SectionName` Literal
trong `document_service.py` làm nguồn sự thật, tầng API để `section: str`.)

**Điểm cần nhớ khi đổi schema:**
- Thêm field **optional** vào response → an toàn, không vỡ frontend cũ.
- Đổi tên / bỏ field / đổi kiểu → **breaking change**, phải sửa cả frontend.
- Enum dùng `(str, Enum)` → serialize ra string sạch, so sánh trực tiếp với string được.
- `model_dump()` thường giữ enum *object*; muốn ra string dùng `model_dump(mode="json")`. FastAPI
  qua `response_model` tự xử lý đúng.
- `Field(ge=0, le=100)` cho điểm → LLM trả điểm rác (150, -20) sẽ nổ `ValidationError` ngay lúc
  parse, không chảy xuống UI.
- `LLMAnalysis.to_response(cv_id, jd_title)` là chỗ ráp LLM output → API response (gắn metadata).

---

## 8. Cấu hình & môi trường

- Python **3.12** trong venv. KHÔNG 3.14 (thiếu wheel).
- `.env` (không commit) chứa `GEMINI_API_KEY` và override cấu hình. `.env.example` là mẫu (commit).
- `requirements.txt`: fastapi, google-genai, chromadb, pypdf, pydantic-settings, python-multipart,
  `posthog<6.0.0` (ghim).
- Đường dẫn dev: `D:\job_assistant_ai`.

---

## 9. Chạy & test

```bash
# tạo & kích hoạt venv (Windows)
python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

# chạy API
uvicorn app.main:app --reload
# docs tự sinh: http://localhost:8000/docs
```

**Test tự động (pytest)** — 52 test trong `tests/`, chạy hết ~5 giây, không cần mạng/API key:

```bash
venv\Scripts\python -m pytest              # mặc định LOẠI marker "live" (không gọi Gemini)
venv\Scripts\python -m pytest --cov=app    # kèm coverage (hiện ~91%)
```

- **Hạ tầng**: `pytest.ini` (`testpaths=tests` — không gom file test tạm ở root vốn gọi API thật;
  `-m "not live"`), `requirements-dev.txt` (cài thêm: `pip install -r requirements-dev.txt`),
  `tests/conftest.py` (env cô lập TRƯỚC import → không đụng `data/` thật; fake embedding autouse;
  guard poison-object chặn LLM thật; collection Chroma riêng mỗi test), `tests/fakes.py`
  (embedding bag-of-words + md5, tất định, bảo toàn quan hệ tương đồng).
- **Ma trận 6 file**: document (8) / vector (5) / llm_service (5) / schemas (7) / route_cv (4) /
  route_analysis (3).
- **Chỗ chưa phủ (coverage 91%)**: thân hàm gọi Gemini thật (cố ý fake trong test — dành cho
  smoke test `live`), đường đọc PDF trong document_service (cần fixture PDF nhị phân), route
  health (mới test tay), `generate`/`generate_json` (chưa route nào dùng).

**Eval chất lượng (`eval/run_eval.py`)** — Gemini THẬT trên dataset có nhãn (khác pytest:
tốn tiền CÓ CHỦ ĐÍCH, chạy khi đổi prompt/model):

```bash
venv\Scripts\python eval\run_eval.py --runs 1
```

- Dataset `eval/dataset/`: 12 CV (4 trục đa dạng) + 6 JD + `cases.json` 20 cặp nhãn tay
  (verdict window / must_matched / must_missing). Metric tự động: grounding (tách mảnh,
  fuzzy 0.8 — có sàn nhiễu ~10%), section detection, skill labels, verdict, variance.
  Báo cáo + raw JSON lưu `eval/reports/` theo timestamp để so giữa các version prompt.
- Chống lỗi API: retry 429/503 (phân loại theo MESSAGE — exception đổi type khi xuyên tầng),
  circuit breaker khi quota ngày cạn (free tier ~20-25 call flash/ngày), `--only` chạy bù.
- **Hành trình 4 lượt đo — vòng lặp đo → chẩn đoán → sửa → đo lại:**

| Lượt | Thay đổi | Case pass | Verdict đúng | Bài học chính |
|---|---|---|---|---|
| Baseline | prompt gốc | 18/20 | 18/20 | Quá gắt với ứng viên cùng ngành non tay; "grounding 51%" hóa ra là nhiễu metric (soi raw mới biết) |
| Vòng #1 | luật floor + cấm chữ JD (trong prompt) | 17/20 | 18/20 | Luật floor trong prompt bị công thức trọng số đè; sửa prompt không miễn phí — case biên lật |
| Vòng #2 | **A+B v2**: `same_field` + floor backend; luật chống inflation | 14/20 | 19/20 | Floor ở code chạy hoàn hảo; luật inflation quá tay ("có nhưng yếu" ≠ "không có"); phát hiện model không biết ngày hiện tại |
| Vòng #3 | luật 3-trạng-thái + tiêm ngày vào prompt | **20/20** | **20/20** | Khép vòng. Dừng tinh chỉnh tại đây — tránh overfit vào 20 case |

---

## 10. Trạng thái tiến độ

### ✅ Đã hoàn thành (test OK)
1. Setup môi trường (venv 3.12, các lib).
2. `config.py` — đọc `.env` type-safe; đã thêm `chroma_collection_name`, `chunk_size`,
   `chunk_overlap`, `cors_origins`.
3. `main.py` — FastAPI + lifespan + CORS + **global exception handler** + router health/cv/analysis.
4. `embedding_service.py` — `embed_text` + `embed_batch` (đã sửa type hint `list[str]`).
5. `llm_service.py` — `generate` + `generate_json` + **`generate_structured` (response_schema)**.
6. `vector_service.py` — kiến trúc B3: collection chung, filter `cv_id`, `delete_cv`. Test cô lập OK.
7. Test Gemini + embedding + vector: search ngữ nghĩa đúng.
8. `document_service.py` — extract → clean → chunk hybrid, facade `process_file`. Test kỹ.
9. `core/exceptions.py` — `AppException` + `DocumentProcessingError` (422) + `CVNotFoundError`
   (404) + `LLMResponseError` (502).
10. **`schemas.py`** — Pydantic v2, 3 tầng model, enum, validation range, `to_response()`. Test OK.
11. **`cv.py`** — `POST /cv/upload`, test 3 case (thành công / đuôi sai / rỗng) pass.
12. **`analysis.py`** — `POST /analysis`, RAG + structured output. Test end-to-end pass
    (CV mẫu junior backend vs JD thật: verdict/score hợp lý, evidence trích nguyên văn,
    missing_skills đúng, suggestions tiếng Việt; case cv_id sai trả 404).
13. **`health.py`** — `GET /health` (liveness) + `GET /health/ready` (readiness: heartbeat +
    mở collection + `count()` chạm đĩa thật; Chroma hỏng → 503). Đã đăng ký router.
    Test 5 case pass (route đăng ký / liveness / readiness OK / giả lập Chroma chết → 503 / khôi phục).

14. **pytest thật trong `tests/`** — HOÀN TẤT ma trận 6 file, **32 test xanh ~3s, coverage 91%**.
    Hạ tầng + chi tiết từng file: xem mục 9 và PROGRESS.md.
15. Dọn dẹp: đã xoá 3 file test tạm ở root (được duyệt); suite vẫn 32/32 xanh sau khi xoá.
16. **Chống LLM-as-judge variance (A+B)** — từ kết quả test tay của người dùng (overall rung
    90/75/85): temperature 0.2 → 0.0 + verdict do backend suy (`MatchVerdict.from_score`).
    Thêm 10 test biên band; suite 42 test xanh.
17. **Gói giảm điểm trừ khi test — phần 1**: refactor tách `ingest_cv` (42 test cũ xanh nguyên,
    không sửa chữ nào — trọng tài của refactor) + `POST /analysis/direct` (upload + phân tích
    1 request; hết copy cvId tay, hết escape `\n` khi dán JD). +3 test → suite 45 xanh.
18. **Gói giảm điểm trừ — phần 2 (khép gói)**: `GET /cv` (danh sách từ metadata Chroma,
    filename tra uploads/) + `DELETE /cv/{cv_id}` 204 (xóa index + file gốc; 404 nếu không có);
    `vector_service` thêm `list_cvs`/`has_cv`; schema `CVListItem`. +3 test → suite 48 xanh.

19. **Eval harness + 3 vòng cải thiện prompt — HOÀN TẤT 20/20** (xem bảng hành trình ở mục 9):
    dataset 20 cặp nhãn tay, 4 lượt đo, 2 lần chuyển logic prompt→code (verdict `from_score`,
    floor `same_field`), tiêm ngày hiện tại vào prompt, grounding thực ~100%. Suite 52 test xanh.
20. **Resources cho suggestions** (bước 0 của giai đoạn frontend): `ResourceLink` +
    `resource_service` (catalog ~30 skill + fallback search tự ráp — LLM không sinh URL),
    enrich trong `_run_analysis`. +6 test → suite 58 xanh.

### ⏳ Còn lại (theo ưu tiên)
1. Frontend ReactJS.
2. Cân nhắc sau: multi-query theo khía cạnh JD nếu retrieval sót; BackgroundTasks nếu CV dài;
   test route health + fixture PDF + 1-2 smoke test `@pytest.mark.live` để phủ nốt phần trắng coverage.

---

## 11. Bẫy đã gặp & cách xử lý

| Bẫy | Triệu chứng | Cách xử lý |
|---|---|---|
| **PyPDF2 deprecated** | Lib cũ, không bảo trì | Dùng `pypdf` |
| **Python 3.14** | Thiếu wheel cho vài lib | Dùng 3.12 |
| **ChromaDB telemetry posthog** | Log lỗi/nhiễu từ posthog | Ghim `posthog<6.0.0` + tắt logger `chromadb.telemetry.product.posthog` |
| **`sys.path` khi test trực tiếp** | `python app/services/x.py` không import được `app.` | Đặt file test thủ công ở **project root** |
| **SDK Gemini cũ vs mới** | Nhầm `google-generativeai` cũ | Dùng `google-genai` mới: `from google import genai`, client pattern |
| **Sai `task_type` embedding** | Retrieval kém chính xác | Document→`RETRIEVAL_DOCUMENT`, query→`RETRIEVAL_QUERY` |
| **Enum ra `<Enum.X>` khi dump** | JSON có `"SectionType.SKILLS"` | Dùng `(str, Enum)` + `model_dump(mode="json")` |
| **Config thiếu biến mà service đã gọi** | App nổ NGAY LÚC IMPORT (`AttributeError` trên `settings`) | Thêm field vào `config.py` TRƯỚC khi viết code gọi nó; smoke test `python -c "import app.main"` sau mỗi bước |
| **Embed query dài quá giới hạn model** | `gemini-embedding-001` chỉ nhận ~2048 token, JD tới 20k ký tự | Cắt query ở `MAX_QUERY_CHARS=8000` trước khi embed (prompt LLM vẫn dùng toàn văn) |
| **`n_results` > số chunk trong index** | Chroma in warning "updating n_results = N" | Vô hại — Chroma tự hạ k; chỉ là cosmetic |
| **`-> None` + `status_code=204` nổ lúc import** | "Status code 204 must not have a response body" ngay khi đăng ký route | Do `from __future__ import annotations`: FastAPI đọc annotation `None` thành response model NoneType. Khai `response_model=None` TƯỜNG MINH trên decorator |
| **Điểm LLM chấm rung giữa các lần gọi** | Cùng CV+JD ra 90/75/85; verdict nhảy band strong↔good | temperature=0.0 + verdict do backend suy từ overall (`MatchVerdict.from_score`) — logic tất định thì về code, đừng để trong prompt. Còn rung > ±5 → self-consistency (median 3 lần) |
| **Luật "floor" trong prompt bị công thức đè** | Dặn "cùng ngành đừng chấm dưới 30" nhưng model vẫn ra 17 khi các trục điểm quá thấp (vòng eval #1) | Hai mệnh lệnh xung đột mà không nói thứ tự ưu tiên → model theo cái cụ thể hơn. Fix kiến trúc (A+B v2): LLM trả dữ kiện rời rạc `same_field`, backend áp floor trong `to_response` — vá bằng lời mãi không bằng chuyển logic tất định về code |

---

## 12. Câu hỏi phỏng vấn tự kiểm tra

Nếu trả lời trôi chảy những câu này → đã hiểu sâu dự án. Câu nào có (★) là có SỐ LIỆU THẬT
từ chính project để kể làm bằng chứng.

**A. RAG, embedding, chunking**
1. RAG là gì? Khi nào RAG *bắt buộc*, khi nào chỉ là lựa chọn? (★ CV nhỏ lọt context — vì sao vẫn dùng)
2. Embedding là gì? Vì sao text gần nghĩa thì vector gần nhau? Cosine vs Euclidean?
3. `task_type` `RETRIEVAL_QUERY` vs `RETRIEVAL_DOCUMENT` khác gì, dùng sai thì sao?
4. Vì sao phải chunking? Trade-off nhỏ/lớn? Overlap để làm gì? Vì sao chọn hybrid section-based?
   (★ eval: CV rơi fallback vẫn 76-84 điểm — fallback không hại chất lượng)
5. Chọn top-k thế nào? Quan hệ giữa k và luật grounding "không có trong trích đoạn = không có"?
6. Multi-tenant trong vector DB: 1 collection + filter metadata vs tách collection — trade-off?
   Thiết kế metadata theo nguyên tắc nào? (giữ `section` vì hạ nguồn cần)
7. Vì sao tự viết chunking thay vì LangChain? Trade-off?

**B. Structured output & schema**
8. `response_mime_type=json` vs `response_schema` (constrained decoding) khác nhau ở tầng nào?
9. Vì sao LLM không nên sinh `cv_id`/`analyzed_at`/verdict? Ai gắn/suy chúng? (★ A+B)
10. Vì sao tách schema 3 tầng (internal/API/LLM)? Đổi 1 tầng có vỡ tầng khác không?
11. Output LLM có đáng tin như input người dùng không? Tường lửa validate đặt ở đâu?
    (`Field(ge=0, le=100)` chặn điểm 150)

**C. Testing hệ thống LLM**
12. Test khác eval thế nào? Cái gì mock, cái gì dùng thật — theo tiêu chí nào?
13. Fake embedding thiết kế ra sao để test retrieval được? Vì sao `hashlib.md5` chứ không `hash()`?
14. Side effect lúc import phá test isolation thế nào? Cô lập Chroma trong test bằng cách gì
    khi client tạo ở module level?
15. Mock ở tầng nào khi test route vs khi test chính service LLM? "Patch tại nơi tên được dùng" là gì?
16. Làm sao biết một test "có thể fail"? Test hợp đồng vs test cài đặt khác gì?
17. Coverage 91% đọc thế nào cho đúng? Chỗ trắng nào là cố ý, vì sao? (★)

**D. LLM-as-judge & eval**
18. LLM chấm điểm có ổn định không? Đo variance thế nào, xử lý theo những tầng nào?
    (★ 90/75/85 ở temp 0.2 → 79/81/81 sau fix)
19. temperature 0 có tất định tuyệt đối không? Vì sao?
20. Nguyên tắc "rời rạc hóa" khi dùng LLM làm judge? (★ verdict + same_field floor — 2 lần
    prompt thua code)
21. Xây eval harness cần gì: dataset, nhãn, metric nào tự động được? Grounding đo thế nào?
22. Khi metric và model mâu thuẫn, nghi ngờ cái nào trước? (★ giả thuyết "dịch evidence" bị bác
    bằng raw JSON — 5/5 ca là ghép trích thật)
23. Vì sao phải lưu raw response mỗi lượt eval? "Dữ liệu đắt thì lưu, phân tích rẻ thì làm lại."
24. Sửa prompt có "miễn phí" không? Label drift là gì? (★ vòng #2: chữa 1 vỡ 5 vì đổi ngữ nghĩa
    present_in_cv)
25. "Có kỹ năng nhưng dưới mức yêu cầu" — vì sao đây là ca khó của schema bool, xử lý ra sao?

**E. Vận hành & kiến trúc service**
26. Gặp 429 thì làm gì? Phân biệt rate-limit phút vs quota ngày, retry/backoff vs circuit breaker? (★)
27. LLM có biết hôm nay là ngày nào không? Hệ quả với CV ghi "09/2024 - nay"? Fix? (★ kt_vs_ketoan 86→62)
28. Route FastAPI khi nào dùng `def`, khi nào `async def`, khi nào `async def` + `run_in_threadpool`?
29. Liveness vs readiness khác gì? Vì sao health check không nên gọi LLM, và heartbeat gần như
    vô nghĩa với Chroma embedded?
30. Hai loại 422 trong app này đến từ đâu? Vì sao thiết kế error shape theo người tiêu thụ lỗi?

---

*Mục 5 (concept) và mục 12 (câu hỏi) đúc từ các phần "🎓 Giải thích để học" của cả 4 giai đoạn:
backend RAG → pytest → giảm điểm trừ DX → eval & cải thiện prompt. Nhớ cập nhật
[mục 10](#10-trạng-thái-tiến-độ) và [mục 3](#3-cấu-trúc-thư-mục--bản-đồ-đổi-ở-đâu) mỗi khi
thêm/đổi module.*