"""
KIS API 예외 메시지 보안 테스트
- _classify_response()가 전체 data dict를 예외 메시지에 포함하지 않는지 검증
- _sanitize_error()가 rt_cd, msg1만 추출하는지 검증
"""

import pytest

from src.kis_api import (
    FatalError,
    KISAPIError,
    RateLimitError,
    RetryableError,
    TokenExpiredError,
    _classify_response,
    _sanitize_error,
)

# 민감 정보가 포함된 가짜 API 응답
SENSITIVE_DATA = {
    "rt_cd": "1",
    "msg_cd": "EGW00123",
    "msg1": "잔고 부족",
    "output": {
        "CANO": "50012345678",
        "ACNT_PRDT_CD": "01",
        "dnca_tot_amt": "999999999",
        "tot_evlu_amt": "123456789",
    },
}

SENSITIVE_KEYS = ["50012345678", "999999999", "123456789", "CANO", "dnca_tot_amt", "tot_evlu_amt"]


class TestSanitizeError:
    def test_extracts_rt_cd_and_msg1(self):
        result = _sanitize_error({"rt_cd": "1", "msg1": "실패 메시지"})
        assert "rt_cd=1" in result
        assert "msg=실패 메시지" in result

    def test_missing_fields_use_default(self):
        result = _sanitize_error({})
        assert "rt_cd=N/A" in result
        assert "msg=N/A" in result

    def test_excludes_sensitive_fields(self):
        result = _sanitize_error(SENSITIVE_DATA)
        for key in SENSITIVE_KEYS:
            assert key not in result

    @pytest.mark.parametrize("bad_input", [None, "error string", ["list"], 42, True])
    def test_non_dict_input_returns_safe_default(self, bad_input):
        result = _sanitize_error(bad_input)
        assert "rt_cd=N/A" in result
        assert "msg=N/A" in result


class TestClassifyResponseSecurity:
    """_classify_response()가 전체 data dict를 예외 메시지에 포함하지 않는지 검증"""

    @pytest.mark.parametrize(
        "status,exc_type",
        [
            (429, RateLimitError),
            (401, TokenExpiredError),
            (400, FatalError),
            (403, FatalError),
            (500, RetryableError),
            (502, RetryableError),
            (418, KISAPIError),
        ],
    )
    def test_error_message_excludes_sensitive_data(self, status, exc_type):
        with pytest.raises(exc_type) as exc_info:
            _classify_response(status, SENSITIVE_DATA)

        error_msg = str(exc_info.value)
        for key in SENSITIVE_KEYS:
            assert key not in error_msg, f"Sensitive value '{key}' leaked in {status} error message"

    @pytest.mark.parametrize(
        "status,exc_type",
        [
            (429, RateLimitError),
            (401, TokenExpiredError),
            (400, FatalError),
            (500, RetryableError),
            (418, KISAPIError),
        ],
    )
    def test_error_message_contains_safe_fields(self, status, exc_type):
        with pytest.raises(exc_type) as exc_info:
            _classify_response(status, SENSITIVE_DATA)

        error_msg = str(exc_info.value)
        assert "rt_cd=1" in error_msg
        assert "msg=잔고 부족" in error_msg

    def test_success_status_returns_none(self):
        assert _classify_response(200, SENSITIVE_DATA) is None
        assert _classify_response(201, {}) is None

    def test_full_dict_not_in_message(self):
        """str(data) 패턴이 예외 메시지에 포함되지 않는지 직접 검증"""
        with pytest.raises(FatalError) as exc_info:
            _classify_response(400, SENSITIVE_DATA)

        error_msg = str(exc_info.value)
        assert "output" not in error_msg
        assert "{" not in error_msg or "rt_cd=" in error_msg
