"""
utils.py 단위 테스트
- Atomic write
- 백업 관리
- 스키마 검증
- safe_load_json (corrupt 파일 대응)
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
