#!/usr/bin/env python3
"""
Turtle Trading System Health Check
시스템 상태를 검증하고 문제점을 보고합니다.
"""

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple


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


def main():
    """전체 헬스 체크 실행"""
    print("=== Turtle Trading System Health Check ===")
    print()

    checks = [
        ("Data Directory", check_data_directory),
        ("Python Packages", check_python_packages),
        ("Position Files", check_position_files),
        ("Environment", check_environment_variables),
        ("Data Freshness", check_data_freshness),
        ("Disk Space", check_disk_space),
    ]

    results = []
    for name, check_func in checks:
        ok, msg = check_func()
        status = "[OK]  " if ok else "[WARN]"
        print(f"{status} {msg}")
        results.append(ok)

    print()
    passed = sum(results)
    total = len(results)
    print(f"=== {passed}/{total} checks passed ===")

    # 실패가 있으면 종료 코드 1 반환 (스크립트 자동화용)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
