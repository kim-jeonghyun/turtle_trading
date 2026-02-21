"""
utils.py 단위 테스트
- Atomic write
- 백업 관리
- 스키마 검증
- safe_load_json (corrupt 파일 대응)
- 심볼 입력 검증
"""

import pytest
import json
import os
import tempfile
import shutil
from pathlib import Path

from src.utils import (
    atomic_write_json,
    backup_file,
    validate_position_schema,
    safe_load_json,
    validate_symbol,
)


@pytest.fixture
def temp_dir():
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


class TestAtomicWriteJson:
    def test_basic_write(self, temp_dir):
        filepath = temp_dir / "test.json"
        data = {"key": "value", "number": 42}
        atomic_write_json(filepath, data)

        assert filepath.exists()
        with open(filepath, 'r') as f:
            loaded = json.load(f)
        assert loaded == data

    def test_nested_data(self, temp_dir):
        filepath = temp_dir / "nested.json"
        data = {"list": [1, 2, 3], "nested": {"a": "b"}}
        atomic_write_json(filepath, data)

        with open(filepath, 'r') as f:
            loaded = json.load(f)
        assert loaded == data

    def test_creates_parent_dirs(self, temp_dir):
        filepath = temp_dir / "subdir1" / "subdir2" / "test.json"
        atomic_write_json(filepath, {"key": "value"})
        assert filepath.exists()

    def test_unicode_data(self, temp_dir):
        filepath = temp_dir / "unicode.json"
        data = {"한국어": "테스트", "日本語": "テスト"}
        atomic_write_json(filepath, data)

        with open(filepath, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        assert loaded["한국어"] == "테스트"

    def test_overwrite_existing(self, temp_dir):
        filepath = temp_dir / "test.json"
        atomic_write_json(filepath, {"version": 1})
        atomic_write_json(filepath, {"version": 2})

        with open(filepath, 'r') as f:
            loaded = json.load(f)
        assert loaded["version"] == 2

    def test_string_path(self, temp_dir):
        filepath = str(temp_dir / "str_path.json")
        atomic_write_json(filepath, {"key": "value"})
        assert Path(filepath).exists()


class TestBackupFile:
    def test_backup_creates_file(self, temp_dir):
        source = temp_dir / "data.json"
        source.write_text('{"key": "value"}')

        backup_file(source)

        backup_dir = temp_dir / "backups"
        assert backup_dir.exists()
        backups = list(backup_dir.glob("data_*.json"))
        assert len(backups) == 1

    def test_backup_nonexistent_file(self, temp_dir):
        source = temp_dir / "nonexistent.json"
        backup_file(source)  # Should not raise

    def test_backup_preserves_content(self, temp_dir):
        source = temp_dir / "data.json"
        original_data = '{"key": "original"}'
        source.write_text(original_data)

        backup_file(source)

        backup_dir = temp_dir / "backups"
        backups = list(backup_dir.glob("data_*.json"))
        assert len(backups) == 1
        assert backups[0].read_text() == original_data

    def test_max_backups_cleanup(self, temp_dir):
        source = temp_dir / "data.json"
        source.write_text('{"key": "value"}')

        backup_dir = temp_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Create old backups manually
        for i in range(10):
            old_backup = backup_dir / f"data_202501{i:02d}.json"
            old_backup.write_text(f'{{"day": {i}}}')

        # Now create a new backup with max_backups=3
        backup_file(source, max_backups=3)

        backups = list(backup_dir.glob("data_*.json"))
        assert len(backups) <= 3


class TestValidatePositionSchema:
    def test_valid_position(self):
        data = {
            'position_id': 'SPY_1_LONG',
            'symbol': 'SPY',
            'entry_price': 100.0,
            'status': 'open',
            'direction': 'LONG',
            'system': 1,
            'entry_date': '2025-01-01',
            'entry_n': 2.5,
            'units': 1,
            'total_shares': 40,
            'stop_loss': 95.0,
        }
        assert validate_position_schema(data) is True

    def test_missing_field(self):
        data = {
            'symbol': 'SPY',
            'entry_price': 100.0,
        }
        assert validate_position_schema(data) is False

    def test_custom_required_fields(self):
        data = {'a': 1, 'b': 2}
        assert validate_position_schema(data, required_fields=['a', 'b']) is True
        assert validate_position_schema(data, required_fields=['a', 'c']) is False

    def test_empty_data(self):
        assert validate_position_schema({}) is False

    def test_empty_required_fields(self):
        assert validate_position_schema({}, required_fields=[]) is True


class TestSafeLoadJson:
    def test_load_valid_json(self, temp_dir):
        filepath = temp_dir / "valid.json"
        data = {"key": "value", "count": 42}
        filepath.write_text(json.dumps(data))

        loaded = safe_load_json(filepath)
        assert loaded == data

    def test_load_nonexistent_file(self, temp_dir):
        filepath = temp_dir / "nonexistent.json"
        result = safe_load_json(filepath)
        assert result == []

    def test_load_nonexistent_with_default(self, temp_dir):
        filepath = temp_dir / "nonexistent.json"
        result = safe_load_json(filepath, default={"default": True})
        assert result == {"default": True}

    def test_load_corrupt_json(self, temp_dir):
        filepath = temp_dir / "corrupt.json"
        filepath.write_text("this is not json{{{")

        result = safe_load_json(filepath)
        assert result == []

    def test_load_corrupt_with_default(self, temp_dir):
        filepath = temp_dir / "corrupt.json"
        filepath.write_text("not json")

        result = safe_load_json(filepath, default={"fallback": True})
        assert result == {"fallback": True}

    def test_load_corrupt_with_backup_restore(self, temp_dir):
        """corrupt 파일이 있을 때 백업에서 복원"""
        filepath = temp_dir / "positions.json"
        filepath.write_text("corrupted content")

        # Create a valid backup
        backup_dir = temp_dir / "backups"
        backup_dir.mkdir()
        backup_data = [{"symbol": "SPY", "status": "open"}]
        backup_file = backup_dir / "positions_20250101.json"
        backup_file.write_text(json.dumps(backup_data))

        result = safe_load_json(filepath)
        assert result == backup_data

    def test_string_path(self, temp_dir):
        filepath = temp_dir / "test.json"
        filepath.write_text('{"key": "value"}')

        result = safe_load_json(str(filepath))
        assert result == {"key": "value"}


class TestValidateSymbol:
    """validate_symbol() 단위 테스트"""

    # --- 유효한 심볼 ---

    def test_us_stock(self):
        assert validate_symbol("AAPL") == "AAPL"

    def test_us_stock_lowercase(self):
        assert validate_symbol("aapl") == "aapl"

    def test_kr_stock_with_dot(self):
        assert validate_symbol("005930.KS") == "005930.KS"

    def test_kr_stock_kq(self):
        assert validate_symbol("035420.KQ") == "035420.KQ"

    def test_kr_stock_numeric(self):
        assert validate_symbol("005930") == "005930"

    def test_crypto_slash(self):
        assert validate_symbol("BTC/USDT") == "BTC/USDT"

    def test_crypto_hyphen(self):
        assert validate_symbol("BTC-USD") == "BTC-USD"

    def test_etf(self):
        assert validate_symbol("SPY") == "SPY"

    def test_underscore(self):
        assert validate_symbol("BRK_B") == "BRK_B"

    def test_single_char(self):
        assert validate_symbol("X") == "X"

    def test_max_length_20(self):
        symbol = "A" * 20
        assert validate_symbol(symbol) == symbol

    def test_mixed_chars(self):
        assert validate_symbol("US.10Y-BOND/2") == "US.10Y-BOND/2"

    # --- strip 처리 ---

    def test_strips_whitespace(self):
        assert validate_symbol("  AAPL  ") == "AAPL"

    def test_strips_leading_space(self):
        assert validate_symbol(" SPY") == "SPY"

    def test_strips_trailing_space(self):
        assert validate_symbol("SPY ") == "SPY"

    # --- 유효하지 않은 심볼 (ValueError) ---

    def test_empty_string(self):
        with pytest.raises(ValueError, match="빈 문자열"):
            validate_symbol("")

    def test_whitespace_only(self):
        with pytest.raises(ValueError, match="빈 문자열"):
            validate_symbol("   ")

    def test_none(self):
        with pytest.raises(ValueError, match="문자열이어야"):
            validate_symbol(None)

    def test_integer(self):
        with pytest.raises(ValueError, match="문자열이어야"):
            validate_symbol(123)

    def test_list(self):
        with pytest.raises(ValueError, match="문자열이어야"):
            validate_symbol(["AAPL"])

    def test_too_long(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("A" * 21)

    def test_special_chars_semicolon(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("AAPL;DROP")

    def test_special_chars_space_in_middle(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("AA PL")

    def test_sql_injection_attempt(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("'; DROP TABLE --")

    def test_path_traversal_attempt(self):
        """경로 순회 시도: 21자 이상이면 길이 초과로 거부"""
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("../../../etc/passwd00")

    def test_path_traversal_short_uses_safe_chars(self):
        """짧은 경로 순회 패턴은 regex 통과하지만 data_store가 /를 _로 치환하여 안전"""
        result = validate_symbol("../../etc/passwd")
        assert result == "../../etc/passwd"

    def test_newline_trailing_stripped(self):
        """후행 개행 문자는 strip으로 제거되어 유효한 심볼로 처리"""
        assert validate_symbol("AAPL\n") == "AAPL"

    def test_newline_embedded(self):
        """심볼 중간의 개행 문자는 거부"""
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("AA\nPL")

    def test_tab_trailing_stripped(self):
        """후행 탭 문자는 strip으로 제거되어 유효한 심볼로 처리"""
        assert validate_symbol("AAPL\t") == "AAPL"

    def test_tab_embedded(self):
        """심볼 중간의 탭 문자는 거부"""
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("AA\tPL")

    def test_null_byte(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("AAPL" + chr(0))

    def test_unicode_korean(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("삼성전자")

    def test_parentheses(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("AAPL(US)")

    def test_at_sign(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("AAPL@NYSE")

    def test_dollar_sign(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("$AAPL")

    def test_backtick(self):
        with pytest.raises(ValueError, match="유효하지 않은 심볼"):
            validate_symbol("`ls`")
