# tests/test_llm_service.py
"""
Test generate_structured — mock ở TẦNG SDK (stub llm_service.client).

Vì sao mock tầng SDK chứ không mock generate_structured như các test route:
- Ở đây generate_structured CHÍNH LÀ thứ đang được test (logic parse/fallback/
  raise của NÓ) → phải mock một tầng BÊN DƯỚI nó (client SDK). Nguyên tắc:
  mock dependency của đơn vị đang test, không bao giờ mock chính đơn vị đó.
- Guard autouse `no_real_llm` trong conftest đã patch llm_service.client bằng
  poison object; test này patch ĐÈ lên bằng stub riêng (bản vá sau thắng),
  nên logic thật của generate_structured chạy nguyên bản, chỉ có SDK là giả.
"""
import pytest
from pydantic import BaseModel

from app.core.exceptions import LLMResponseError
from app.services.llm_service import llm_service


class MiniKQ(BaseModel):
    """Schema nhỏ gọn thay cho LLMAnalysis — generate_structured là hàm generic
    (TypeVar), test bằng schema nào cũng chứng minh được cùng hành vi."""
    ket_luan: str
    diem: int


class _FakeResponse:
    """Giả lập object response của google-genai: chỉ cần .parsed và .text —
    đúng 2 attribute mà generate_structured đọc."""

    def __init__(self, parsed=None, text=None):
        self.parsed = parsed
        self.text = text


class _StubModels:
    def __init__(self, response):
        self._response = response
        self.last_call = None  # ghi lại kwargs để test "dây nối" xuống SDK

    def generate_content(self, *, model, contents, config):
        self.last_call = {"model": model, "contents": contents, "config": config}
        return self._response


class _StubClient:
    def __init__(self, response):
        self.models = _StubModels(response)


def _install_stub(monkeypatch, response) -> _StubClient:
    stub = _StubClient(response)
    monkeypatch.setattr(llm_service, "client", stub)  # đè lên guard autouse
    return stub


# ==========================================================================
# 1. Đường sung sướng: SDK parse sẵn (.parsed đúng schema) → trả thẳng
# ==========================================================================

def test_parsed_ok_tra_thang_khong_parse_lai(monkeypatch):
    da_parse = MiniKQ(ket_luan="good_match", diem=80)
    stub = _install_stub(
        monkeypatch,
        _FakeResponse(parsed=da_parse, text='{"ket_luan": "good_match", "diem": 80}'),
    )

    ket_qua = llm_service.generate_structured(
        prompt="cham diem CV",
        response_schema=MiniKQ,
        system_instruction="ban la recruiter",
        temperature=0.3,
    )

    # `is` (identity) chứ không phải `==`: trả ĐÚNG instance SDK đã parse,
    # không parse lại/copy — nếu code lỡ validate lần 2 từ text, test này đỏ.
    assert ket_qua is da_parse

    # Test "dây nối": các tham số phải THẬT SỰ xuống tới SDK — quên truyền
    # response_schema thì app vẫn "chạy được" (nhờ mime_type) nhưng mất
    # constrained decoding một cách âm thầm; assert này chặn đường lùi đó.
    cfg = stub.models.last_call["config"]
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema is MiniKQ
    assert cfg.temperature == 0.3
    assert cfg.system_instruction == "ban la recruiter"
    assert stub.models.last_call["model"] == llm_service.model
    assert stub.models.last_call["contents"] == "cham diem CV"


# ==========================================================================
# 2. Đường dự phòng: .parsed = None nhưng .text là JSON hợp lệ → fallback OK
# ==========================================================================

def test_parsed_none_fallback_validate_tu_text(monkeypatch):
    _install_stub(
        monkeypatch,
        _FakeResponse(parsed=None, text='{"ket_luan": "kha", "diem": 70}'),
    )

    ket_qua = llm_service.generate_structured(prompt="p", response_schema=MiniKQ)

    assert ket_qua == MiniKQ(ket_luan="kha", diem=70)


# ==========================================================================
# 3. Text rác → LLMResponseError 502 (cả 2 kiểu rác)
# ==========================================================================

@pytest.mark.parametrize(
    "text_rac",
    [
        "Xin loi, toi khong the tra ve JSON duoc.",  # không phải JSON
        '{"ket_luan": "ok"}',                         # JSON hợp lệ nhưng SAI schema (thiếu diem)
    ],
)
def test_text_rac_raise_llm_response_error(monkeypatch, text_rac):
    _install_stub(monkeypatch, _FakeResponse(parsed=None, text=text_rac))

    with pytest.raises(LLMResponseError) as excinfo:
        llm_service.generate_structured(prompt="p", response_schema=MiniKQ)

    # 502 + error_code là hợp đồng với global handler / frontend (retry được).
    assert excinfo.value.status_code == 502
    assert excinfo.value.error_code == "LLM_RESPONSE_ERROR"


# ==========================================================================
# 4. Không có cả parsed lẫn text (response rỗng) → LLMResponseError
#    (nhánh có thật trong code: output bị cắt/mạng đứt giữa chừng)
# ==========================================================================

def test_response_rong_raise_llm_response_error(monkeypatch):
    _install_stub(monkeypatch, _FakeResponse(parsed=None, text=None))

    with pytest.raises(LLMResponseError):
        llm_service.generate_structured(prompt="p", response_schema=MiniKQ)
