#!/usr/bin/env python3
"""
시장 인텔리전스 파이프라인.

collect_daily_ohlcv.py 이후 실행되어 350종목 OHLCV를 분석하고
구조화된 인텔리전스 리포트를 생성·전송합니다.

Usage:
    python scripts/market_intelligence.py              # 전체 파이프라인
    python scripts/market_intelligence.py --dry-run    # 리포트 생성만 (전송 없음)
    python scripts/market_intelligence.py --json       # JSON 출력
"""

import argparse
import asyncio
import fcntl
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data_store import ParquetDataStore
from src.market_breadth import calculate_breadth_score
from src.regime_detector import RegimeSnapshot, classify_regime
from src.screener import TurtleStrategy, run_screening
from src.script_helpers import load_config, setup_notifier
from src.types import MarketRegime, SignalType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
LOCK_FILE = PROJECT_ROOT / "data" / ".market_intelligence.lock"

# DD5: 레짐 분류용 인덱스 프록시 (KODEX 200, KODEX KOSDAQ 150)
INDEX_PROXIES = ["069500", "229200"]

# 레짐별 경고 메시지 (advisory only — 차단 없음)
_REGIME_WARNINGS: dict[MarketRegime, str] = {
    MarketRegime.BEAR: "레짐 BEAR — 신규 진입 주의 권고",
    MarketRegime.DECLINE: "레짐 DECLINE — 진입 규모 축소 고려",
    MarketRegime.SIDEWAYS: "레짐 SIDEWAYS — 브레이크아웃 신뢰도 낮음",
}


def generate_intelligence_report(
    data: dict[str, pd.DataFrame],
    index_df: pd.DataFrame | None = None,
) -> dict:
    """인텔리전스 리포트 데이터 생성.

    Args:
        data: {symbol: ohlcv_df} — 전체 350종목
        index_df: 대표 지수 OHLCV (DD5: KODEX 200 등). None이면 가장 긴 데이터로 대체.

    Returns:
        리포트 딕셔너리
    """
    today = datetime.now().strftime("%Y-%m-%d")
    warnings: list[str] = []

    # 1. 브레드스 계산
    breadth = calculate_breadth_score(data)

    # 2. 레짐 분류 (DD5: 인덱스 프록시 우선)
    if index_df is not None and len(index_df) >= 200:
        regime_snapshot = classify_regime(index_df)
    elif data:
        longest_symbol = max(data.keys(), key=lambda s: len(data[s]))
        regime_snapshot = classify_regime(data[longest_symbol])
    else:
        regime_snapshot = RegimeSnapshot(
            regime=MarketRegime.SIDEWAYS,
            last_close=0,
            sma_50=0,
            sma_200=0,
            slope_200=0,
        )

    # 레짐 경고 (advisory only)
    if regime_snapshot.regime in _REGIME_WARNINGS:
        warnings.append(_REGIME_WARNINGS[regime_snapshot.regime])

    # 브레드스 경고
    if breadth.composite_score < 40:
        warnings.append(f"브레드스 낮음 ({breadth.composite_score:.0f}/100) — 시장 약세 주의")
    if breadth.pct_above_200ma < 40:
        warnings.append(f"200MA 상위 {breadth.pct_above_200ma:.0f}% — 장기 추세 약화")

    # 3. 스크리닝 (한국 주식 숏 제한: short_restricted_symbols=None → 전체 제한)
    screening_results = run_screening(data, strategies=[TurtleStrategy()])

    entry_signals = [r for r in screening_results if r.signal_type in (SignalType.ENTRY_LONG, SignalType.ENTRY_SHORT)]
    exit_signals = [r for r in screening_results if r.signal_type in (SignalType.EXIT_LONG, SignalType.EXIT_SHORT)]

    # Top 후보: entry 시그널을 시스템 우선순위로 정렬 (S2 > S1)
    top_candidates = sorted(
        entry_signals,
        key=lambda r: (r.metadata.get("system", 0), r.current_close),
        reverse=True,
    )[:10]

    return {
        "date": today,
        "regime": regime_snapshot.regime.value,
        "regime_detail": regime_snapshot.to_dict(),
        "breadth": breadth.to_dict(),
        "breadth_score": breadth.composite_score,
        "entry_signals": len(entry_signals),
        "exit_signals": len(exit_signals),
        "all_signals": [r.to_dict() for r in screening_results],
        "top_candidates": [
            {
                "symbol": r.symbol,
                "signal": r.message,
                "signal_type": r.signal_type.value,
                "price": round(r.price, 2),
                "stop_loss": round(r.stop_loss, 2),
                "n_value": round(r.n_value, 2),
            }
            for r in top_candidates
        ],
        "warnings": warnings,
        "total_symbols_analyzed": len(data),
    }


def acquire_lock():
    """중복 실행 방지."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd
    except OSError:
        lock_fd.close()
        logger.warning("이미 실행 중인 인텔리전스 프로세스가 있습니다.")
        return None


def release_lock(lock_fd):
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass


async def run_pipeline(
    dry_run: bool = False,
    min_rows: int = 56,
    output_json: bool = False,
    timeout: int = 300,
) -> dict | None:
    """인텔리전스 파이프라인 실행 (parse_args 없이 직접 호출 가능).

    Lock 획득, 파이프라인 로직, lock 해제를 모두 담당.
    hook과 CLI 양쪽에서 안전하게 호출 가능.

    Args:
        dry_run: True이면 전송 없이 리포트만 생성
        min_rows: 최소 데이터 행 수
        output_json: True이면 stdout에 JSON 출력
        timeout: 파이프라인 타임아웃 초 (기본 300초)

    Returns:
        리포트 딕셔너리. 실행 불가/타임아웃 시 None.
    """
    lock_fd = acquire_lock()
    if lock_fd is None:
        return None

    try:
        async with asyncio.timeout(timeout):
            logger.info("=== 시장 인텔리전스 파이프라인 시작 ===")

            data_store = ParquetDataStore(base_dir=str(PROJECT_ROOT / "data"))
            symbols = data_store.list_accumulated_symbols()

            if not symbols:
                logger.warning("축적 OHLCV 데이터 없음. collect_daily_ohlcv.py를 먼저 실행하세요.")
                return None

            logger.info(f"축적 심볼: {len(symbols)}개, 로딩 중 (min_rows={min_rows})...")
            data = data_store.load_multiple_ohlcv(symbols, min_rows=min_rows)
            logger.info(f"분석 대상: {len(data)}개 심볼")

            if not data:
                logger.warning(
                    f"min_rows={min_rows} 기준 분석 가능 심볼 0개. "
                    "데이터 축적을 기다리세요."
                )
                return None

            # DD5: 인덱스 프록시 로드
            index_df = None
            for proxy_symbol in INDEX_PROXIES:
                proxy_df = data_store.load_ohlcv_accumulated(proxy_symbol)
                if proxy_df is not None and len(proxy_df) >= 200:
                    index_df = proxy_df
                    logger.info(f"인덱스 프록시 사용: {proxy_symbol} ({len(proxy_df)}행)")
                    break

            if index_df is None:
                logger.info("인덱스 프록시 미발견, 가장 긴 심볼로 대체")

            # 리포트 생성
            report = generate_intelligence_report(data, index_df=index_df)

            logger.info(
                f"리포트 완료: 레짐={report['regime']}, "
                f"브레드스={report['breadth_score']:.0f}, "
                f"진입={report['entry_signals']}, 청산={report['exit_signals']}"
            )

            # JSON 출력
            if output_json:
                print(json.dumps(report, ensure_ascii=False, indent=2))

            # JSON 아카이브 저장
            archive_dir = PROJECT_ROOT / "data" / "intelligence"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"{report['date']}.json"
            with open(archive_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info(f"아카이브 저장: {archive_path}")

            # 알림 전송
            if not dry_run:
                config = load_config()
                notifier = setup_notifier(config)
                await notifier.send_market_intelligence(report)
                logger.info("인텔리전스 리포트 전송 완료")
            else:
                logger.info("[DRY-RUN] 전송 생략")

            logger.info("=== 시장 인텔리전스 파이프라인 완료 ===")
            return report

    except TimeoutError:
        logger.error(f"인텔리전스 파이프라인 타임아웃 ({timeout}초)")
        return None
    finally:
        release_lock(lock_fd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="시장 인텔리전스 리포트 생성")
    parser.add_argument("--dry-run", action="store_true", help="리포트 생성만 (전송 없음)")
    parser.add_argument("--json", action="store_true", help="JSON 형식 출력")
    parser.add_argument("--min-rows", type=int, default=56, help="최소 데이터 행 수 (기본 56)")
    parser.add_argument("--timeout", type=int, default=300, help="파이프라인 타임아웃 초 (기본 300)")
    return parser.parse_args()


async def main():
    """CLI 엔트리포인트. thin wrapper — parse_args만 처리하고 run_pipeline에 위임."""
    args = parse_args()
    await run_pipeline(
        dry_run=args.dry_run,
        min_rows=args.min_rows,
        output_json=args.json,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    asyncio.run(main())
