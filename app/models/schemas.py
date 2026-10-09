"""
app/models/schemas.py

Pydantic v2 models cho toàn bộ API của Job Assistant AI.

Nguyên tắc tổ chức:
- Enum: các giá trị cố định (dùng để constrain LLM output sau này).
- Internal models: dữ liệu luân chuyển giữa các service (không expose ra client).
- Request models: dữ liệu client GỬI LÊN.
- Response models: dữ liệu server TRẢ VỀ (là "hợp đồng" với frontend).
- LLM output models: schema ta ép Gemini phải tuân theo (response_schema).

Quy ước:
- Model request/response API dùng camelCase khi serialize ra JSON (chuẩn JS/React),
  nhưng code Python vẫn snake_case → dùng alias + populate_by_name.
- Internal & LLM models giữ snake_case thuần cho gọn.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


# ==========================================================================
# 1. ENUMS — tập giá trị cố định
# ==========================================================================

# Ghi chú (A1): loại section KHÔNG định nghĩa Enum ở đây. document_service.py
# đã có `SectionName = Literal["summary","experience",...]` làm nguồn sự thật.
# Ở tầng API ta để `section: str` (trong ChunkPreview) để không phải đồng bộ 2
# nơi mỗi khi thêm section mới. Enum chỉ dùng cho giá trị mà LLM phải bị RÀNG
# BUỘC (MatchVerdict, Priority) — nơi constrain output thật sự có giá trị.


class MatchVerdict(str, Enum):
    """
    Kết luận tổng thể mức độ phù hợp CV vs JD.

    [Quyết định A+B — chống LLM-as-judge variance] Verdict KHÔNG còn do LLM
    chọn nữa: backend TỰ SUY từ overall_score qua from_score(). Lý do: để LLM
    vừa chấm điểm vừa tự chọn band thì hai thứ có thể lệch nhau giữa các lần
    chạy; ánh xạ band là logic TẤT ĐỊNH -> thuộc về code (test được), không
    thuộc về prompt.
    """
    STRONG_MATCH = "strong_match"      # rất phù hợp
    GOOD_MATCH = "good_match"          # khá phù hợp
    PARTIAL_MATCH = "partial_match"    # phù hợp một phần
    WEAK_MATCH = "weak_match"          # yếu
    NOT_A_MATCH = "not_a_match"        # không phù hợp

    @classmethod
    def from_score(cls, overall: int) -> "MatchVerdict":
        """Ánh xạ band điểm -> verdict (trước đây nằm trong SYSTEM_INSTRUCTION)."""
        if overall >= 85:
            return cls.STRONG_MATCH
        if overall >= 70:
            return cls.GOOD_MATCH
        if overall >= 50:
            return cls.PARTIAL_MATCH
        if overall >= 30:
            return cls.WEAK_MATCH
        return cls.NOT_A_MATCH


class Priority(str, Enum):
    """Độ ưu tiên của một gợi ý cải thiện CV."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ==========================================================================
# 2. BASE CONFIG — dùng chung cho các model "public API"
# ==========================================================================

class APIModel(BaseModel):
    """
    Base cho mọi model xuất hiện trong request/response API.

    - alias_generator=to_camel: field snake_case (chunk_index) tự có alias camelCase
      (chunkIndex) khi serialize -> hợp gu frontend JS.
    - populate_by_name=True: vẫn cho phép khởi tạo bằng tên snake_case trong code Python.
    - from_attributes=True: cho phép tạo model từ object có attribute (ORM/dataclass) qua
      model_validate(obj) — tiện khi map từ internal model sang response model.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        # Không bật use_enum_values ở đây: ta MUỐN giữ enum object trong code
        # (để so sánh, autocomplete). Serialize ra string dùng model_dump(mode="json").
    )


# ==========================================================================
# 3. INTERNAL MODEL — LƯU Ý (quyết định A1)
# ==========================================================================
# `DocumentChunk` (đơn vị chảy qua pipeline document -> embedding -> vector)
# KHÔNG định nghĩa ở đây. Nó là @dataclass đã có sẵn và test kỹ trong
# app/services/document_service.py, với các field: chunk_id, section, content,
# char_count. Đó là NGUỒN SỰ THẬT duy nhất cho internal chunk.
#
# schemas.py chỉ lo tầng API (request/response) + tầng LLM. Khi cần biểu diễn
# một chunk cho client, ta map dataclass đó -> ChunkPreview (bên dưới).
#
# Vì sao không định nghĩa lại ở đây (A1 thay vì A2):
# - document_service.py đã test kỹ; đừng đụng code đang chạy đúng.
# - Tránh 2 class trùng tên khác cấu trúc -> nguồn lỗi âm thầm.


# ==========================================================================
# 4. REQUEST MODELS — client gửi lên
# ==========================================================================

class JDInput(APIModel):
    """
    Job Description do người dùng dán vào.
    Không nhận file cho JD (đơn giản hoá) — chỉ text thuần.
    """
    title: str | None = Field(
        default=None,
        max_length=200,
        description="Tên vị trí (tuỳ chọn), vd 'Junior Backend Engineer'",
    )
    content: str = Field(
        ...,
        min_length=30,           # chặn JD rỗng/quá ngắn ngay tại tầng validation
        max_length=20_000,
        description="Toàn văn JD",
    )


class AnalysisRequest(APIModel):
    """
    Yêu cầu phân tích: gắn một CV (đã upload trước, định danh bằng cv_id)
    với một JD để chấm điểm.

    Lý do dùng cv_id thay vì gửi lại toàn bộ CV:
    - CV đã được parse + embed + lưu vào ChromaDB ở bước upload.
    - Ở bước analysis, ta chỉ cần trỏ tới đúng collection/records của CV đó.
    """
    cv_id: str = Field(..., description="ID của CV đã upload (trả về từ /cv/upload)")
    jd: JDInput = Field(..., description="Job Description để so khớp")


# ==========================================================================
# 5. RESPONSE MODELS — server trả về (hợp đồng với frontend)
# ==========================================================================

class ChunkPreview(APIModel):
    """
    Bản rút gọn của một chunk (DocumentChunk dataclass trong document_service)
    để trả cho client sau khi upload — không lộ toàn bộ internal, chỉ đủ để
    UI hiển thị/kiểm chứng chất lượng chunking.

    Lưu ý field khớp với dataclass thật:
    - chunk_id  <- DocumentChunk.chunk_id (vd "experience_0")
    - section   <- DocumentChunk.section  (Literal string, KHÔNG phải Enum)
    - preview   <- DocumentChunk.content[:preview_len]
    """
    chunk_id: str = Field(..., description="Định danh chunk, vd 'experience_0'")
    section: str = Field(..., description="Section CV mà chunk thuộc về")
    char_count: int
    preview: str = Field(..., description="Vài trăm ký tự đầu của chunk để xem nhanh")

    @classmethod
    def from_chunk(cls, chunk, preview_len: int = 200) -> "ChunkPreview":
        """
        Map dataclass DocumentChunk (từ document_service) -> model public.
        Không type-hint cụ thể để tránh vòng import service <-> schemas;
        chỉ cần object có .chunk_id / .section / .char_count / .content.
        """
        return cls(
            chunk_id=chunk.chunk_id,
            section=chunk.section,
            char_count=chunk.char_count,
            preview=chunk.content[:preview_len],
        )


class CVUploadResponse(APIModel):
    """Kết quả sau khi upload + parse + embed một CV."""
    cv_id: str = Field(..., description="ID để dùng cho các request phân tích sau này")
    filename: str
    total_chunks: int = Field(..., ge=0)
    sections_detected: list[str] = Field(
        default_factory=list,
        description="Các section nhận diện được (vd ['experience','skills']); "
                    "chỉ ['other'] nếu rơi vào fallback fixed-size",
    )
    chunks: list[ChunkPreview] = Field(
        default_factory=list,
        description="Preview các chunk để client kiểm chứng chất lượng chunking",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class CVListItem(APIModel):
    """
    Một dòng trong danh sách CV (GET /cv) — phục vụ test tay + màn hình
    "CV của tôi" trên frontend.

    filename có thể None: tên file tra từ data/uploads theo prefix cv_id;
    Chroma mới là nguồn sự thật về index, file chỉ là bản lưu gốc (ai đó
    xóa file tay thì CV vẫn phân tích được — index còn).
    """
    cv_id: str
    filename: str | None = None
    total_chunks: int = Field(..., ge=0)
    sections: list[str] = Field(default_factory=list)


class SkillMatch(APIModel):
    """
    Một kỹ năng/keyword từ JD và tình trạng nó có mặt trong CV hay không.
    Đây là phần 'evidence' giúp điểm số minh bạch, không phải con số trên trời.
    """
    skill: str = Field(..., description="Tên kỹ năng/keyword lấy từ JD")
    present_in_cv: bool = Field(..., description="CV có thể hiện kỹ năng này không")
    evidence: str | None = Field(
        default=None,
        description="Trích đoạn từ CV chứng minh (None nếu thiếu)",
    )


class ResourceLink(APIModel):
    """
    Một link tài nguyên học tập gắn vào suggestion.

    QUAN TRỌNG: URL do BACKEND sở hữu (catalog biên soạn tay trong
    resource_service, hoặc link tìm kiếm tự ráp) — LLM KHÔNG BAO GIỜ sinh URL.
    LLM bịa URL là bệnh kinh điển: link trông thật nhưng chết/trỏ sai, và
    không có cách nào grounding được URL như grounding evidence.
    """
    title: str
    url: str
    kind: Literal["docs", "roadmap", "course", "search"] = "docs"


class ImprovementSuggestion(APIModel):
    """Một gợi ý cải thiện CV để khớp JD hơn."""
    priority: Priority
    title: str = Field(..., max_length=120, description="Tóm tắt ngắn gợi ý")
    detail: str = Field(..., description="Giải thích cụ thể nên sửa gì, thêm gì")
    related_skill: str | None = Field(
        default=None,
        description="Kỹ năng/keyword liên quan (nếu có)",
    )
    resources: list[ResourceLink] = Field(
        default_factory=list,
        description="Link học tập cho related_skill — backend gắn sau khi LLM "
                    "trả kết quả (xem resource_service), không nằm trong LLM schema",
    )


class MatchScore(APIModel):
    """
    Điểm phù hợp chi tiết. Tách nhỏ để UI vẽ được breakdown,
    và để LLM buộc phải 'suy nghĩ có cấu trúc' thay vì phán 1 số.
    """
    overall: int = Field(..., ge=0, le=100, description="Điểm tổng 0-100")
    skills_match: int = Field(..., ge=0, le=100, description="Mức khớp kỹ năng")
    experience_match: int = Field(..., ge=0, le=100, description="Mức khớp kinh nghiệm")
    education_match: int = Field(..., ge=0, le=100, description="Mức khớp học vấn")


class AnalysisResponse(APIModel):
    """
    Kết quả cuối cùng trả cho client: điểm + verdict + bằng chứng + gợi ý.
    Đây là thứ frontend render thành báo cáo.
    """
    cv_id: str
    jd_title: str | None = None
    verdict: MatchVerdict
    score: MatchScore
    summary: str = Field(..., description="Nhận xét tổng quan 2-4 câu")
    matched_skills: list[SkillMatch] = Field(default_factory=list)
    missing_skills: list[str] = Field(
        default_factory=list,
        description="Kỹ năng JD yêu cầu nhưng CV thiếu hẳn",
    )
    suggestions: list[ImprovementSuggestion] = Field(default_factory=list)
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ==========================================================================
# 6. LLM OUTPUT MODELS — schema ta ÉP Gemini tuân theo (response_schema)
# ==========================================================================
# Vì sao tách riêng khỏi AnalysisResponse?
# - LLM chỉ cần sinh phần "phân tích" (verdict, score, skills, suggestions).
# - Các field như cv_id, analyzed_at là do BACKEND gắn vào, KHÔNG để LLM sinh
#   (LLM sinh timestamp/id là vô nghĩa và dễ sai).
# - Giữ schema đưa cho Gemini càng gọn càng tốt -> model tập trung, ít lỗi, rẻ token.
# Các model này KHÔNG dùng alias camelCase: ta cần key snake_case ổn định trong prompt.

class LLMSkillMatch(BaseModel):
    skill: str
    present_in_cv: bool
    evidence: str | None = None


class LLMSuggestion(BaseModel):
    priority: Priority
    title: str
    detail: str
    related_skill: str | None = None


# [A+B v2] Floor cho ứng viên cùng ngành: không bao giờ rơi xuống band
# not_a_match (<30) chỉ vì non kinh nghiệm. Đặt 32 (không phải 30) để không
# nằm sát mép band — tránh rung nhẹ là đổi verdict.
FLOOR_CUNG_NGANH = 32


class LLMAnalysis(BaseModel):
    """
    Đây chính là 'response_schema' truyền cho Gemini.
    Cấu trúc phẳng, rõ ràng, mọi field đều là thứ LLM có thể suy luận từ CV + JD.

    Lưu ý [A+B]: KHÔNG có field verdict — verdict do backend suy từ
    overall_score (MatchVerdict.from_score) để điểm và band nhất quán 100%.
    [A+B v2]: same_field là DỮ KIỆN RỜI RẠC để backend áp floor cùng-ngành —
    vòng eval #1 chứng minh luật floor viết trong prompt bị model bỏ qua khi
    công thức trọng số cho điểm quá thấp → logic tất định phải về code.
    """
    same_field: bool = Field(
        ...,
        description="CV và JD có cùng ngành hoặc ngành gần nhau không "
                    "(vd backend và data engineering = gần; backend và kế toán "
                    "= trái ngành). Chỉ xét lĩnh vực chuyên môn, không xét cấp bậc.",
    )
    overall_score: int = Field(..., ge=0, le=100)
    skills_score: int = Field(..., ge=0, le=100)
    experience_score: int = Field(..., ge=0, le=100)
    education_score: int = Field(..., ge=0, le=100)
    summary: str
    matched_skills: list[LLMSkillMatch] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    suggestions: list[LLMSuggestion] = Field(default_factory=list)

    def to_response(self, cv_id: str, jd_title: str | None) -> AnalysisResponse:
        """
        Chuyển output thô của LLM -> response API hoàn chỉnh.
        Backend gắn thêm cv_id, jd_title, analyzed_at (những thứ LLM không nên sinh).
        Đây là điểm 'ráp nối' giữa tầng LLM và tầng API.
        """
        # [A+B v2] Áp floor TRƯỚC khi suy verdict, và trả overall ĐÃ floor cho
        # client — điểm hiển thị và verdict phải cùng một con số. Các trục
        # thành phần giữ nguyên (floor là ghi đè có chủ đích, không phải tính lại).
        overall = self.overall_score
        if self.same_field and overall < 30:
            overall = FLOOR_CUNG_NGANH

        return AnalysisResponse(
            cv_id=cv_id,
            jd_title=jd_title,
            # [B] Backend suy verdict từ điểm — không để LLM chọn (hết cảnh
            # điểm 75 mà verdict strong_match, hay 2 lần chạy 2 band khác nhau
            # dù điểm sát nhau chỉ vì LLM "đổi ý").
            verdict=MatchVerdict.from_score(overall),
            score=MatchScore(
                overall=overall,
                skills_match=self.skills_score,
                experience_match=self.experience_score,
                education_match=self.education_score,
            ),
            summary=self.summary,
            matched_skills=[
                SkillMatch(
                    skill=s.skill,
                    present_in_cv=s.present_in_cv,
                    evidence=s.evidence,
                )
                for s in self.matched_skills
            ],
            missing_skills=self.missing_skills,
            suggestions=[
                ImprovementSuggestion(
                    priority=s.priority,
                    title=s.title,
                    detail=s.detail,
                    related_skill=s.related_skill,
                )
                for s in self.suggestions
            ],
        )


# ==========================================================================
# 7. ERROR RESPONSE — khớp với AppException để trả JSON thống nhất
# ==========================================================================

class ErrorResponse(APIModel):
    """
    Body JSON chuẩn khi có lỗi. Global exception handler trong main.py
    sẽ dựng model này từ AppException (message, error_code) rồi trả về.
    """
    error_code: str = Field(..., description="Mã lỗi máy đọc được, vd 'DOCUMENT_PROCESSING_ERROR'")
    message: str = Field(..., description="Thông điệp lỗi dành cho người/để debug")
    detail: str | None = Field(default=None, description="Chi tiết bổ sung (tuỳ chọn)")