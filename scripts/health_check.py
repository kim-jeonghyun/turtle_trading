#!/usr/bin/env python3
"""
Turtle Trading System Health Check
시스템 상태를 검증하고 문제점을 보고합니다.
"""

import json
import logging
import os
import shutil
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

# 외부 API 연결 확인 타임아웃 (초)
EXTERNAL_API_TIMEOUT_SECONDS = 5


def check_data_directory() -> Tuple[bool, str]:
    """데이터 디렉토리 존재 및 쓰기 가능 여부 확인"""
    base_dir = Path("data")
    required_dirs = ["positions", "entries", "cache", "signals", "trades"]

    if not base_dir.exists():
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            return True, f"Data directory: {base_dir}/ (created)"
        except Exception as e:
            return False, f"Data directory: Cannot create - {e}"

    # 쓰기 권한 확인
    try:
        test_file = base_dir / ".write_test"
        test_file.touch()
        test_file.unlink()

        # 필수 하위 디렉토리 확인
        missing = []
        for d in required_dirs:
            subdir = base_dir / d
            if not subdir.exists():
                subdir.mkdir(parents=True, exist_ok=True)
                missing.append(d)

        if missing:
            return True, f"Data directory: {base_dir}/ (created subdirs: {', '.join(missing)})"
        return True, f"Data directory: {base_dir}/"
    except Exception as e:
        return False, f"Data directory: Not writable - {e}"


def check_python_packages() -> Tuple[bool, str]:
    """필수 Python 패키지 import 가능 여부 확인"""
    required_packages = ["pandas", "numpy", "yfinance", "FinanceDataReader"]
    missing = []

    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        return False, f"Python packages: Missing - {', '.join(missing)}"
    return True, f"Python packages: {', '.join(required_packages)}"


def check_position_files() -> Tuple[bool, str]:
    """포지션 파일 JSON 유효성 확인"""
    positions_file = Path("data/positions/positions.json")

    if not positions_file.exists():
        # 파일이 없으면 생성
        try:
            positions_file.parent.mkdir(parents=True, exist_ok=True)
            with open(positions_file, "w") as f:
                json.dump([], f)
            return True, "Position file: valid (initialized empty)"
        except Exception as e:
            return False, f"Position file: Cannot create - {e}"

    try:
        with open(positions_file, "r") as f:
            data = json.load(f)

        if not isinstance(data, list):
            return False, "Position file: Invalid format (not a list)"

        open_positions = [p for p in data if p.get("status") == "open"]
        return True, f"Position file: valid ({len(open_positions)} open positions)"
    except json.JSONDecodeError as e:
        return False, f"Position file: Invalid JSON - {e}"
    except Exception as e:
        return False, f"Position file: Error - {e}"


def check_environment_variables() -> Tuple[bool, str]:
    """환경 변수 설정 확인"""
    env_file = Path(".env")
    warnings = []

    if not env_file.exists():
        return False, "Environment: .env file not found"

    # .env 파일 파싱
    env_vars = {}
    try:
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key.strip()] = value.strip()
    except Exception as e:
        return False, f"Environment: Cannot read .env - {e}"

    # 필수 변수 확인
    required = {"TELEGRAM_BOT_TOKEN": "Telegram bot token", "TELEGRAM_CHAT_ID": "Telegram chat ID"}

    for var, desc in required.items():
        if var not in env_vars or not env_vars[var]:
            warnings.append(f"{desc} not set")

    if warnings:
        return False, f"Environment: {', '.join(warnings)}"

    return True, "Environment: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"


def check_data_freshness() -> Tuple[bool, str]:
    """최근 데이터 업데이트 확인 (캐시 파일)"""
    cache_dir = Path("data/cache")

    if not cache_dir.exists():
        return True, "Data freshness: no cache yet (OK for new install)"

    parquet_files = list(cache_dir.glob("*.parquet"))

    if not parquet_files:
        return True, "Data freshness: no cache yet (OK for new install)"

    # 가장 최근 파일 찾기
    latest_file = max(parquet_files, key=lambda p: p.stat().st_mtime)
    latest_time = datetime.fromtimestamp(latest_file.stat().st_mtime)
    age = datetime.now() - latest_time

    if age > timedelta(days=7):
        return False, f"Data freshness: last update {age.days} days ago (stale)"

    # 사람이 읽기 쉬운 형식으로 변환
    if age.total_seconds() < 3600:
        age_str = f"{int(age.total_seconds() / 60)}m ago"
    elif age.total_seconds() < 86400:
        age_str = f"{int(age.total_seconds() / 3600)}h ago"
    else:
        age_str = f"{age.days}d ago"

    return True, f"Data freshness: last update {age_str}"


def check_disk_space() -> Tuple[bool, str]:
    """디스크 공간 확인"""
    try:
        stat = shutil.disk_usage(".")
        free_gb = stat.free / (1024**3)

        if free_gb < 1:
            return False, f"Disk space: {free_gb:.2f}GB free (low!)"

        return True, f"Disk space: {free_gb:.1f}GB free"
    except Exception as e:
        return False, f"Disk space: Cannot check - {e}"


def _load_env_vars() -> dict:
    """Load environment variables from .env file (does not override os.environ)."""
    env_vars: dict = {}
    env_file = Path(".env")
    if env_file.exists():
        try:
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        value = value.strip()
                        # Strip surrounding quotes (single or double)
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                            value = value[1:-1]
                        env_vars[key.strip()] = value
        except Exception as e:
            logger.warning("Failed to read .env file: %s", e)
    # os.environ takes precedence
    for key in list(env_vars.keys()):
        if key in os.environ:
            env_vars[key] = os.environ[key]
    # Also pick up common keys from os.environ that may not be in .env
    _KNOWN_KEYS = (
        "KIS_APP_KEY", "KIS_APP_SECRET", "KIS_IS_REAL",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    )
    for key in _KNOWN_KEYS:
        if key not in env_vars and key in os.environ:
            env_vars[key] = os.environ[key]
    return env_vars


def check_kis_api_connection() -> Tuple[bool, str]:
    """KIS API 서버 도달 가능성 확인

    실제 토큰 발급은 시도하지 않고, 서버 도달 가능 여부만 확인합니다.
    환경변수에 KIS 설정이 없으면 스킵합니다.
    """
    env = _load_env_vars()
    app_key = env.get("KIS_APP_KEY", "")
    app_secret = env.get("KIS_APP_SECRET", "")

    if not app_key or not app_secret:
        return True, "KIS API: skipped (credentials not configured)"

    is_real = env.get("KIS_IS_REAL", "false").lower() == "true"
    if is_real:
        base_url = "https://openapi.koreainvestment.com:9443"
    else:
        base_url = "https://openapivts.koreainvestment.com:29443"

    url = f"{base_url}/oauth2/tokenP"

    try:
        # HEAD 요청으로 서버 도달 가능성만 확인 (토큰 발급 없이)
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=EXTERNAL_API_TIMEOUT_SECONDS) as resp:
            return True, f"KIS API: reachable (HTTP {resp.status})"
    except urllib.error.HTTPError as e:
        # 405 Method Not Allowed 또는 400 Bad Request는 서버 도달 성공
        if e.code in (405, 400, 404):
            return True, f"KIS API: reachable (HTTP {e.code})"
        return False, f"KIS API: HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"KIS API: unreachable ({e.reason})"
    except (TimeoutError, socket.timeout):
        return False, f"KIS API: timeout (>{EXTERNAL_API_TIMEOUT_SECONDS}s)"
    except Exception as e:
        return False, f"KIS API: error ({e})"


def check_telegram_connection() -> Tuple[bool, str]:
    """Telegram Bot API getMe 호출로 연결 확인

    환경변수에 TELEGRAM_BOT_TOKEN이 없으면 스킵합니다.
    """
    env = _load_env_vars()
    bot_token = env.get("TELEGRAM_BOT_TOKEN", "")

    if not bot_token:
        return True, "Telegram: skipped (token not configured)"

    url = f"https://api.telegram.org/bot{bot_token}/getMe"

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=EXTERNAL_API_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                bot_name = data.get("result", {}).get("username", "unknown")
                return True, f"Telegram: connected (@{bot_name})"
            return False, "Telegram: API returned ok=false"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Telegram: invalid bot token (401)"
        return False, f"Telegram: HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"Telegram: unreachable ({e.reason})"
    except (TimeoutError, socket.timeout):
        return False, f"Telegram: timeout (>{EXTERNAL_API_TIMEOUT_SECONDS}s)"
    except Exception as e:
        return False, f"Telegram: error ({e})"


def check_yfinance_connection() -> Tuple[bool, str]:
    """yfinance로 SPY 1일 데이터를 조회하여 연결 확인"""
    try:
        import yfinance as yf

        ticker = yf.Ticker("SPY")
        df = ticker.history(period="1d")

        if df is not None and not df.empty:
            last_close = df["Close"].iloc[-1]
            return True, f"yfinance: connected (SPY last={last_close:.2f})"
        return False, "yfinance: no data returned for SPY"
    except ImportError:
        return True, "yfinance: skipped (package not installed)"
    except Exception as e:
        return False, f"yfinance: error ({e})"


def main():
    """전체 헬스 체크 실행"""
    print("=== Turtle Trading System Health Check ===")
    print()

    # 필수 체크 (실패 시 종료 코드 1)
    core_checks = [
        ("Data Directory", check_data_directory),
        ("Python Packages", check_python_packages),
        ("Position Files", check_position_files),
        ("Environment", check_environment_variables),
        ("Data Freshness", check_data_freshness),
        ("Disk Space", check_disk_space),
    ]

    # 외부 API 체크 (실패해도 경고만, 종료 코드에 영향 없음)
    external_checks = [
        ("KIS API", check_kis_api_connection),
        ("Telegram", check_telegram_connection),
        ("yfinance", check_yfinance_connection),
    ]

    core_results = []
    for name, check_func in core_checks:
        ok, msg = check_func()
        status = "[OK]  " if ok else "[WARN]"
        print(f"{status} {msg}")
        core_results.append(ok)

    print()
    print("--- External API Connectivity ---")
    external_results = []
    for name, check_func in external_checks:
        ok, msg = check_func()
        status = "[OK]  " if ok else "[WARN]"
        print(f"{status} {msg}")
        external_results.append(ok)

    print()
    core_passed = sum(core_results)
    core_total = len(core_results)
    ext_passed = sum(external_results)
    ext_total = len(external_results)
    print(f"=== Core: {core_passed}/{core_total} passed | External: {ext_passed}/{ext_total} passed ===")

    # 종료 코드는 핵심 체크만 기준 (외부 API 실패는 경고만)
    sys.exit(0 if core_passed == core_total else 1)


if __name__ == "__main__":
    main()
