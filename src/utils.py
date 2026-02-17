"""
공유 유틸리티 모듈
- Atomic write 패턴
- 스키마 검증
- 백업 관리
"""

import json
import shutil
import tempfile
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def atomic_write_json(filepath: Path, data: Any):
    """Atomic JSON write: temp file → rename (POSIX atomic)"""
    filepath = Path(filepath)
    dir_path = filepath.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.rename(tmp_path, str(filepath))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def backup_file(filepath: Path, max_backups: int = 7):
    """일별 백업 생성 (최대 max_backups개 유지)"""
    filepath = Path(filepath)
    if not filepath.exists():
        return

    backup_dir = filepath.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime('%Y%m%d')
    backup_path = backup_dir / f"{filepath.stem}_{date_str}{filepath.suffix}"

    if not backup_path.exists():
        shutil.copy2(filepath, backup_path)
        logger.info(f"백업 생성: {backup_path}")

    # 오래된 백업 정리
    backups = sorted(backup_dir.glob(f"{filepath.stem}_*{filepath.suffix}"))
    while len(backups) > max_backups:
        oldest = backups.pop(0)
        oldest.unlink()
        logger.info(f"오래된 백업 삭제: {oldest}")


def validate_position_schema(data: dict, required_fields: Optional[List[str]] = None) -> bool:
    """포지션 데이터 스키마 검증"""
    if required_fields is None:
        required_fields = [
            'position_id', 'symbol', 'entry_price', 'status',
            'direction', 'system', 'entry_date', 'entry_n',
            'units', 'total_shares', 'stop_loss'
        ]
    return all(f in data for f in required_fields)


def safe_load_json(filepath: Path, default: Any = None) -> Any:
    """안전한 JSON 로드 (corrupt 파일 대응)"""
    filepath = Path(filepath)
    if not filepath.exists():
        return default if default is not None else []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.critical(f"JSON 파일 손상: {filepath} - {e}")
        # 백업에서 복원 시도
        backup_dir = filepath.parent / "backups"
        if backup_dir.exists():
            backups = sorted(backup_dir.glob(f"{filepath.stem}_*{filepath.suffix}"), reverse=True)
            for backup in backups:
                try:
                    with open(backup, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    logger.info(f"백업에서 복원: {backup}")
                    # 복원된 데이터로 원본 덮어쓰기
                    atomic_write_json(filepath, data)
                    return data
                except (json.JSONDecodeError, Exception):
                    continue
        logger.error(f"복원 실패, 기본값 반환: {filepath}")
        return default if default is not None else []
    except Exception as e:
        logger.error(f"파일 로드 실패: {filepath} - {e}")
        return default if default is not None else []
