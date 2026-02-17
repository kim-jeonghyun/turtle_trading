#!/usr/bin/env python3
"""
Turtle Trading Data Validation
데이터 무결성 검증 및 자동 수정 스크립트
"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
from datetime import datetime
from typing import Tuple, List
import pandas as pd

from src.utils import validate_position_schema, safe_load_json, atomic_write_json


class DataValidator:
    """데이터 검증기"""

    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.errors = []
        self.warnings = []

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
        required_fields = ['entry_id', 'position_id', 'entry_date', 'entry_price', 'shares']
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
                df = pd.read_parquet(pf)
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
        position_ids = [p.get('position_id') for p in data if 'position_id' in p]
        duplicates = [pid for pid in set(position_ids) if position_ids.count(pid) > 1]

        if duplicates:
            self.errors.append(f"Duplicate position IDs: {', '.join(duplicates)}")

            if fix:
                # 가장 최근 업데이트만 유지
                seen = {}
                unique_data = []
                for p in reversed(data):  # 역순으로 처리하여 최신 것 우선
                    pid = p.get('position_id')
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
            for date_field in ['entry_date', 'exit_date']:
                date_str = p.get(date_field)
                if date_str:
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
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
            position_id = p.get('position_id', 'unknown')

            # 음수 가격 체크
            for price_field in ['entry_price', 'exit_price', 'stop_loss']:
                price = p.get(price_field)
                if price is not None and price < 0:
                    issues.append(f"{position_id} {price_field}: negative ({price})")

            # 극단값 체크 (진입가 대비 10배 이상)
            entry_price = p.get('entry_price')
            exit_price = p.get('exit_price')

            if entry_price and exit_price and entry_price > 0:
                ratio = exit_price / entry_price
                if ratio > 10 or ratio < 0.1:
                    issues.append(f"{position_id} extreme price move: {ratio:.2f}x")

        if issues:
            for issue in issues:
                self.errors.append(f"Price issue: {issue}")
            return False, f"Price sanity: {len(issues)} issues found"

        return True, "Price sanity: all prices valid"


def main():
    parser = argparse.ArgumentParser(description="Validate Turtle Trading data integrity")
    parser.add_argument('--fix', action='store_true', help='Auto-fix issues where possible')

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
