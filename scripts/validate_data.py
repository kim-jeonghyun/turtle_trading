#!/usr/bin/env python3
"""
Turtle Trading Data Validation
데이터 무결성 검증 및 자동 수정 스크립트
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple

import pandas as pd

from src.data_store import ParquetDataStore
from src.utils import atomic_write_json, safe_load_json, validate_position_schema

logger = logging.getLogger(__name__)


class DataValidator:
    """데이터 검증기"""

    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate_position_json(self, fix: bool = False) -> Tuple[bool, str]:
        """포지션 JSON 검증"""
        positions_file = self.base_dir / "positions" / "positions.json"

        if not positions_file.exists():
            return True, "Positions: file not found (OK for new install)"

        data = safe_load_json(positions_file, default=None)

        if data is None:
            self.errors.append("Positions file is corrupted")
            return False, "Positions: corrupted (check backups)"

        if not isinstance(data, list):
            self.errors.append("Positions file is not a list")
            return False, "Positions: invalid format (not a list)"

        # 스키마 검증
        valid_count = 0
        invalid_positions = []

        for i, pos in enumerate(data):
            if validate_position_schema(pos):
                valid_count += 1
            else:
                invalid_positions.append(i)
                self.errors.append(f"Position {i} has invalid schema: {pos.get('position_id', 'unknown')}")

        if invalid_positions:
            if fix:
                # 유효한 포지션만 유지
                fixed_data = [p for i, p in enumerate(data) if i not in invalid_positions]
                atomic_write_json(positions_file, fixed_data)
                return True, f"Positions: {valid_count} records, {len(invalid_positions)} invalid removed"
            return False, f"Positions: {valid_count} valid, {len(invalid_positions)} invalid"

        return True, f"Positions: {valid_count} records, all valid"

    def validate_entries_json(self, fix: bool = False) -> Tuple[bool, str]:
        """진입 기록 JSON 검증"""
        entries_file = self.base_dir / "entries" / "entries.json"

        if not entries_file.exists():
            return True, "Entries: file not found (OK for new install)"

        data = safe_load_json(entries_file, default=None)

        if data is None:
            self.errors.append("Entries file is corrupted")
            return False, "Entries: corrupted (check backups)"

        if not isinstance(data, list):
            self.errors.append("Entries file is not a list")
            return False, "Entries: invalid format (not a list)"

        # 필수 필드 검증
        required_fields = ["entry_id", "position_id", "entry_date", "entry_price", "shares"]
        valid_count = 0
        invalid_entries = []

        for i, entry in enumerate(data):
            if all(f in entry for f in required_fields):
                valid_count += 1
            else:
                invalid_entries.append(i)
                self.errors.append(f"Entry {i} missing required fields: {entry.get('entry_id', 'unknown')}")

        if invalid_entries:
            if fix:
                fixed_data = [e for i, e in enumerate(data) if i not in invalid_entries]
                atomic_write_json(entries_file, fixed_data)
                return True, f"Entries: {valid_count} records, {len(invalid_entries)} invalid removed"
            return False, f"Entries: {valid_count} valid, {len(invalid_entries)} invalid"

        return True, f"Entries: {valid_count} records, all valid"

    def validate_parquet_files(self) -> Tuple[bool, str]:
        """Parquet 파일 읽기 가능 여부 확인"""
        cache_dir = self.base_dir / "cache"

        if not cache_dir.exists():
            return True, "Cache: no files (OK for new install)"

        parquet_files = list(cache_dir.glob("*.parquet"))

        if not parquet_files:
            return True, "Cache: no files (OK for new install)"

        readable_count = 0
        stale_count = 0
        corrupted = []

        for pf in parquet_files:
            try:
                pd.read_parquet(pf)
                readable_count += 1

                # 30일 이상 오래된 파일 체크
                age_days = (datetime.now() - datetime.fromtimestamp(pf.stat().st_mtime)).days
                if age_days > 30:
                    stale_count += 1
                    self.warnings.append(f"Stale cache file: {pf.name} ({age_days} days old)")

            except Exception as e:
                corrupted.append(pf.name)
                self.errors.append(f"Cannot read parquet: {pf.name} - {e}")

        if corrupted:
            return False, f"Cache: {readable_count} readable, {len(corrupted)} corrupted"

        if stale_count > 0:
            self.warnings.append(f"{stale_count} stale cache files (> 30 days)")
            return True, f"Cache: {readable_count} files, {stale_count} stale (> 30 days)"

        return True, f"Cache: {readable_count} files, all readable"

    def validate_data_consistency(self, fix: bool = False) -> Tuple[bool, str]:
        """데이터 일관성 검증"""
        positions_file = self.base_dir / "positions" / "positions.json"

        if not positions_file.exists():
            return True, "Consistency: no data to check"

        data = safe_load_json(positions_file, default=[])

        # 중복 position_id 확인
        position_ids = [p.get("position_id") for p in data if "position_id" in p]
        duplicates = [pid for pid in set(position_ids) if position_ids.count(pid) > 1]

        if duplicates:
            self.errors.append(f"Duplicate position IDs: {', '.join(duplicates)}")

            if fix:
                # 가장 최근 업데이트만 유지
                seen = {}
                unique_data: list[dict] = []
                for p in reversed(data):  # 역순으로 처리하여 최신 것 우선
                    pid = p.get("position_id")
                    if pid and pid not in seen:
                        seen[pid] = True
                        unique_data.insert(0, p)

                atomic_write_json(positions_file, unique_data)
                return True, f"Consistency: {len(duplicates)} duplicates removed"

            return False, f"Consistency: {len(duplicates)} duplicate position IDs found"

        return True, "Consistency: no duplicate position IDs"

    def validate_date_range(self) -> Tuple[bool, str]:
        """날짜 범위 검증 (미래 날짜 없는지)"""
        positions_file = self.base_dir / "positions" / "positions.json"

        if not positions_file.exists():
            return True, "Date range: no data to check"

        data = safe_load_json(positions_file, default=[])
        today = datetime.now().date()
        future_dates = []

        for p in data:
            for date_field in ["entry_date", "exit_date"]:
                date_str = p.get(date_field)
                if date_str:
                    try:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                        if date_obj > today:
                            future_dates.append(f"{p.get('position_id', 'unknown')} {date_field}: {date_str}")
                    except ValueError:
                        self.errors.append(f"Invalid date format: {date_str} in {p.get('position_id', 'unknown')}")

        if future_dates:
            for fd in future_dates:
                self.errors.append(f"Future date: {fd}")
            return False, f"Date range: {len(future_dates)} future dates found"

        return True, "Date range: all dates valid"

    def validate_price_sanity(self) -> Tuple[bool, str]:
        """가격 정상성 검증 (음수, 극단값)"""
        positions_file = self.base_dir / "positions" / "positions.json"

        if not positions_file.exists():
            return True, "Price sanity: no data to check"

        data = safe_load_json(positions_file, default=[])
        issues = []

        for p in data:
            position_id = p.get("position_id", "unknown")

            # 음수 가격 체크
            for price_field in ["entry_price", "exit_price", "stop_loss"]:
                price = p.get(price_field)
                if price is not None and price < 0:
                    issues.append(f"{position_id} {price_field}: negative ({price})")

            # 극단값 체크 (진입가 대비 10배 이상)
            entry_price = p.get("entry_price")
            exit_price = p.get("exit_price")

            if entry_price and exit_price and entry_price > 0:
                ratio = exit_price / entry_price
                if ratio > 10 or ratio < 0.1:
                    issues.append(f"{position_id} extreme price move: {ratio:.2f}x")

        if issues:
            for issue in issues:
                self.errors.append(f"Price issue: {issue}")
            return False, f"Price sanity: {len(issues)} issues found"

        return True, "Price sanity: all prices valid"


def validate_ohlcv_consistency(df: pd.DataFrame, symbol: str) -> list[str]:
    """OHLCV 논리 일관성 검증.

    Args:
        df: OHLCV DataFrame (columns: high, low, close, open, volume)
        symbol: 종목 코드

    Returns:
        이슈 메시지 리스트 (빈 리스트 = 정상)
    """
    issues = []

    # 1. high >= low
    bad_hl = df[df["high"] < df["low"]]
    if not bad_hl.empty:
        issues.append(f"{symbol}: high < low ({len(bad_hl)}건) — {bad_hl.index.tolist()[:3]}")

    # 2. high >= close and high >= open
    bad_hc = df[(df["high"] < df["close"]) | (df["high"] < df["open"])]
    if not bad_hc.empty:
        issues.append(f"{symbol}: high < close/open ({len(bad_hc)}건)")

    # 3. low <= close and low <= open
    bad_lc = df[(df["low"] > df["close"]) | (df["low"] > df["open"])]
    if not bad_lc.empty:
        issues.append(f"{symbol}: low > close/open ({len(bad_lc)}건)")

    # 4. 음수 거래량
    bad_vol = df[df["volume"] < 0]
    if not bad_vol.empty:
        issues.append(f"{symbol}: 음수 거래량 ({len(bad_vol)}건)")

    return issues


def validate_ohlcv_date_gaps(df: pd.DataFrame, symbol: str, market: str = "KR") -> list[str]:
    """거래일 갭 감지 (주말/공휴일 제외).

    단순 역일(calendar days) 기준. 연말/설 연휴(최대 4-5일)를 고려하여
    6일 이상을 이상 갭으로 판단. market_calendar.py 활용한 정밀 판단은 v3.8.0 검토.
    주의: 월~월 사이 1일 공휴일 = 역일 7일이므로 5일 기준은 false positive 발생 가능.

    Args:
        df: OHLCV DataFrame (columns: date)
        symbol: 종목 코드
        market: 시장 코드 (향후 확장용)

    Returns:
        이슈 메시지 리스트 (빈 리스트 = 정상)
    """
    issues = []
    if len(df) < 2:
        return issues

    dates = pd.to_datetime(df["date"]).sort_values()
    for i in range(1, len(dates)):
        gap = (dates.iloc[i] - dates.iloc[i - 1]).days
        if gap > 6:  # 역일 6일 이상 = 공휴일 포함 주말 대비 여유
            issues.append(f"{symbol}: {gap}일 갭 ({dates.iloc[i - 1].date()} -> {dates.iloc[i].date()})")

    return issues


def validate_ohlcv_outliers(df: pd.DataFrame, symbol: str, threshold: float = 0.31) -> list[str]:
    """가격 이상치 감지 (전일 대비 +/-threshold 변동).

    한국 시장 가격제한폭 +/-30%이므로 threshold=0.31로 설정.
    정확히 30.00% 변동(상한가/하한가)은 정상 범위로 처리.

    Args:
        df: OHLCV DataFrame (columns: date, close)
        symbol: 종목 코드
        threshold: 이상치 판단 기준 (기본 0.31 = 31%)

    Returns:
        이슈 메시지 리스트 (빈 리스트 = 정상)
    """
    issues = []
    if len(df) < 2:
        return issues

    closes = df["close"].values
    for i in range(1, len(closes)):
        if closes[i - 1] == 0:
            continue
        change = abs(closes[i] - closes[i - 1]) / closes[i - 1]
        if change > threshold:
            date = df["date"].iloc[i]
            issues.append(f"{symbol}: {date} 가격 변동 {change:.1%} ({closes[i - 1]:.0f} -> {closes[i]:.0f})")

    return issues


def validate_ohlcv_data(base_dir: str = "data") -> Tuple[bool, str]:
    """축적된 OHLCV parquet 파일 전체에 대해 무결성 검증 수행.

    Args:
        base_dir: 데이터 디렉토리 경로

    Returns:
        (성공 여부, 요약 메시지) 튜플
    """
    data_store = ParquetDataStore(base_dir=base_dir)
    ohlcv_dir = data_store.ohlcv_dir

    parquet_files = list(ohlcv_dir.glob("*_ohlcv.parquet"))
    if not parquet_files:
        return True, "OHLCV: no accumulated data files"

    total_issues: list[str] = []

    for pf in parquet_files:
        symbol = pf.stem.replace("_ohlcv", "")
        try:
            df = pd.read_parquet(pf)
        except Exception as e:
            total_issues.append(f"{symbol}: parquet 읽기 실패 — {e}")
            continue

        total_issues.extend(validate_ohlcv_consistency(df, symbol))
        total_issues.extend(validate_ohlcv_date_gaps(df, symbol))
        total_issues.extend(validate_ohlcv_outliers(df, symbol))

    if total_issues:
        for issue in total_issues:
            logger.warning(f"OHLCV 검증: {issue}")
        return False, f"OHLCV: {len(total_issues)} issues in {len(parquet_files)} files"

    return True, f"OHLCV: {len(parquet_files)} files, all valid"


def main():
    parser = argparse.ArgumentParser(description="Validate Turtle Trading data integrity")
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues where possible")

    args = parser.parse_args()

    print("=== Data Validation Report ===")
    print()

    validator = DataValidator(base_dir="data")

    checks = [
        ("Positions JSON", lambda: validator.validate_position_json(fix=args.fix)),
        ("Entries JSON", lambda: validator.validate_entries_json(fix=args.fix)),
        ("Parquet Files", validator.validate_parquet_files),
        ("Data Consistency", lambda: validator.validate_data_consistency(fix=args.fix)),
        ("Date Range", validator.validate_date_range),
        ("Price Sanity", validator.validate_price_sanity),
        ("OHLCV Data", lambda: validate_ohlcv_data()),
    ]

    results = []
    for name, check_func in checks:
        ok, msg = check_func()
        status = "[OK]  " if ok else "[WARN]"
        print(f"{status} {msg}")
        results.append(ok)

    print()

    # 에러 및 경고 요약
    error_count = len(validator.errors)
    warning_count = len(validator.warnings)

    if validator.errors:
        print("=== Errors ===")
        for err in validator.errors:
            print(f"  - {err}")
        print()

    if validator.warnings:
        print("=== Warnings ===")
        for warn in validator.warnings:
            print(f"  - {warn}")
        print()

    print(f"=== Validation complete: {error_count} errors, {warning_count} warnings ===")

    # 에러가 있으면 종료 코드 1 반환
    sys.exit(0 if error_count == 0 else 1)


if __name__ == "__main__":
    main()
