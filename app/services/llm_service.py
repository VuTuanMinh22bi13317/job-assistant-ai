# app/services/llm_service.py
"""
Service gọi Gemini để SINH TEXT: phân tích CV vs JD, chấm điểm phù hợp,
gợi ý cải thiện. Khác với embedding_service (chỉ tạo vector), service này
tạo ra văn bản/phản hồi có nghĩa cho người dùng.
"""
import json
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.core.exceptions import LLMResponseError

# T = "một class Pydantic bất kỳ". Nhờ TypeVar, khi gọi
# generate_structured(..., response_schema=LLMAnalysis) thì type checker
# biết kết quả trả về CHÍNH XÁC là LLMAnalysis (không phải BaseModel chung chung).
T = TypeVar("T", bound=BaseModel)


class LLMService:
    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """
        Sinh text tự do từ một prompt.

        Args:
            prompt: nội dung yêu cầu.
            system_instruction: "vai trò/luật chơi" đặt cho model
                                 (vd: "Bạn là chuyên gia tuyển dụng...").
            temperature: 0.0 = bám sát, ít sáng tạo; cao hơn = đa dạng hơn.
                         Chấm điểm nên để thấp; gợi ý cải thiện có thể cao hơn.

        Returns:
            str: văn bản Gemini trả về.
        """
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,  # None cũng hợp lệ
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return response.text

    def generate_json(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> dict:
        """
        Sinh kết quả ở dạng JSON có cấu trúc (dùng cho chấm điểm phù hợp).
        Ta ép model trả JSON để code phía sau parse được chắc chắn,
        thay vì phải bóc tách văn bản tự do.
        """
        config = types.GenerateContentConfig(
            temperature=0.2,  # chấm điểm cần ổn định, ít ngẫu nhiên
            system_instruction=system_instruction,
            response_mime_type="application/json",  # buộc trả về JSON hợp lệ
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        # response.text lúc này là chuỗi JSON -> parse thành dict Python
        return json.loads(response.text)

    def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> T:
        """
        Sinh output CÓ CẤU TRÚC theo một Pydantic model (constrained decoding).

        Khác generate_json (chỉ ép "JSON hợp lệ" nhưng HÌNH DẠNG tùy model):
        - response_schema: Gemini nhận JSON Schema sinh từ Pydantic model và
          RÀNG BUỘC ngay lúc decode — đúng field, đúng kiểu, enum chỉ được chọn
          trong các giá trị cho phép. Không còn cảnh model tự chế key lạ.
        - SDK tự parse: response.parsed là INSTANCE của model (không phải dict).

        Args:
            prompt: nội dung yêu cầu.
            response_schema: class Pydantic mô tả hình dạng output (vd LLMAnalysis).
            system_instruction: vai trò/luật chơi cho model.
            temperature: mặc định 0.2 — chấm điểm cần ổn định.

        Returns:
            Instance của `response_schema` đã được validate.

        Raises:
            LLMResponseError: model trả về rỗng hoặc không khớp schema
                              (hiếm khi xảy ra nhờ constrained decoding,
                              nhưng vẫn phải phòng — network cắt giữa chừng,
                              output bị cắt vì max tokens...).
        """
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,  # <-- điểm nâng cấp so với generate_json
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )

        # Đường sung sướng: SDK đã parse sẵn thành đúng model.
        parsed = response.parsed
        if isinstance(parsed, response_schema):
            return parsed

        # Đường dự phòng: .parsed là None (SDK parse thất bại) nhưng .text có thể
        # vẫn là JSON tốt -> tự validate lại bằng Pydantic trước khi bỏ cuộc.
        if response.text is None:
            raise LLMResponseError("Gemini không trả về nội dung nào (response.text is None).")
        try:
            return response_schema.model_validate_json(response.text)
        except ValidationError as exc:
            raise LLMResponseError(
                f"Output của Gemini không khớp schema {response_schema.__name__}: {exc}"
            ) from exc


# Instance dùng chung toàn app
llm_service = LLMService()