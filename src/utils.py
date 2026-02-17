"""
공유 유틸리티 모듈
- Atomic write 패턴
- 스키마 검증
- 백업 관리
- 재시도 데코레이터
- 구조화된 로깅
"""

import json
import shutil
import tempfile
import os
import time
import asyncio
import functools
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


# ---------------------------------------------------------------------------
# 재시도 데코레이터
# ---------------------------------------------------------------------------

def retry_async(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
):
    """비동기 함수용 지수 백오프 재시도 데코레이터"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries}: {func.__name__} - {e}"
                        )
                        await asyncio.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


def retry_sync(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
):
    """동기 함수용 지수 백오프 재시도 데코레이터"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries}: {func.__name__} - {e}"
                        )
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 구조화된 로깅 설정
# ---------------------------------------------------------------------------

def setup_structured_logging(
    name: str,
    log_dir: str = "data/logs",
    level: int = logging.INFO,
) -> logging.Logger:
    """구조화된 로깅 설정 (파일 + 콘솔)"""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    structured_logger = logging.getLogger(name)
    structured_logger.setLevel(level)

    # 콘솔 핸들러
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # 파일 핸들러 (일별 로테이션)
    from logging.handlers import TimedRotatingFileHandler
    file_handler = TimedRotatingFileHandler(
        log_path / f"{name}.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    ))

    if not structured_logger.handlers:
        structured_logger.addHandler(console)
        structured_logger.addHandler(file_handler)

    return structured_logger
