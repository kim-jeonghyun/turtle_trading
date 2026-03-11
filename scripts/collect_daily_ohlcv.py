#!/usr/bin/env python3
"""
일별 OHLCV 데이터 수집 스크립트

KOSPI 200 + KOSDAQ 150 (~350 종목) 장 마감 후 배치 수집.
FDR(FinanceDataReader) 1차, yfinance 2차 폴백 (마켓 힌트 사용).

Usage:
    python scripts/collect_daily_ohlcv.py                    # 전체 수집
    python scripts/collect_daily_ohlcv.py --dry-run          # 실제 저장 없이 시뮬레이션
    python scripts/collect_daily_ohlcv.py --symbols 005930 000660  # 특정 종목만
    python scripts/collect_daily_ohlcv.py --date 2026-02-28  # 특정 날짜 수집
"""

import argparse
import asyncio
import fcntl
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
import yaml

from src.data_fetcher import DataFetcher
from src.data_store import ParquetDataStore
from src.notifier import NotificationLevel, NotificationMessage
from src.script_helpers import load_config, setup_notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "ohlcv_collection.yaml"
LOCK_FILE = Path("/tmp/collect_daily_ohlcv.lock")


@dataclass
class CollectionResult:
    """수집 결과 집계"""

    total_symbols: int = 0
    success_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    new_rows_total: int = 0
    failed_symbols: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def load_collection_config(config_path: Path = CONFIG_PATH) -> dict:
    """OHLCV 수집 설정 로드.

    Args:
        config_path: YAML 설정 파일 경로

    Returns:
        설정 딕셔너리

    Raises:
        FileNotFoundError: 설정 파일이 없을 때
        ValueError: 설정이 비어있을 때
    """
    if not config_path.exists():
        raise FileNotFoundError(f"수집 설정 파일 없음: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        raise ValueError(f"수집 설정이 비어있습니다: {config_path}")

    result: dict = config
    return result


def get_collection_symbols(config: dict, override_symbols: Optional[List[str]] = None) -> list[tuple[str, str]]:
    """수집 대상 심볼 목록 반환.

    Args:
        config: YAML 설정 딕셔너리
        override_symbols: CLI에서 지정한 심볼 (지정 시 설정 무시, market은 "kospi"로 기본 설정)

    Returns:
        (symbol, market) 튜플 리스트. market은 "kospi" 또는 "kosdaq".
        중복 제거, 순서 유지.
    """
    if override_symbols:
        return [(s, "kospi") for s in override_symbols]

    symbol_pairs: list[tuple[str, str]] = []
    symbols_config = config.get("symbols", {})

    for group_name, group_symbols in symbols_config.items():
        market = "kosdaq" if "kosdaq" in group_name.lower() else "kospi"
        if isinstance(group_symbols, list):
            for s in group_symbols:
                symbol_pairs.append((str(s), market))

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for symbol, market in symbol_pairs:
        if symbol not in seen:
            seen.add(symbol)
            unique.append((symbol, market))

    return unique


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame 유효성 검증 및 정제.

    Args:
        df: 원본 OHLCV DataFrame

    Returns:
        정제된 DataFrame

    Raises:
        ValueError: 필수 컬럼이 누락된 경우
    """
    required_columns = {"date", "open", "high", "low", "close", "volume"}
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}")

    original_len = len(df)

    df = df.dropna(subset=["close"])

    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        df = df[df[col] >= 0]

    # OHLC 논리 검증: high < low인 행 제거
    invalid_hl = df["high"] < df["low"]
    if invalid_hl.any():
        logger.warning(f"OHLC 불일치 {invalid_hl.sum()}건 제거 (high < low)")
        df = df[~invalid_hl]

    dropped = original_len - len(df)
    if dropped > 0:
        logger.warning(f"OHLCV 유효성 검증: {dropped}행 제거됨 (null close, 음수 가격, 또는 OHLC 불일치)")

    return df.reset_index(drop=True)


def collect_symbol(
    symbol: str,
    fetcher: DataFetcher,
    data_store: ParquetDataStore,
    start_date: str,
    end_date: str,
    dry_run: bool = False,
    max_retries: int = 1,
    market: str = "kospi",
) -> tuple[Optional[bool], int, str]:
    """단일 종목 OHLCV 수집.

    FDR로 먼저 시도하고, 실패 시 yfinance 폴백 (마켓 힌트에 따라 .KS/.KQ 순서 결정).

    Returns:
        (success, new_rows, message) 튜플.
        success=True: 수집 성공, success=False: 수집 실패(에러),
        success=None: 스킵 (공휴일 등 데이터 자체가 없는 경우)
    """
    last_error = ""

    if market == "kosdaq":
        yf_suffixes = [".KQ", ".KS"]
    else:
        yf_suffixes = [".KS", ".KQ"]

    for attempt in range(max_retries + 1):
        try:
            df = fetcher.fetch_fdr(symbol, start=start_date, end=end_date)

            if not df.empty:
                df.columns = [c.lower() for c in df.columns]

            if df.empty:
                for suffix in yf_suffixes:
                    yf_symbol = f"{symbol}{suffix}"
                    logger.info(f"FDR 데이터 없음, yfinance 폴백: {symbol} -> {yf_symbol}")
                    df = fetcher.fetch_yfinance(yf_symbol, start=start_date, end=end_date)
                    if not df.empty:
                        df.columns = [c.lower() for c in df.columns]
                        break

            if df.empty:
                return None, 0, "no-data"

            df = validate_ohlcv(df)

            if df.empty:
                return None, 0, "no-valid-data"

            if dry_run:
                logger.info(f"[DRY-RUN] {symbol}: {len(df)}행 수집 (저장 생략)")
                return True, len(df), "dry-run"

            new_rows = data_store.save_ohlcv_accumulated(symbol, df)
            return True, new_rows, "ok"

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                backoff = min(2**attempt * 0.5, 10.0)
                logger.warning(f"{symbol} 수집 실패 (시도 {attempt + 1}), {backoff:.1f}s 후 재시도: {e}")
                time.sleep(backoff)
            else:
                logger.error(f"{symbol} 수집 최종 실패: {e}")

    return False, 0, last_error


def determine_start_date(
    symbol: str,
    data_store: ParquetDataStore,
    initial_lookback_days: int,
    target_date: Optional[str] = None,
) -> str:
    """수집 시작일 결정.

    기존 데이터가 있으면 마지막 날짜 - 7일부터 (주말+공휴일 대응),
    없으면 initial_lookback_days 전부터.

    7일 오버랩 이유: 한국 공휴일(추석/설날) 연휴가 최대 5-6일 연속
    비영업일이 될 수 있어, 3일로는 부족할 수 있음.
    """
    if target_date:
        return target_date

    last_date = data_store.get_ohlcv_last_date(symbol)
    if last_date:
        start = last_date - timedelta(days=7)
        return start.strftime("%Y-%m-%d")
    else:
        start = datetime.now() - timedelta(days=initial_lookback_days)
        return start.strftime("%Y-%m-%d")


async def run_collection(
    symbols: list[tuple[str, str]],
    fetcher: DataFetcher,
    data_store: ParquetDataStore,
    rate_limit: float = 0.1,
    max_retries: int = 1,
    initial_lookback_days: int = 730,
    dry_run: bool = False,
    target_date: Optional[str] = None,
) -> CollectionResult:
    """전체 수집 실행."""
    result = CollectionResult(total_symbols=len(symbols))
    start_time = time.time()

    # --date 사용 시 end_date를 target_date + 1일로 설정
    # FDR/yfinance의 end_date는 exclusive이므로 +1일 필요
    if target_date:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        end_date = (target_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        # FDR/yfinance의 end_date는 exclusive이므로 +1일 필요
        end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"=== OHLCV 수집 시작: {len(symbols)}개 종목 ===")
    if dry_run:
        logger.info("[DRY-RUN 모드] 실제 저장 없이 시뮬레이션합니다.")

    for i, (symbol, market) in enumerate(symbols, 1):
        start_date = determine_start_date(symbol, data_store, initial_lookback_days, target_date)

        logger.info(f"[{i}/{len(symbols)}] {symbol} ({start_date} ~ {end_date})")

        success, new_rows, msg = collect_symbol(
            symbol=symbol,
            fetcher=fetcher,
            data_store=data_store,
            start_date=start_date,
            end_date=end_date,
            dry_run=dry_run,
            max_retries=max_retries,
            market=market,
        )

        if success is True:
            result.success_count += 1
            result.new_rows_total += new_rows
        elif success is None:
            result.skip_count += 1
            logger.info(f"{symbol}: 스킵 ({msg})")
        else:
            result.fail_count += 1
            result.failed_symbols.append(f"{symbol}: {msg}")

        if i < len(symbols) and rate_limit > 0:
            time.sleep(rate_limit)

    result.elapsed_seconds = time.time() - start_time
    logger.info(
        f"=== OHLCV 수집 완료: "
        f"성공 {result.success_count}, "
        f"스킵 {result.skip_count}, "
        f"실패 {result.fail_count}, "
        f"신규 {result.new_rows_total}행, "
        f"소요 {result.elapsed_seconds:.1f}초 ==="
    )

    return result


async def send_collection_summary(notifier, result: CollectionResult, dry_run: bool = False) -> None:
    """수집 결과 알림 전송."""
    if dry_run:
        level = NotificationLevel.INFO
        title = "[DRY-RUN] OHLCV 수집 시뮬레이션 완료"
    elif result.fail_count > 0:
        level = NotificationLevel.WARNING
        title = "OHLCV 수집 완료 (일부 실패)"
    else:
        level = NotificationLevel.INFO
        title = "OHLCV 수집 완료"

    body = (
        f"총 {result.total_symbols}개 종목\n"
        f"성공: {result.success_count}\n"
        f"스킵: {result.skip_count}\n"
        f"실패: {result.fail_count}\n"
        f"신규 행: {result.new_rows_total}\n"
        f"소요 시간: {result.elapsed_seconds:.1f}초"
    )

    if result.failed_symbols:
        failed_list = result.failed_symbols[:10]
        body += "\n\n실패 종목:\n" + "\n".join(f"- {s}" for s in failed_list)
        if len(result.failed_symbols) > 10:
            body += f"\n... 외 {len(result.failed_symbols) - 10}개"

    message = NotificationMessage(
        title=title,
        body=body,
        level=level,
        data={
            "성공": result.success_count,
            "스킵": result.skip_count,
            "실패": result.fail_count,
            "신규 행": result.new_rows_total,
            "소요(초)": f"{result.elapsed_seconds:.1f}",
        },
    )
    await notifier.send_message(message)


def parse_args() -> argparse.Namespace:
    """CLI 인수 파싱."""
    parser = argparse.ArgumentParser(description="일별 OHLCV 데이터 수집 (KOSPI 200 + KOSDAQ 150)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 저장 없이 수집 시뮬레이션",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="수집 대상 심볼 직접 지정 (설정 파일 무시)",
    )
    parser.add_argument(
        "--date",
        type=str,
        help="특정 날짜 수집 (YYYY-MM-DD 형식)",
    )
    return parser.parse_args()


def acquire_lock():
    """중복 실행 방지를 위한 파일 잠금.

    Returns:
        file descriptor on success, None if already locked
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd
    except OSError:
        lock_fd.close()
        logger.warning("이미 실행 중인 수집 프로세스가 있습니다. 종료합니다.")
        return None


def release_lock(lock_fd):
    """파일 잠금 해제."""
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass


async def main():
    """메인 엔트리포인트."""
    lock_fd = acquire_lock()
    if lock_fd is None:
        return

    try:
        args = parse_args()

        collection_config = load_collection_config()
        app_config = load_config()

        coll_settings = collection_config.get("collection", {})
        rate_limit = coll_settings.get("rate_limit_seconds", 0.1)
        max_retries = coll_settings.get("max_retries", 1)
        initial_lookback = coll_settings.get("initial_lookback_days", 730)

        symbols = get_collection_symbols(collection_config, args.symbols)
        if not symbols:
            logger.error("수집 대상 심볼이 없습니다.")
            return

        logger.info(f"수집 대상: {len(symbols)}개 종목")

        fetcher = DataFetcher()
        data_store = ParquetDataStore()
        notifier = setup_notifier(app_config)

        result = await run_collection(
            symbols=symbols,
            fetcher=fetcher,
            data_store=data_store,
            rate_limit=rate_limit,
            max_retries=max_retries,
            initial_lookback_days=initial_lookback,
            dry_run=args.dry_run,
            target_date=args.date,
        )

        await send_collection_summary(notifier, result, args.dry_run)

        # 수집 성공 시 인텔리전스 파이프라인 트리거 (별도 프로세스)
        if not args.dry_run and result.success_count > 0:
            logger.info("=== 인텔리전스 파이프라인 트리거 ===")
            try:
                import subprocess
                import sys

                subprocess.Popen(
                    [sys.executable, str(Path(__file__).parent / "market_intelligence.py")],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("인텔리전스 파이프라인 프로세스 시작 완료")
            except Exception as e:
                logger.error(f"인텔리전스 파이프라인 트리거 실패 (수집 결과에 영향 없음): {e}")

    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    asyncio.run(main())
