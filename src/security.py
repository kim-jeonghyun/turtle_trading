"""
보안 유틸리티 모듈
- Dry-run 강제화
- 환경변수 검증
- 자격증명 파일 권한 검사
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def enforce_dry_run(is_live: bool, env_var: str = "TURTLE_ALLOW_LIVE") -> bool:
    """
    실거래 여부를 강제 검증

    실거래(is_live=True)일 때, 환경변수 TURTLE_ALLOW_LIVE가 "true"로 설정되어 있는지
    확인합니다. 설정되어 있지 않으면 경고를 기록하고 False를 반환하여 dry-run 강제합니다.

    Args:
        is_live: 실거래 여부
        env_var: 확인할 환경변수명 (기본값: "TURTLE_ALLOW_LIVE")

    Returns:
        True if live trading is allowed, False if forced to dry-run
    """
    if not is_live:
        return False

    env_value = os.environ.get(env_var, "").lower()

    if env_value != "true":
        logger.warning(
            f"실거래 시도가 차단됨. 환경변수 {env_var}=true를 설정하세요. (현재값: {repr(os.environ.get(env_var))})"
        )
        return False

    logger.info(f"실거래 모드 활성화. {env_var}={env_value}")
    return True


def check_env_file_permissions(env_path: str = ".env") -> Tuple[bool, str]:
    """
    .env 파일 권한 검사

    .env 파일이 존재하는지 확인하고, 파일 권한이 600 또는 400
    (소유자만 읽기/쓰기)인지 검사합니다. macOS에서는 os.stat()을 사용합니다.

    Args:
        env_path: .env 파일 경로

    Returns:
        (is_safe: bool, message: str)
        - is_safe: 권한이 안전한지 여부
        - message: 상태 메시지
    """
    env_file = Path(env_path)

    if not env_file.exists():
        return True, f".env 파일 없음: {env_path}"

    try:
        # macOS: os.stat().st_mode에서 권한 추출
        stat_info = os.stat(env_file)
        file_mode = stat_info.st_mode & 0o777

        # 안전한 권한: 600 (rw-------) 또는 400 (r--------)
        safe_permissions = {0o600, 0o400}

        if file_mode in safe_permissions:
            return True, f".env 권한 안전: {oct(file_mode)}"
        else:
            return False, (
                f".env 권한 위험: {oct(file_mode)} (안전한 권한: 0600, 0400). chmod 600 {env_path} 실행 필요"
            )
    except Exception as e:
        return False, f".env 권한 검사 실패: {e}"


def validate_credentials(required_vars: List[str]) -> Tuple[bool, List[str]]:
    """
    필수 환경변수 검증

    모든 필수 환경변수가 설정되어 있고 비어있지 않은지 확인합니다.

    Args:
        required_vars: 필수 환경변수명 목록
        예: ["KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO",
             "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]

    Returns:
        (all_valid: bool, missing_vars: list[str])
        - all_valid: 모든 필수 변수가 설정되었는지 여부
        - missing_vars: 설정되지 않은 변수 목록
    """
    missing_vars = []

    for var_name in required_vars:
        value = os.environ.get(var_name, "").strip()
        if not value:
            missing_vars.append(var_name)

    all_valid = len(missing_vars) == 0

    return all_valid, missing_vars


def mask_credential(value: str, visible_chars: int = 4) -> str:
    """
    자격증명 마스킹

    자격증명 값의 처음 visible_chars개 문자만 표시하고 나머지는 *로 마스킹합니다.
    값이 비어있거나 None이면 "[NOT SET]"을 반환합니다.

    Args:
        value: 마스킹할 자격증명 값
        visible_chars: 표시할 문자 수 (기본값: 4)

    Returns:
        마스킹된 문자열
        예: "abc123secret" → "abc1********"
        예: "" → "[NOT SET]"
        예: None → "[NOT SET]"
    """
    if not value:
        return "[NOT SET]"

    if len(value) <= visible_chars:
        return "*" * len(value)

    visible_part = value[:visible_chars]
    masked_part = "*" * (len(value) - visible_chars)

    return visible_part + masked_part


def run_security_check() -> Dict[str, Any]:
    """
    전체 보안 검사 실행

    모든 보안 검사(env 파일 권한, 필수 자격증명)를 실행하고
    결과를 요약한 딕셔너리를 반환합니다.

    Returns:
        {
            "env_permissions": {
                "is_safe": bool,
                "message": str
            },
            "credentials": {
                "all_valid": bool,
                "missing_vars": list[str]
            },
            "live_trading": {
                "allowed": bool,
                "env_var_name": str
            }
        }
    """
    required_credentials = [
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "KIS_ACCOUNT_NO",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]

    # 환경 파일 권한 검사
    is_safe, perm_message = check_env_file_permissions()

    # 필수 자격증명 검사
    creds_valid, missing_vars = validate_credentials(required_credentials)

    # 실거래 허용 여부 (환경변수에서 직접 읽기)
    env_value = os.environ.get("TURTLE_ALLOW_LIVE", "").lower()
    is_live_allowed = env_value == "true"

    return {
        "env_permissions": {
            "is_safe": is_safe,
            "message": perm_message,
        },
        "credentials": {
            "all_valid": creds_valid,
            "missing_vars": missing_vars,
        },
        "live_trading": {
            "allowed": is_live_allowed,
            "env_var_name": "TURTLE_ALLOW_LIVE",
        },
    }
