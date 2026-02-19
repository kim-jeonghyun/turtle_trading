#!/usr/bin/env python3
"""
보안 감사 스크립트 - 시스템 시작 전 보안 상태 확인

이 스크립트는 실거래 전에 .env 파일의 권한과 필수 환경변수를 확인하여
보안 문제가 없는지 검증합니다.
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List

from src.security import (
    check_env_file_permissions,
    mask_credential,
    validate_credentials,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# 색상 코드 (터미널 출력)
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_BLUE = "\033[94m"
COLOR_RESET = "\033[0m"


def colored(text: str, color: str) -> str:
    """터미널 색상 출력"""
    return f"{color}{text}{COLOR_RESET}"


def print_header(title: str) -> None:
    """섹션 헤더 출력"""
    print(f"\n{colored('=' * 60, COLOR_BLUE)}")
    print(colored(f"  {title}", COLOR_BLUE))
    print(f"{colored('=' * 60, COLOR_BLUE)}\n")


def check_env_permissions_detailed(env_path: str = ".env") -> bool:
    """
    .env 파일 권한 상세 검사

    Args:
        env_path: .env 파일 경로

    Returns:
        권한이 안전한지 여부
    """
    is_safe, message = check_env_file_permissions(env_path)

    if is_safe:
        print(colored("✓ PASS", COLOR_GREEN), message)
    else:
        print(colored("✗ FAIL", COLOR_RED), message)

    return is_safe


def check_credentials_detailed(required_vars: List[str]) -> bool:
    """
    필수 환경변수 상세 검사

    Args:
        required_vars: 필수 환경변수명 목록

    Returns:
        모든 필수 변수가 설정되었는지 여부
    """
    all_valid, missing_vars = validate_credentials(required_vars)

    if all_valid:
        print(colored("✓ All credentials are set", COLOR_GREEN))
        # 마스킹된 값 표시
        for var_name in required_vars:
            value = os.environ.get(var_name, "")
            masked = mask_credential(value)
            print(f"  {var_name}: {masked}")
    else:
        print(colored("✗ Missing credentials", COLOR_RED))
        for var_name in missing_vars:
            print(f"  - {var_name}")

    return all_valid


def fix_env_permissions(env_path: str = ".env") -> bool:
    """
    .env 파일 권한 자동 수정

    Args:
        env_path: .env 파일 경로

    Returns:
        수정 성공 여부
    """
    env_file = Path(env_path)

    if not env_file.exists():
        print(f"  {colored('⚠', COLOR_YELLOW)} .env 파일 없음: {env_path}")
        return True

    try:
        # 600 (rw-------)으로 설정
        os.chmod(env_file, 0o600)
        current_mode = os.stat(env_file).st_mode & 0o777
        print(f"  {colored('✓ Fixed', COLOR_GREEN)} .env 권한: {oct(current_mode)}")
        return True
    except Exception as e:
        print(f"  {colored('✗ Error', COLOR_RED)} .env 권한 수정 실패: {e}")
        return False


def run_full_security_check(strict: bool = False, fix: bool = False) -> int:
    """
    전체 보안 검사 실행

    Args:
        strict: 경고도 실패로 취급할지 여부
        fix: 권한 문제 자동 수정 여부

    Returns:
        종료 코드 (0: 성공, 1: 실패)
    """
    required_credentials = [
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "KIS_ACCOUNT_NO",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]

    all_checks_passed = True

    # .env 파일 권한 검사
    print_header("Environment File Permissions")
    if fix:
        fix_env_permissions()
    if not check_env_permissions_detailed():
        all_checks_passed = False

    # 필수 자격증명 검사
    print_header("Required Credentials")
    if not check_credentials_detailed(required_credentials):
        all_checks_passed = False

    # 종합 결과
    print_header("Security Check Summary")
    if all_checks_passed:
        print(colored("✓ All security checks passed", COLOR_GREEN))
        return 0
    else:
        print(colored("✗ Some security checks failed", COLOR_RED))
        if strict:
            return 1
        else:
            print(f"  {colored('Note:', COLOR_YELLOW)} Use --strict to fail on warnings")
            return 0


def main() -> int:
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="Turtle Trading System 보안 감사",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 기본 보안 검사 실행
  python scripts/security_check.py

  # Strict 모드 (경고도 실패로 취급)
  python scripts/security_check.py --strict

  # .env 권한 자동 수정
  python scripts/security_check.py --fix

  # Strict + Fix
  python scripts/security_check.py --strict --fix
        """,
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="경고도 실패로 취급",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help=".env 권한 자동 수정",
    )

    args = parser.parse_args()

    return run_full_security_check(strict=args.strict, fix=args.fix)


if __name__ == "__main__":
    sys.exit(main())
