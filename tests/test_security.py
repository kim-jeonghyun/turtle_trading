"""
src/security.py 단위 테스트

보안 검증 로직 테스트:
- Dry-run 강제화
- 환경파일 권한 검사
- 자격증명 검증
- 자격증명 마스킹
"""

import sys
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.security import (
    enforce_dry_run,
    check_env_file_permissions,
    validate_credentials,
    mask_credential,
    run_security_check,
)


class TestDryRunEnforcement:
    """실거래 강제 검증 테스트"""

    def test_live_blocked_without_env(self):
        """is_live=True이지만 환경변수 없음 -> False 반환"""
        with patch.dict(os.environ, {}, clear=True):
            result = enforce_dry_run(is_live=True)
            assert result is False

    def test_live_blocked_with_false_env(self):
        """is_live=True이고 TURTLE_ALLOW_LIVE=false -> False 반환"""
        with patch.dict(os.environ, {"TURTLE_ALLOW_LIVE": "false"}):
            result = enforce_dry_run(is_live=True)
            assert result is False

    def test_live_allowed_with_env(self):
        """is_live=True이고 TURTLE_ALLOW_LIVE=true -> True 반환"""
        with patch.dict(os.environ, {"TURTLE_ALLOW_LIVE": "true"}):
            result = enforce_dry_run(is_live=True)
            assert result is True

    def test_live_allowed_with_env_uppercase(self):
        """is_live=True이고 TURTLE_ALLOW_LIVE=TRUE -> True 반환 (대소문자 무시)"""
        with patch.dict(os.environ, {"TURTLE_ALLOW_LIVE": "TRUE"}):
            result = enforce_dry_run(is_live=True)
            assert result is True

    def test_dry_run_always_false(self):
        """is_live=False는 환경변수 관계없이 항상 False"""
        with patch.dict(os.environ, {"TURTLE_ALLOW_LIVE": "true"}):
            result = enforce_dry_run(is_live=False)
            assert result is False

    def test_dry_run_always_false_no_env(self):
        """is_live=False는 환경변수 없을 때도 False"""
        with patch.dict(os.environ, {}, clear=True):
            result = enforce_dry_run(is_live=False)
            assert result is False

    def test_custom_env_var_name(self):
        """커스텀 환경변수명 사용"""
        with patch.dict(os.environ, {"CUSTOM_VAR": "true"}):
            result = enforce_dry_run(is_live=True, env_var="CUSTOM_VAR")
            assert result is True

        with patch.dict(os.environ, {"CUSTOM_VAR": "false"}):
            result = enforce_dry_run(is_live=True, env_var="CUSTOM_VAR")
            assert result is False


class TestEnvFilePermissions:
    """환경파일 권한 검사 테스트"""

    def test_missing_file(self):
        """파일 없음 -> 안전한 상태로 간주"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            is_safe, message = check_env_file_permissions(env_path)
            assert is_safe is True
            assert ".env 파일 없음" in message

    def test_safe_permissions_600(self):
        """파일 권한 600 (rw-------) -> 안전"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            Path(env_path).write_text("TEST=value")
            os.chmod(env_path, 0o600)

            is_safe, message = check_env_file_permissions(env_path)
            assert is_safe is True
            assert "0o600" in message

    def test_safe_permissions_400(self):
        """파일 권한 400 (r--------) -> 안전"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            Path(env_path).write_text("TEST=value")
            os.chmod(env_path, 0o400)

            is_safe, message = check_env_file_permissions(env_path)
            assert is_safe is True
            assert "0o400" in message

    def test_unsafe_permissions_644(self):
        """파일 권한 644 (rw-r--r--) -> 위험"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            Path(env_path).write_text("TEST=value")
            os.chmod(env_path, 0o644)

            is_safe, message = check_env_file_permissions(env_path)
            assert is_safe is False
            assert "위험" in message or "danger" in message.lower()
            assert "chmod 600" in message

    def test_unsafe_permissions_666(self):
        """파일 권한 666 (rw-rw-rw-) -> 위험"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            Path(env_path).write_text("TEST=value")
            os.chmod(env_path, 0o666)

            is_safe, message = check_env_file_permissions(env_path)
            assert is_safe is False
            assert "위험" in message

    def test_custom_env_path(self):
        """커스텀 .env 경로"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, "custom.env")
            Path(env_path).write_text("TEST=value")
            os.chmod(env_path, 0o600)

            is_safe, message = check_env_file_permissions(env_path)
            assert is_safe is True


class TestCredentialValidation:
    """자격증명 검증 테스트"""

    def test_all_credentials_present(self):
        """모든 필수 자격증명 설정됨"""
        env_vars = {
            "API_KEY": "secret123",
            "API_SECRET": "secret456",
            "TOKEN": "token789",
        }
        with patch.dict(os.environ, env_vars):
            all_valid, missing = validate_credentials(list(env_vars.keys()))
            assert all_valid is True
            assert missing == []

    def test_missing_single_credential(self):
        """하나의 자격증명 누락"""
        env_vars = {
            "API_KEY": "secret123",
            "API_SECRET": "secret456",
        }
        required = ["API_KEY", "API_SECRET", "TOKEN"]

        with patch.dict(os.environ, env_vars, clear=True):
            all_valid, missing = validate_credentials(required)
            assert all_valid is False
            assert "TOKEN" in missing

    def test_missing_multiple_credentials(self):
        """여러 자격증명 누락"""
        env_vars = {"API_KEY": "secret123"}
        required = ["API_KEY", "API_SECRET", "TOKEN", "CHAT_ID"]

        with patch.dict(os.environ, env_vars, clear=True):
            all_valid, missing = validate_credentials(required)
            assert all_valid is False
            assert len(missing) == 3
            assert "API_SECRET" in missing
            assert "TOKEN" in missing
            assert "CHAT_ID" in missing

    def test_empty_credential_is_invalid(self):
        """빈 문자열은 설정되지 않은 것으로 간주"""
        env_vars = {
            "API_KEY": "",
            "API_SECRET": "secret456",
        }
        required = ["API_KEY", "API_SECRET"]

        with patch.dict(os.environ, env_vars, clear=True):
            all_valid, missing = validate_credentials(required)
            assert all_valid is False
            assert "API_KEY" in missing

    def test_whitespace_only_is_invalid(self):
        """공백만 있는 문자열은 설정되지 않은 것으로 간주"""
        env_vars = {
            "API_KEY": "   ",
            "API_SECRET": "secret456",
        }
        required = ["API_KEY", "API_SECRET"]

        with patch.dict(os.environ, env_vars, clear=True):
            all_valid, missing = validate_credentials(required)
            assert all_valid is False
            assert "API_KEY" in missing

    def test_empty_required_list(self):
        """필수 항목 없음"""
        with patch.dict(os.environ, {}, clear=True):
            all_valid, missing = validate_credentials([])
            assert all_valid is True
            assert missing == []


class TestMaskCredential:
    """자격증명 마스킹 테스트"""

    def test_masks_correctly(self):
        """일반적인 마스킹: 처음 4자만 표시"""
        result = mask_credential("abc123secret")
        assert result == "abc1" + "*" * 8

    def test_masks_with_custom_visible_chars(self):
        """커스텀 표시 문자 수"""
        result = mask_credential("abcdefgh", visible_chars=2)
        assert result == "ab" + "*" * 6

    def test_empty_string_returns_not_set(self):
        """빈 문자열 -> [NOT SET]"""
        result = mask_credential("")
        assert result == "[NOT SET]"

    def test_none_returns_not_set(self):
        """None -> [NOT SET]"""
        result = mask_credential(None)
        assert result == "[NOT SET]"

    def test_short_value_fully_masked(self):
        """짧은 값 -> 모두 마스킹"""
        result = mask_credential("ab")
        assert result == "**"

    def test_exact_visible_chars_length(self):
        """정확히 visible_chars 길이의 값"""
        result = mask_credential("abcd")
        assert result == "****"

    def test_one_char_longer_than_visible(self):
        """visible_chars + 1"""
        result = mask_credential("abcde")
        assert result == "abcd*"

    def test_very_long_credential(self):
        """매우 긴 자격증명"""
        long_cred = "a" * 100
        result = mask_credential(long_cred, visible_chars=4)
        assert result == "aaaa" + "*" * 96

    def test_special_characters(self):
        """특수 문자 포함"""
        result = mask_credential("abc$%^&secret")
        assert result == "abc$" + "*" * 9


class TestRunSecurityCheck:
    """전체 보안 검사 테스트"""

    def test_returns_dict_structure(self):
        """반환값이 올바른 구조"""
        result = run_security_check()

        assert isinstance(result, dict)
        assert "env_permissions" in result
        assert "credentials" in result
        assert "live_trading" in result

        # env_permissions 구조
        assert "is_safe" in result["env_permissions"]
        assert "message" in result["env_permissions"]

        # credentials 구조
        assert "all_valid" in result["credentials"]
        assert "missing_vars" in result["credentials"]

        # live_trading 구조
        assert "allowed" in result["live_trading"]
        assert "env_var_name" in result["live_trading"]

    def test_check_with_all_credentials_set(self):
        """모든 자격증명 설정됨"""
        creds = {
            "KIS_APP_KEY": "key123",
            "KIS_APP_SECRET": "secret456",
            "KIS_ACCOUNT_NO": "account789",
            "TELEGRAM_BOT_TOKEN": "token111",
            "TELEGRAM_CHAT_ID": "chat222",
        }
        with patch.dict(os.environ, creds):
            result = run_security_check()
            assert result["credentials"]["all_valid"] is True
            assert result["credentials"]["missing_vars"] == []

    def test_check_with_missing_credentials(self):
        """일부 자격증명 누락"""
        creds = {
            "KIS_APP_KEY": "key123",
            "KIS_APP_SECRET": "secret456",
        }
        with patch.dict(os.environ, creds, clear=True):
            result = run_security_check()
            assert result["credentials"]["all_valid"] is False
            assert len(result["credentials"]["missing_vars"]) > 0
            assert "KIS_ACCOUNT_NO" in result["credentials"]["missing_vars"]

    def test_env_permissions_check(self):
        """환경 파일 권한 검사 통합"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            Path(env_path).write_text("TEST=value")
            os.chmod(env_path, 0o600)

            # 현재 디렉토리를 임시 디렉토리로 변경하여 테스트
            with patch("builtins.open", create=True):
                result = run_security_check()
                # 실제 .env 파일이 있으면 검사 수행
                assert "is_safe" in result["env_permissions"]

    def test_live_trading_always_not_allowed_in_check(self):
        """run_security_check에서 live_trading은 항상 False"""
        result = run_security_check()
        # run_security_check는 is_live=False로 호출하므로 항상 False
        assert result["live_trading"]["allowed"] is False
