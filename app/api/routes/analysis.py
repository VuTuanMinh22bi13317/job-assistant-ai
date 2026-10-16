# app/api/routes/analysis.py
"""
Route phân tích CV vs JD — trái tim của Job Assistant AI (luồng RAG hoàn chỉnh).

Luồng xử lý POST /analysis:
1. RETRIEVE : embed JD -> vector_service.query(cv_id, ...) lấy top-k chunk CV
              gần nghĩa nhất (chỉ trong đúng CV đó — filter metadata cv_id).
2. AUGMENT  : ráp JD + các chunk (kèm nhãn section) thành prompt chấm điểm.
3. GENERATE : gọi Gemini với response_schema=LLMAnalysis -> output có cấu trúc,
              đã validate, KHÔNG phải bóc tách text tự do.
4. ASSEMBLE : LLMAnalysis.to_response(...) — backend gắn cv_id/jd_title/analyzed_at
              VÀ tự suy verdict từ overall_score (MatchVerdict.from_score — quyết
              định A+B: LLM sinh nội dung + điểm, backend gắn metadata + kết luận).

Quyết định thiết kế trong file này (xem trade-off chi tiết trong README):
- TOP_K = 10 : CV thường chỉ có ~8-20 chunk (chunk_size 600) nên k=10 phủ gần
  hết CV mà vẫn giữ được cơ chế "ưu tiên phần liên quan". k nhỏ (3-5) tiết kiệm
  token nhưng dễ thiếu bằng chứng -> LLM kết luận oan "CV thiếu kỹ năng X".
- 1 query duy nhất bằng toàn văn JD (không multi-query theo từng khía cạnh JD):
  đơn giản, 1 lần embed; nâng cấp multi-query để dành khi thấy retrieval sót.
- Route khai báo `def` thường (KHÔNG async): mọi việc bên trong (embed, query
  Chroma, gọi Gemini) đều là blocking sync -> để FastAPI tự chạy trong
  threadpool, không chặn event loop như khi bỏ vào `async def`.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.routes.cv import ingest_cv
from app.core.exceptions import CVNotFoundError
from app.models.schemas import AnalysisRequest, AnalysisResponse, JDInput, LLMAnalysis
from app.services.llm_service import llm_service
from app.services.resource_service import enrich_response
from app.services.vector_service import vector_service

router = APIRouter(prefix="/analysis", tags=["Analysis"])

# Số chunk CV lấy ra làm bằng chứng cho LLM.
TOP_K = 10

# gemini-embedding-001 giới hạn đầu vào ~2048 token. JD cho phép tới 20k ký tự
# (~5k token) nên phải cắt bớt TRƯỚC KHI EMBED để tránh lỗi/bị cắt âm thầm.
# Lưu ý: chỉ cắt cho bước embed (retrieve); prompt gửi LLM vẫn dùng TOÀN VĂN JD.
MAX_QUERY_CHARS = 8_000

# ==========================================================================
# SYSTEM INSTRUCTION — "luật chơi" cố định cho mọi lần chấm điểm.
# Tách khỏi prompt (dữ liệu từng request) để: (1) dễ chỉnh sửa/AB-test,
# (2) model coi trọng system instruction hơn nội dung trộn trong prompt.
# ==========================================================================
SYSTEM_INSTRUCTION = """\
Bạn là chuyên gia tuyển dụng kỹ thuật (technical recruiter) giàu kinh nghiệm.
Nhiệm vụ: đánh giá mức độ phù hợp giữa một CV và một Job Description (JD).

LUẬT GROUNDING (chống bịa — quan trọng nhất):
1. CHỈ dùng thông tin trong các TRÍCH ĐOẠN CV được cung cấp. Thông tin không
   xuất hiện trong trích đoạn thì coi như KHÔNG có trong CV.
2. Mỗi kỹ năng khớp (present_in_cv=true) BẮT BUỘC kèm `evidence` là trích dẫn
   nguyên văn (hoặc gần nguyên văn, dưới 200 ký tự) từ trích đoạn CV — giữ
   NGUYÊN NGÔN NGỮ GỐC của CV (không dịch), và TUYỆT ĐỐI không lấy câu chữ
   của JD làm evidence. Không tìm được bằng chứng -> present_in_cv=false
   và evidence=null.
3. Không suy diễn kỹ năng từ chức danh hay tên công ty (làm ở công ty fintech
   không có nghĩa là biết Kafka). Chỉ tính những gì CV viết rõ.
4. Phân biệt "KHÔNG CÓ" với "CÓ NHƯNG DƯỚI MỨC YÊU CẦU" (vòng eval #2 cho
   thấy gộp hai trạng thái này làm một là sai cả hai phía):
   - CV CÓ kỹ năng nhưng mức độ THẤP HƠN JD đòi (vd "Python cơ bản" vs
     "thành thạo Python") -> VẪN present_in_cv=true, evidence ghi rõ mức độ,
     và trừ phần đó vào skills_score. KHÔNG phủ nhận sự tồn tại.
   - present_in_cv=false CHỈ khi CV hoàn toàn không thể hiện kỹ năng đó.
   - Riêng khi JD nêu ĐÍCH DANH công nghệ cụ thể (vd "PostgreSQL") mà CV chỉ
     có khái niệm chung chung (vd "SQL cơ bản") -> coi là KHÔNG có, đưa vào
     missing_skills.

RUBRIC CHẤM ĐIỂM (0-100, chấm từng trục độc lập):
- skills_score: tỉ lệ kỹ năng JD yêu cầu có bằng chứng trong CV; kỹ năng bắt
  buộc (must-have) nặng hơn kỹ năng cộng điểm (nice-to-have).
- experience_score: số năm, seniority và độ liên quan của kinh nghiệm thực tế
  so với yêu cầu JD (đúng domain/loại công việc mới được điểm cao).
- education_score: so bằng cấp/chuyên ngành với yêu cầu JD. Nếu JD KHÔNG yêu
  cầu học vấn thì cho 70 điểm trung lập và nói rõ điều đó trong summary.
- overall_score: trung bình có trọng số, khoảng skills 50% + experience 35%
  + education 15% (vai trò kỹ thuật thông thường), có thể xê dịch nhẹ nếu JD
  nhấn mạnh khác đi.
- same_field: đánh giá ĐỘC LẬP với điểm số — true nếu CV và JD thuộc cùng
  ngành hoặc ngành gần nhau (vd backend và data engineering), false nếu trái
  ngành (vd backend và kế toán). Chỉ xét LĨNH VỰC chuyên môn, tuyệt đối không
  xét cấp bậc hay số năm kinh nghiệm.

ĐẦU RA:
- `summary` (2-4 câu) và mọi `suggestions` viết bằng TIẾNG VIỆT; tên kỹ năng,
  công nghệ giữ nguyên gốc (Python, FastAPI...).
- `missing_skills`: các kỹ năng JD đòi hỏi nhưng hoàn toàn không có bằng chứng.
- `suggestions`: cụ thể, hành động được (viết lại bullet nào, thêm số liệu gì,
  học chứng chỉ nào), gắn priority theo mức ảnh hưởng tới khả năng đậu JD này.
- `related_skill` (trong suggestions): phải là TÊN KỸ NĂNG NGẮN GỌN 1-4 từ
  (vd "CRM", "Excel", "Kubernetes", "kỹ năng giao tiếp") — TUYỆT ĐỐI không
  chép nguyên câu yêu cầu của JD vào đây (backend dùng field này tra link
  học tập, câu dài sẽ tra hỏng).
"""


def _build_prompt(jd_title: str | None, jd_content: str, retrieved: list[dict]) -> str:
    """
    Ráp phần AUGMENT của RAG: JD + các chunk CV lấy được từ vector DB.

    Mỗi chunk in kèm `section` + `chunk_id`:
    - section giúp LLM chấm đúng trục (experience_score nhìn vào section
      experience, education_score nhìn education...) — đây chính là lý do
      B3 giữ `section` trong metadata Chroma.
    - chunk_id giúp debug: đối chiếu evidence LLM trích với chunk gốc.
    """
    evidence_blocks = "\n\n".join(
        f"--- Trích đoạn {i + 1} | section: {c['section']} | chunk_id: {c['chunk_id']} ---\n"
        f"{c['text']}"
        for i, c in enumerate(retrieved)
    )
    jd_block = f"Vị trí: {jd_title}\n\n{jd_content}" if jd_title else jd_content

    # Tiêm ngày hiện tại: LLM KHÔNG có đồng hồ — không biết "nay" trong
    # "09/2024 - nay" là bao giờ -> tính sai số năm kinh nghiệm (vòng eval #2:
    # kt_vs_ketoan experienceMatch sụp 20 vì chuyện này).
    return f"""\
Hôm nay là {datetime.now():%d/%m/%Y} — dùng mốc này để quy đổi các khoảng thời gian
tương đối trong CV ("nay", "hiện tại", "present").

# JOB DESCRIPTION
{jd_block}

# TRÍCH ĐOẠN CV ({len(retrieved)} đoạn liên quan nhất, xếp theo độ gần nghĩa với JD)
{evidence_blocks}

# YÊU CẦU
Đánh giá mức độ phù hợp của ứng viên với JD trên, tuân thủ đúng luật grounding
và rubric trong system instruction. Trả về đầy đủ các trường theo schema."""


def _run_analysis(cv_id: str, jd: JDInput) -> AnalysisResponse:
    """
    Lõi phân tích dùng chung cho POST /analysis và POST /analysis/direct —
    4 nhịp RAG (retrieve -> augment -> generate -> assemble). Blocking sync
    có chủ đích: caller sync để FastAPI chạy threadpool, caller async phải
    tự bọc run_in_threadpool.
    """
    # --- 1. RETRIEVE ---
    # Query = title + toàn văn JD (title chứa tín hiệu mạnh: "Senior Backend..."),
    # cắt ở MAX_QUERY_CHARS vì giới hạn đầu vào của model embedding.
    jd_query = f"{jd.title}\n{jd.content}" if jd.title else jd.content
    retrieved = vector_service.query(
        cv_id=cv_id,
        query_text=jd_query[:MAX_QUERY_CHARS],
        n_results=TOP_K,
    )
    # query() filter where={"cv_id": ...} nên list rỗng nghĩa là CV không tồn tại
    # (mọi CV upload thành công đều có >= 1 chunk — ingest_cv đã chặn CV rỗng).
    if not retrieved:
        raise CVNotFoundError(cv_id)

    # --- 2. AUGMENT ---
    prompt = _build_prompt(jd.title, jd.content, retrieved)

    # --- 3. GENERATE (structured output — Gemini bị ràng buộc theo LLMAnalysis) ---
    analysis = llm_service.generate_structured(
        prompt=prompt,
        response_schema=LLMAnalysis,
        system_instruction=SYSTEM_INSTRUCTION,
        # [A] 0.0 chứ không phải 0.2: đo thực tế (cùng CV+JD chạy 3 lần) thấy
        # overall rung 90/75/85 ở temp 0.2. temp 0.0 giảm mạnh nhưng KHÔNG
        # triệt để (nhiễu floating-point/batching phía server vẫn còn).
        temperature=0.0,
    )

    # --- 4. ASSEMBLE: backend gắn metadata + tự suy verdict từ overall_score,
    # rồi gắn link học tập cho từng suggestion (catalog tất định — LLM không
    # sinh URL, xem resource_service) ---
    return enrich_response(analysis.to_response(cv_id=cv_id, jd_title=jd.title))


@router.post("", response_model=AnalysisResponse)
def analyze_cv(request: AnalysisRequest) -> AnalysisResponse:
    """
    Chấm điểm CV ĐÃ upload trước đó (định danh bằng cv_id) với một JD.
    Dùng khi 1 CV cần chạy nhiều JD — không tốn công re-upload/re-embed.

    Lỗi (qua global exception handler):
    - 404 CV_NOT_FOUND: cv_id không có chunk nào trong ChromaDB.
    - 502 LLM_RESPONSE_ERROR: Gemini trả output không khớp schema (hiếm).
    """
    return _run_analysis(request.cv_id, request.jd)


@router.post("/direct", response_model=AnalysisResponse)
async def analyze_direct(
    file: UploadFile = File(..., description="File CV (.pdf/.txt/.md, tối đa 5MB)"),
    # Form field đặt alias camelCase cho khớp quy ước API. Ràng buộc lặp lại
    # đúng JDInput (min 30 / max 20k) — FastAPI validate ngay tầng form.
    jd_title: str | None = Form(default=None, alias="jdTitle", max_length=200),
    jd_content: str = Form(..., alias="jdContent", min_length=30, max_length=20_000),
) -> AnalysisResponse:
    """
    Upload + phân tích trong MỘT request (multipart form) — "một phát ăn ngay".

    Vì sao multipart chứ không JSON: request có file đính kèm thì bắt buộc
    multipart; và nhờ JD là form field (textarea trong Swagger) nên dán JD
    nhiều dòng KHÔNG cần escape \\n như khi nhét vào chuỗi JSON.

    Trade-off (đã chốt): tiện one-shot nhưng mỗi lần gọi là re-embed toàn bộ CV;
    muốn 1 CV chạy nhiều JD thì dùng cặp /cv/upload + /analysis như cũ
    (response có cvId để tái dùng cho /analysis).
    """
    ingested = await ingest_cv(file)
    jd = JDInput(title=jd_title, content=jd_content)
    # _run_analysis blocking (Chroma + Gemini) mà route này là async def
    # (cần await đọc file) -> phải tự đẩy sang threadpool, không để chặn
    # event loop suốt mấy giây LLM suy nghĩ.
    return await run_in_threadpool(_run_analysis, ingested.cv_id, jd)
