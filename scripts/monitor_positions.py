#!/usr/bin/env python3
"""
포지션 장중 모니터링 -- 5분 cron 실행

- KIS API 실시간 가격으로 스톱로스/P&L 모니터링
- 알림 중복 방지 (MonitorState)
- 파일 잠금으로 동시 실행 차단
- 장중 시간에만 실행 (is_market_open 게이트)
"""

import argparse
import asyncio
import fcntl
import logging
import logging.handlers
import os
import sys
from contextlib import nullcontext
from pathlib import Path

from src.kis_api import KISAPIClient
from src.market_calendar import infer_market, is_market_open
from src.monitor_state import MonitorState
from src.notifier import NotificationLevel, NotificationMessage
from src.position_tracker import PositionTracker
from src.script_helpers import create_kis_client, load_config, setup_notifier
from src.spot_price import SpotData, SpotPriceFetcher
from src.types import Direction
from src.vi_cb_detector import VICBDetector

LOCK_FILE = Path(__file__).parent.parent / "data" / ".monitor_positions.lock"
# NOTE: check_positions.py(.check_positions.lock)와 별도 lock 사용.
# 동시 실행 가능하나 무해: monitor는 PositionTracker read-only,
# MonitorState는 별도 파일. check_positions가 포지션 청산 시
# 다음 폴링에서 자동 반영됨.
SCRIPT_TIMEOUT = 240  # 4분 (5분 폴링 간격 내 완료 보장)

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """일별 로테이션 로깅 (cron >> 리디렉션 불필요)."""
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "monitor.log",
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def acquire_lock():
    """파일 잠금 (check_positions.py:60-82 패턴).

    Returns file descriptor on success, calls sys.exit(0) if lock held.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
    except OSError:
        logger.warning("다른 모니터링 인스턴스 실행 중 -- 종료")
        fd.close()
        sys.exit(0)
    return fd


def check_stop_loss_intraday(position, spot: SpotData) -> bool:
    """장중 스톱로스 체크 -- check_positions.py:92-94 동일 의미론.

    - LONG: 장중 저가(low) <= stop_loss
    - SHORT: 장중 고가(high) >= stop_loss

    is_delayed=True(fallback)인 경우: high=low=price이므로
    스톱로스 체크는 현재가 기준으로 동작 (거짓 알림 방지).
    """
    if position.direction == Direction.LONG:
        return bool(spot["low"] <= position.stop_loss)
    else:
        return bool(spot["high"] >= position.stop_loss)


def calculate_unrealized_pnl(position, current_price: float) -> tuple[float, float]:
    """미실현 손익 계산.

    Returns:
        (pnl_dollar, pnl_percent)
    """
    if not position.entry_price:
        return 0.0, 0.0
    if position.direction == Direction.LONG:
        pnl_dollar = (current_price - position.entry_price) * position.total_shares
        pnl_pct = (current_price - position.entry_price) / position.entry_price
    else:
        pnl_dollar = (position.entry_price - current_price) * position.total_shares
        pnl_pct = (position.entry_price - current_price) / position.entry_price
    return pnl_dollar, pnl_pct


def _build_stop_loss_alert(position, spot: SpotData) -> NotificationMessage:
    """스톱로스 알림 메시지 생성."""
    pnl_dollar, pnl_pct = calculate_unrealized_pnl(position, spot["price"])
    return NotificationMessage(
        title="STOP LOSS ALERT (Intraday)",
        body=(
            f"장중 스톱로스 이탈 감지\n"
            f"심볼: {position.symbol}\n"
            f"방향: {position.direction.value}\n"
            f"진입가: {position.entry_price:,.2f}\n"
            f"스톱: {position.stop_loss:,.2f}\n"
            f"현재가: {spot['price']:,.2f}\n"
            f"장중저가: {spot['low']:,.2f}\n"
            f"장중고가: {spot['high']:,.2f}\n"
            f"미실현손익: ${pnl_dollar:,.2f} ({pnl_pct * 100:+.2f}%)"
        ),
        level=NotificationLevel.ERROR,
        data={"action": "CHECK_POSITION", "symbol": position.symbol},
    )


def _build_pnl_warning(position, spot: SpotData, pnl_dollar: float, pnl_pct: float) -> NotificationMessage:
    """P&L 경고 알림 메시지 생성."""
    return NotificationMessage(
        title="UNREALIZED LOSS WARNING (Intraday)",
        body=(
            f"미실현 손실 임계치 초과\n"
            f"심볼: {position.symbol}\n"
            f"방향: {position.direction.value}\n"
            f"진입가: {position.entry_price:,.2f}\n"
            f"현재가: {spot['price']:,.2f}\n"
            f"미실현손익: ${pnl_dollar:,.2f} ({pnl_pct * 100:+.2f}%)"
        ),
        level=NotificationLevel.WARNING,
        data={"symbol": position.symbol, "pnl_pct": f"{pnl_pct * 100:.2f}%"},
    )


async def monitor_positions(args):
    """장중 포지션 모니터링 메인 루프."""
    lock_fd = acquire_lock()

    try:
        async with asyncio.timeout(SCRIPT_TIMEOUT):
            config = load_config()
            notifier = setup_notifier(config)
            tracker = PositionTracker()
            monitor_state = MonitorState.load()

            # KIS 세션 관리: async with로 1회 생성, 전 종목 공유
            kis_config = create_kis_client(config)
            kis_ctx = KISAPIClient(kis_config) if kis_config else None

            async with kis_ctx if kis_ctx else nullcontext() as kis_client:
                spot_fetcher = SpotPriceFetcher(kis_client)
                vi_cb_detector = VICBDetector()

                open_positions = tracker.get_open_positions()
                if not open_positions:
                    logger.info("오픈 포지션 없음")
                    return

                logger.info(f"모니터링 시작: {len(open_positions)}개 포지션")
                open_ids = {p.position_id for p in open_positions}
                monitor_state.cleanup_closed_positions(open_ids)

                for pos in open_positions:
                    market = infer_market(pos.symbol)
                    if market != "CRYPTO" and not is_market_open(market):
                        logger.debug(f"장외 시간: {pos.symbol} ({market})")
                        continue

                    spot = await spot_fetcher.fetch_spot_price(pos.symbol)
                    if spot is None:
                        logger.warning(f"가격 조회 실패: {pos.symbol}")
                        continue

                    # VI/CB 상태 체크: 발동 중이면 모니터링 일시 중지
                    vi_allowed, vi_reason = vi_cb_detector.check_entry_allowed(pos.symbol)
                    if not vi_allowed:
                        logger.info(f"VI/CB 발동 중: {pos.symbol} 모니터링 일시 중지 — {vi_reason}")
                        continue

                    # 스톱로스 체크
                    if check_stop_loss_intraday(pos, spot):
                        if not monitor_state.is_stop_loss_alerted(pos.position_id):
                            await notifier.send_message(_build_stop_loss_alert(pos, spot))
                            monitor_state.mark_stop_loss_alerted(pos.position_id)
                            logger.warning(f"스톱로스 알림: {pos.symbol}")
                    else:
                        # 가격 회복 시 리셋 (다음 이탈에 재알림 가능)
                        if monitor_state.is_stop_loss_alerted(pos.position_id):
                            monitor_state.reset_stop_loss_alert(pos.position_id)
                            logger.info(f"스톱로스 회복: {pos.symbol}")

                    # P&L 경고
                    pnl_dollar, pnl_pct = calculate_unrealized_pnl(pos, spot["price"])
                    if pnl_pct <= -args.threshold:
                        if monitor_state.can_send_warning(pos.position_id, args.warning_cooldown):
                            await notifier.send_message(_build_pnl_warning(pos, spot, pnl_dollar, pnl_pct))
                            monitor_state.update_warning(pos.position_id)
                            logger.warning(f"P&L 경고: {pos.symbol} ({pnl_pct * 100:+.2f}%)")

                monitor_state.save()
                logger.info("모니터링 완료")

    except asyncio.TimeoutError:
        logger.error(f"모니터링 타임아웃 ({SCRIPT_TIMEOUT}초)")
        try:
            await notifier.send_message(
                NotificationMessage(
                    title="MONITOR TIMEOUT",
                    body=f"장중 모니터링 타임아웃 ({SCRIPT_TIMEOUT}초). 확인 필요.",
                    level=NotificationLevel.ERROR,
                    data={"action": "CHECK_MONITOR"},
                )
            )
        except Exception:
            pass  # notifier 미초기화(NameError) 또는 전송 실패
    except Exception as e:
        logger.error(f"모니터링 오류: {e}", exc_info=True)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def main():
    parser = argparse.ArgumentParser(description="포지션 장중 모니터링")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="미실현 손실 임계값 (기본값: 0.05 = 5%%)",
    )
    parser.add_argument(
        "--warning-cooldown",
        type=int,
        default=60,
        help="미실현 손실 경고 쿨다운 (분, 기본: 60)",
    )
    parser.add_argument("--verbose", action="store_true", help="상세 로깅 활성화")

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)
    logger.info("=== 포지션 장중 모니터링 시작 ===")
    asyncio.run(monitor_positions(args))


if __name__ == "__main__":
    main()
