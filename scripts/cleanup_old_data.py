#!/usr/bin/env python3
"""
오래된 데이터 정리 - 캐시, 로그, 백업 관리
- 오래된 parquet 캐시 파일 정리 (기본값: 30일)
- 오래된 로그 파일 정리 (기본값: 90일)
- 오래된 백업 아카이브 정리 (최신 N개 유지)
- --dry-run이 기본값이며, --execute를 통해 실제 삭제 가능
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_project_root() -> Path:
    """프로젝트 루트 디렉토리 반환"""
    return Path(__file__).parent.parent


def find_old_files(
    directory: Path,
    pattern: str,
    days_old: int,
    exclude_patterns: List[str] = None
) -> List[Path]:
    """
    지정된 패턴과 나이 조건에 맞는 파일 찾기

    Args:
        directory: 검색 디렉토리
        pattern: glob 패턴 (예: "*.parquet")
        days_old: 이 날짜보다 오래된 파일만 반환
        exclude_patterns: 제외할 glob 패턴

    Returns:
        오래된 파일 목록
    """
    if not directory.exists():
        return []

    exclude_patterns = exclude_patterns or []
    cutoff_date = datetime.now() - timedelta(days=days_old)
    old_files = []

    for filepath in directory.glob(pattern):
        # 제외 패턴 체크
        excluded = False
        for exclude_pattern in exclude_patterns:
            if filepath.match(exclude_pattern):
                excluded = True
                break

        if excluded:
            continue

        # 파일 수정 시간 체크
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        if mtime < cutoff_date:
            old_files.append(filepath)

    return sorted(old_files)


def cleanup_cache_files(
    dry_run: bool = True,
    cache_days: int = 30
) -> Tuple[int, int]:
    """
    Parquet 캐시 파일 정리

    Args:
        dry_run: True면 삭제하지 않고 목록만 출력
        cache_days: 이 날짜보다 오래된 캐시만 삭제

    Returns:
        (파일 수, 해제된 용량 MB)
    """
    cache_dir = get_project_root() / "data" / "cache"

    if not cache_dir.exists():
        logger.info(f"캐시 디렉토리 없음: {cache_dir}")
        return 0, 0

    logger.info(f"캐시 디렉토리 검색: {cache_dir}")

    old_files = find_old_files(cache_dir, "*.parquet", cache_days)

    if not old_files:
        logger.info(f"정리할 오래된 캐시 파일 없음 ({cache_days}일 이상)")
        return 0, 0

    total_size_mb = 0

    for filepath in old_files:
        size_bytes = filepath.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        total_size_mb += size_mb

        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        age_days = (datetime.now() - mtime).days

        if dry_run:
            logger.info(f"  [DRY-RUN] 삭제 예정: {filepath.name} ({age_days}일, {size_mb:.2f}MB)")
        else:
            try:
                filepath.unlink()
                logger.info(f"  ✓ 삭제: {filepath.name} ({size_mb:.2f}MB)")
            except Exception as e:
                logger.error(f"  ✗ 삭제 실패: {filepath.name} - {e}")

    logger.info(f"캐시 정리 결과: {len(old_files)}개 파일, {total_size_mb:.2f}MB")

    return len(old_files), total_size_mb


def cleanup_log_files(
    dry_run: bool = True,
    log_days: int = 90
) -> Tuple[int, int]:
    """
    로그 파일 정리

    Args:
        dry_run: True면 삭제하지 않고 목록만 출력
        log_days: 이 날짜보다 오래된 로그만 삭제

    Returns:
        (파일 수, 해제된 용량 MB)
    """
    log_dir = get_project_root() / "logs"

    if not log_dir.exists():
        logger.info(f"로그 디렉토리 없음: {log_dir}")
        return 0, 0

    logger.info(f"로그 디렉토리 검색: {log_dir}")

    old_files = find_old_files(
        log_dir,
        "*.log*",
        log_days,
        exclude_patterns=["*.log"]  # 현재 활성 로그는 제외
    )

    if not old_files:
        logger.info(f"정리할 오래된 로그 파일 없음 ({log_days}일 이상)")
        return 0, 0

    total_size_mb = 0

    for filepath in old_files:
        size_bytes = filepath.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        total_size_mb += size_mb

        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        age_days = (datetime.now() - mtime).days

        if dry_run:
            logger.info(f"  [DRY-RUN] 삭제 예정: {filepath.name} ({age_days}일, {size_mb:.2f}MB)")
        else:
            try:
                filepath.unlink()
                logger.info(f"  ✓ 삭제: {filepath.name} ({size_mb:.2f}MB)")
            except Exception as e:
                logger.error(f"  ✗ 삭제 실패: {filepath.name} - {e}")

    logger.info(f"로그 정리 결과: {len(old_files)}개 파일, {total_size_mb:.2f}MB")

    return len(old_files), total_size_mb


def cleanup_backup_archives(
    dry_run: bool = True,
    keep_count: int = 30
) -> Tuple[int, int]:
    """
    백업 아카이브 정리 (최신 N개만 유지)

    Args:
        dry_run: True면 삭제하지 않고 목록만 출력
        keep_count: 유지할 최신 백업 개수

    Returns:
        (파일 수, 해제된 용량 MB)
    """
    backup_dir = get_project_root() / "data" / "backups"

    if not backup_dir.exists():
        logger.info(f"백업 디렉토리 없음: {backup_dir}")
        return 0, 0

    logger.info(f"백업 디렉토리 검색: {backup_dir}")

    # 모든 백업 파일 찾기 (날짜 순서대로 정렬)
    all_backups = sorted(
        backup_dir.glob("*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if len(all_backups) <= keep_count:
        logger.info(f"유지할 백업: {len(all_backups)}개 (최소 유지: {keep_count}개)")
        return 0, 0

    old_backups = all_backups[keep_count:]
    total_size_mb = 0

    for filepath in old_backups:
        size_bytes = filepath.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        total_size_mb += size_mb

        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        age_days = (datetime.now() - mtime).days

        if dry_run:
            logger.info(f"  [DRY-RUN] 삭제 예정: {filepath.name} ({age_days}일, {size_mb:.2f}MB)")
        else:
            try:
                if filepath.is_dir():
                    import shutil
                    shutil.rmtree(filepath)
                else:
                    filepath.unlink()
                logger.info(f"  ✓ 삭제: {filepath.name} ({size_mb:.2f}MB)")
            except Exception as e:
                logger.error(f"  ✗ 삭제 실패: {filepath.name} - {e}")

    logger.info(f"백업 정리 결과: {len(old_backups)}개 파일, {total_size_mb:.2f}MB")

    return len(old_backups), total_size_mb


def print_summary(
    cache_files: int,
    cache_size_mb: float,
    log_files: int,
    log_size_mb: float,
    backup_files: int,
    backup_size_mb: float,
    dry_run: bool
):
    """정리 결과 요약"""
    logger.info("=" * 80)
    logger.info("CLEANUP SUMMARY")
    logger.info("=" * 80)

    mode = "[DRY-RUN MODE]" if dry_run else "[EXECUTION MODE]"
    print(f"\n{mode}\n")

    total_files = cache_files + log_files + backup_files
    total_size_mb = cache_size_mb + log_size_mb + backup_size_mb

    print(f"캐시 파일:    {cache_files:4} files  {cache_size_mb:8.2f} MB")
    print(f"로그 파일:    {log_files:4} files  {log_size_mb:8.2f} MB")
    print(f"백업 파일:    {backup_files:4} files  {backup_size_mb:8.2f} MB")
    print(f"{'-' * 50}")
    print(f"합계:         {total_files:4} files  {total_size_mb:8.2f} MB")

    if dry_run:
        print("\n💡 Tip: --execute 플래그를 사용하여 실제 삭제 가능")
    else:
        print("\n✓ 정리가 완료되었습니다")

    logger.info("=" * 80)


def main(args):
    """메인 함수"""
    if args.dry_run and args.execute:
        logger.error("--dry-run과 --execute는 동시에 사용할 수 없습니다")
        return

    # 모드 결정 (기본값: dry_run)
    dry_run = not args.execute
    mode_str = "DRY-RUN" if dry_run else "EXECUTION"

    logger.info(f"=== 오래된 데이터 정리 시작 ({mode_str}) ===")
    logger.info(f"캐시 임계값: {args.cache_days}일")
    logger.info(f"로그 임계값: {args.log_days}일")
    logger.info(f"백업 유지: 최신 {args.keep_backups}개")

    # 각 종류별 정리 실행
    cache_files, cache_size = cleanup_cache_files(dry_run, args.cache_days)
    log_files, log_size = cleanup_log_files(dry_run, args.log_days)
    backup_files, backup_size = cleanup_backup_archives(dry_run, args.keep_backups)

    # 요약 출력
    print_summary(
        cache_files, cache_size,
        log_files, log_size,
        backup_files, backup_size,
        dry_run
    )

    logger.info("=== 정리 완료 ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="오래된 데이터 정리 (캐시, 로그, 백업)"
    )

    # 실행 모드
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="미리보기 모드 (기본값, 삭제하지 않음)"
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="실제 삭제 실행 (주의: 되돌릴 수 없음)"
    )

    # 정리 옵션
    parser.add_argument(
        "--cache-days",
        type=int,
        default=30,
        help="이 날짜 이상 오래된 캐시 파일 정리 (기본값: 30일)"
    )
    parser.add_argument(
        "--log-days",
        type=int,
        default=90,
        help="이 날짜 이상 오래된 로그 파일 정리 (기본값: 90일)"
    )
    parser.add_argument(
        "--keep-backups",
        type=int,
        default=30,
        help="유지할 최신 백업 개수 (기본값: 30개)"
    )

    args = parser.parse_args()

    # --dry-run이 명시적으로 지정되었다면 제대로 처리
    if "--dry-run" not in sys.argv and "--execute" not in sys.argv:
        args.dry_run = True
        args.execute = False

    main(args)
