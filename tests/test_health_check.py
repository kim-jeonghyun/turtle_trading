"""
health_check.py 외부 API 연결 확인 단위 테스트
- check_kis_api_connection: KIS API 토큰 엔드포인트 연결 확인
- check_telegram_connection: Telegram getMe API 연결 확인
- check_yfinance_connection: yfinance SPY 데이터 조회 확인
- main() 종료 코드: 외부 API 실패가 종료 코드에 영향을 미치지 않는지 확인
"""

import json
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.health_check import (
    EXTERNAL_API_TIMEOUT_SECONDS,
    _load_env_vars,
    check_kis_api_connection,
    check_telegram_connection,
    check_yfinance_connection,
)

# ---------------------------------------------------------------------------
# Helper: fake urllib response
# ---------------------------------------------------------------------------


class FakeHTTPResponse:
    """Minimal mock for urllib.request.urlopen context manager."""

    def __init__(self, data: dict, status: int = 200):
        self._data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# _load_env_vars
# ---------------------------------------------------------------------------


class TestLoadEnvVars:
    def test_reads_env_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        monkeypatch.chdir(tmp_path)
        result = _load_env_vars()
        assert result["FOO"] == "bar"
        assert result["BAZ"] == "qux"

    def test_os_environ_overrides(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=from_file\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FOO", "from_env")
        result = _load_env_vars()
        assert result["FOO"] == "from_env"

    def test_missing_env_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _load_env_vars()
        assert result == {}

    def test_skips_comments_and_empty_lines(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nKEY=value\n")
        monkeypatch.chdir(tmp_path)
        result = _load_env_vars()
        assert "KEY" in result
        assert len(result) == 1

    def test_strips_double_quotes(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text('KEY="quoted_value"\n')
        monkeypatch.chdir(tmp_path)
        result = _load_env_vars()
        assert result["KEY"] == "quoted_value"

    def test_strips_single_quotes(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY='single_quoted'\n")
        monkeypatch.chdir(tmp_path)
        result = _load_env_vars()
        assert result["KEY"] == "single_quoted"

    def test_value_with_equals(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=abc=def=ghi\n")
        monkeypatch.chdir(tmp_path)
        result = _load_env_vars()
        assert result["SECRET"] == "abc=def=ghi"

    def test_picks_up_env_only_vars(self, tmp_path, monkeypatch):
        """os.environ에만 있고 .env에 없는 변수도 인식"""
        env_file = tmp_path / ".env"
        env_file.write_text("OTHER=val\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("KIS_APP_KEY", "from_env_only")
        result = _load_env_vars()
        assert result["KIS_APP_KEY"] == "from_env_only"


# ---------------------------------------------------------------------------
# check_kis_api_connection
# ---------------------------------------------------------------------------


class TestCheckKisApiConnection:
    def test_skip_when_no_credentials(self, tmp_path, monkeypatch):
        """KIS 설정이 없으면 스킵 (True 반환)"""
        env_file = tmp_path / ".env"
        env_file.write_text("SOME_OTHER_VAR=123\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)

        ok, msg = check_kis_api_connection()
        assert ok is True
        assert "skipped" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_reachable(self, mock_urlopen, tmp_path, monkeypatch):
        """서버 도달 성공 시 True 반환"""
        env_file = tmp_path / ".env"
        env_file.write_text("KIS_APP_KEY=test_key\nKIS_APP_SECRET=test_secret\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        ok, msg = check_kis_api_connection()
        assert ok is True
        assert "reachable" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_method_not_allowed_still_reachable(self, mock_urlopen, tmp_path, monkeypatch):
        """HEAD 요청에 대해 405 반환 시에도 서버 도달로 판정"""
        env_file = tmp_path / ".env"
        env_file.write_text("KIS_APP_KEY=test_key\nKIS_APP_SECRET=test_secret\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://test", code=405, msg="Method Not Allowed", hdrs=None, fp=BytesIO(b"")
        )

        ok, msg = check_kis_api_connection()
        assert ok is True
        assert "reachable" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen, tmp_path, monkeypatch):
        """HTTP 에러 (예: 403) 시 경고"""
        env_file = tmp_path / ".env"
        env_file.write_text("KIS_APP_KEY=test_key\nKIS_APP_SECRET=test_secret\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://test", code=403, msg="Forbidden", hdrs=None, fp=BytesIO(b"")
        )

        ok, msg = check_kis_api_connection()
        assert ok is False
        assert "HTTP 403" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_url_error_unreachable(self, mock_urlopen, tmp_path, monkeypatch):
        """네트워크 도달 불가"""
        env_file = tmp_path / ".env"
        env_file.write_text("KIS_APP_KEY=test_key\nKIS_APP_SECRET=test_secret\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        ok, msg = check_kis_api_connection()
        assert ok is False
        assert "unreachable" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen, tmp_path, monkeypatch):
        """타임아웃"""
        env_file = tmp_path / ".env"
        env_file.write_text("KIS_APP_KEY=test_key\nKIS_APP_SECRET=test_secret\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)

        mock_urlopen.side_effect = TimeoutError("timed out")

        ok, msg = check_kis_api_connection()
        assert ok is False
        assert "timeout" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_socket_timeout(self, mock_urlopen, tmp_path, monkeypatch):
        """socket.timeout (Python 3.11 호환)"""
        import socket

        env_file = tmp_path / ".env"
        env_file.write_text("KIS_APP_KEY=test_key\nKIS_APP_SECRET=test_secret\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)

        mock_urlopen.side_effect = socket.timeout("timed out")

        ok, msg = check_kis_api_connection()
        assert ok is False
        assert "timeout" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_uses_real_url_when_is_real(self, mock_urlopen, tmp_path, monkeypatch):
        """KIS_IS_REAL=True 시 실전투자 URL 사용"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "KIS_APP_KEY=test_key\nKIS_APP_SECRET=test_secret\nKIS_IS_REAL=True\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_IS_REAL", raising=False)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        check_kis_api_connection()

        # Verify the URL used contains the real API host
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        assert "openapi.koreainvestment.com" in request_obj.full_url
        assert "openapivts" not in request_obj.full_url
        assert request_obj.method == "HEAD"

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_generic_exception(self, mock_urlopen, tmp_path, monkeypatch):
        """예상치 못한 예외"""
        env_file = tmp_path / ".env"
        env_file.write_text("KIS_APP_KEY=test_key\nKIS_APP_SECRET=test_secret\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)

        mock_urlopen.side_effect = RuntimeError("unexpected")

        ok, msg = check_kis_api_connection()
        assert ok is False
        assert "error" in msg


# ---------------------------------------------------------------------------
# check_telegram_connection
# ---------------------------------------------------------------------------


class TestCheckTelegramConnection:
    def test_skip_when_no_token(self, tmp_path, monkeypatch):
        """토큰 미설정 시 스킵"""
        env_file = tmp_path / ".env"
        env_file.write_text("SOME_VAR=123\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        ok, msg = check_telegram_connection()
        assert ok is True
        assert "skipped" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_success(self, mock_urlopen, tmp_path, monkeypatch):
        """getMe 성공 시 봇 이름 표시"""
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=123:ABC\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        mock_urlopen.return_value = FakeHTTPResponse({
            "ok": True,
            "result": {"username": "test_bot"},
        })

        ok, msg = check_telegram_connection()
        assert ok is True
        assert "connected" in msg
        assert "@test_bot" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_api_returns_not_ok(self, mock_urlopen, tmp_path, monkeypatch):
        """API 응답 ok=false"""
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=123:ABC\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        mock_urlopen.return_value = FakeHTTPResponse({"ok": False})

        ok, msg = check_telegram_connection()
        assert ok is False
        assert "ok=false" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_invalid_token_401(self, mock_urlopen, tmp_path, monkeypatch):
        """잘못된 토큰 시 401"""
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=invalid\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://test", code=401, msg="Unauthorized", hdrs=None, fp=BytesIO(b"")
        )

        ok, msg = check_telegram_connection()
        assert ok is False
        assert "invalid bot token" in msg
        assert "401" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_http_error_other(self, mock_urlopen, tmp_path, monkeypatch):
        """401 이외 HTTP 에러"""
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=123:ABC\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://test", code=500, msg="Internal", hdrs=None, fp=BytesIO(b"")
        )

        ok, msg = check_telegram_connection()
        assert ok is False
        assert "HTTP 500" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_url_error(self, mock_urlopen, tmp_path, monkeypatch):
        """네트워크 도달 불가"""
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=123:ABC\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        mock_urlopen.side_effect = urllib.error.URLError("DNS failed")

        ok, msg = check_telegram_connection()
        assert ok is False
        assert "unreachable" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen, tmp_path, monkeypatch):
        """타임아웃"""
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=123:ABC\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        mock_urlopen.side_effect = TimeoutError("timed out")

        ok, msg = check_telegram_connection()
        assert ok is False
        assert "timeout" in msg

    @patch("scripts.health_check.urllib.request.urlopen")
    def test_generic_exception(self, mock_urlopen, tmp_path, monkeypatch):
        """예상치 못한 예외"""
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=123:ABC\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        mock_urlopen.side_effect = ValueError("bad data")

        ok, msg = check_telegram_connection()
        assert ok is False
        assert "error" in msg

    def test_telegram_error_does_not_leak_token(self, tmp_path, monkeypatch):
        """Telegram 에러 메시지에 봇 토큰이 노출되지 않는지 확인"""
        fake_token = "1234567890:ABCDEFfake_token_value"
        env_file = tmp_path / ".env"
        env_file.write_text(f"TELEGRAM_BOT_TOKEN={fake_token}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        # Mock urlopen to raise an exception that includes the URL (and thus the token)
        def raise_with_token(*args, **kwargs):
            raise Exception(f"Connection failed: https://api.telegram.org/bot{fake_token}/getMe")

        monkeypatch.setattr("urllib.request.urlopen", raise_with_token)
        ok, msg = check_telegram_connection()
        assert not ok
        assert fake_token not in msg  # Token must not be in output
        assert "***" in msg  # Token should be replaced


# ---------------------------------------------------------------------------
# check_yfinance_connection
# ---------------------------------------------------------------------------


class TestCheckYfinanceConnection:
    @patch("yfinance.Ticker")
    def test_success(self, mock_ticker_cls):
        """SPY 데이터 정상 반환"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame({"Close": [580.25]})
        mock_ticker_cls.return_value = mock_ticker

        ok, msg = check_yfinance_connection()
        assert ok is True
        assert "connected" in msg
        assert "580.25" in msg

    @patch("yfinance.Ticker")
    def test_empty_dataframe(self, mock_ticker_cls):
        """빈 데이터 반환"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        ok, msg = check_yfinance_connection()
        assert ok is False
        assert "no data" in msg

    @patch("yfinance.Ticker")
    def test_none_dataframe(self, mock_ticker_cls):
        """None 반환"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = None
        mock_ticker_cls.return_value = mock_ticker

        ok, msg = check_yfinance_connection()
        assert ok is False
        assert "no data" in msg

    @patch("yfinance.Ticker")
    def test_exception(self, mock_ticker_cls):
        """yfinance 예외 발생"""
        mock_ticker_cls.side_effect = Exception("network error")

        ok, msg = check_yfinance_connection()
        assert ok is False
        assert "error" in msg

    def test_import_error(self):
        """yfinance 미설치 시 스킵 (ImportError 경로)"""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "yfinance":
                raise ImportError("No module named 'yfinance'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            ok, msg = check_yfinance_connection()
            assert ok is True
            assert "skipped" in msg


# ---------------------------------------------------------------------------
# Timeout constant
# ---------------------------------------------------------------------------


class TestTimeoutConstant:
    def test_timeout_is_5_seconds(self):
        """타임아웃이 5초로 설정되어 있는지 확인"""
        assert EXTERNAL_API_TIMEOUT_SECONDS == 5


# ---------------------------------------------------------------------------
# main() exit code: external API failures do not affect exit code
# ---------------------------------------------------------------------------


class TestMainExitCode:
    @patch("scripts.health_check.check_kis_api_connection", return_value=(False, "KIS API: failed"))
    @patch("scripts.health_check.check_telegram_connection", return_value=(False, "Telegram: failed"))
    @patch("scripts.health_check.check_yfinance_connection", return_value=(False, "yfinance: failed"))
    @patch("scripts.health_check.check_data_directory", return_value=(True, "OK"))
    @patch("scripts.health_check.check_python_packages", return_value=(True, "OK"))
    @patch("scripts.health_check.check_position_files", return_value=(True, "OK"))
    @patch("scripts.health_check.check_environment_variables", return_value=(True, "OK"))
    @patch("scripts.health_check.check_data_freshness", return_value=(True, "OK"))
    @patch("scripts.health_check.check_disk_space", return_value=(True, "OK"))
    def test_external_failures_do_not_affect_exit_code(self, *mocks):
        """외부 API 전부 실패해도 core가 통과하면 exit(0)"""
        from scripts.health_check import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    @patch("scripts.health_check.check_kis_api_connection", return_value=(True, "OK"))
    @patch("scripts.health_check.check_telegram_connection", return_value=(True, "OK"))
    @patch("scripts.health_check.check_yfinance_connection", return_value=(True, "OK"))
    @patch("scripts.health_check.check_data_directory", return_value=(False, "FAIL"))
    @patch("scripts.health_check.check_python_packages", return_value=(True, "OK"))
    @patch("scripts.health_check.check_position_files", return_value=(True, "OK"))
    @patch("scripts.health_check.check_environment_variables", return_value=(True, "OK"))
    @patch("scripts.health_check.check_data_freshness", return_value=(True, "OK"))
    @patch("scripts.health_check.check_disk_space", return_value=(True, "OK"))
    def test_core_failure_causes_exit_code_1(self, *mocks):
        """core 체크 하나라도 실패하면 exit(1)"""
        from scripts.health_check import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    @patch("scripts.health_check.check_kis_api_connection", return_value=(True, "OK"))
    @patch("scripts.health_check.check_telegram_connection", return_value=(True, "OK"))
    @patch("scripts.health_check.check_yfinance_connection", return_value=(True, "OK"))
    @patch("scripts.health_check.check_data_directory", return_value=(True, "OK"))
    @patch("scripts.health_check.check_python_packages", return_value=(True, "OK"))
    @patch("scripts.health_check.check_position_files", return_value=(True, "OK"))
    @patch("scripts.health_check.check_environment_variables", return_value=(True, "OK"))
    @patch("scripts.health_check.check_data_freshness", return_value=(True, "OK"))
    @patch("scripts.health_check.check_disk_space", return_value=(True, "OK"))
    def test_all_pass_exit_code_0(self, *mocks):
        """전체 통과 시 exit(0)"""
        from scripts.health_check import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
