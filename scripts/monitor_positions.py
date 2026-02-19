#!/usr/bin/env python3
"""
포지션 실시간 모니터링 - cron으로 주기적 실행
- 오픈 포지션을 현재 가격으로 체크
- 스톱로스 발동 시 알림
- 미실현 손실이 임계값을 초과하면 알림
"""

import argparse
import asyncio
import logging
import os
from datetime import datetime

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv():
        pass


from src.data_fetcher import DataFetcher
from src.notifier import NotificationLevel, NotificationManager, NotificationMessage, TelegramChannel
from src.position_tracker import Position, PositionTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_config():
    """환경 변수에서 설정 로드"""
    load_dotenv()
    return {
        "telegram_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
    }


def setup_notifier(config: dict) -> NotificationManager:
    """알림 채널 설정"""
    notifier = NotificationManager()

    if config.get("telegram_token") and config.get("telegram_chat_id"):
        notifier.add_channel(TelegramChannel(config["telegram_token"], config["telegram_chat_id"]))
        logger.info("Telegram 채널 활성화")

    return notifier


def calculate_unrealized_pnl(position: Position, current_price: float) -> tuple:
    """
    미실현 손익 계산

    Returns:
        (pnl_dollar, pnl_percent)
    """
    if position.direction == "LONG":
        pnl_dollar = (current_price - position.entry_price) * position.total_shares
        pnl_percent = (current_price - position.entry_price) / position.entry_price
    else:  # SHORT
        pnl_dollar = (position.entry_price - current_price) * position.total_shares
        pnl_percent = (position.entry_price - current_price) / position.entry_price

    return pnl_dollar, pnl_percent


def format_position_status(position: Position, current_price: float) -> str:
    """포지션 상태를 포맷된 문자열로 반환"""
    pnl_dollar, pnl_percent = calculate_unrealized_pnl(position, current_price)

    status_lines = [
        f"심볼: {position.symbol}",
        f"시스템: System {position.system}",
        f"방향: {position.direction}",
        f"진입가: {position.entry_price:,.2f}",
        f"현재가: {current_price:,.2f}",
        f"유닛: {position.units}/{position.max_units}",
        f"수량: {position.total_shares}",
        f"미실현손익: ${pnl_dollar:,.2f} ({pnl_percent * 100:+.2f}%)",
        f"스톱로스: {position.stop_loss:,.2f}",
        f"진입일: {position.entry_date}",
    ]

    return "\n".join(status_lines)


async def monitor_single_position(
    position: Position,
    data_fetcher: DataFetcher,
    notifier: NotificationManager,
    threshold: float,
    verbose: bool = False,
) -> bool:
    """
    개별 포지션 모니터링

    Args:
        position: 모니터링할 포지션
        data_fetcher: 데이터 페칭 객체
        notifier: 알림 매니저
        threshold: 미실현 손실 임계값 (0.05 = 5%)
        verbose: 상세 로깅 여부

    Returns:
        문제 발생 여부
    """
    try:
        # 현재 가격 페칭
        df = data_fetcher.fetch(position.symbol, period="1d")
        if df is None or df.empty:
            logger.warning(f"데이터 없음: {position.symbol}")
            return False

        current_price = df.iloc[-1]["close"]
        pnl_dollar, pnl_percent = calculate_unrealized_pnl(position, current_price)

        if verbose:
            logger.info(f"{position.symbol}: {current_price:,.2f} (PnL: {pnl_percent * 100:+.2f}%)")

        # 1. 스톱로스 체크
        if position.direction == "LONG" and current_price <= position.stop_loss:
            logger.error(f"스톱로스 발동: {position.symbol} @ {current_price:,.2f}")

            position_info = format_position_status(position, current_price)
            await notifier.send_message(
                NotificationMessage(
                    title="🛑 STOP LOSS TRIGGERED",
                    body=f"스톱로스가 발동되었습니다!\n\n{position_info}",
                    level=NotificationLevel.ERROR,
                    data={
                        "action": "CLOSE_POSITION_IMMEDIATELY",
                        "symbol": position.symbol,
                        "exit_price": current_price,
                        "loss": f"${pnl_dollar:,.2f}",
                    },
                )
            )
            return True

        elif position.direction == "SHORT" and current_price >= position.stop_loss:
            logger.error(f"스톱로스 발동: {position.symbol} @ {current_price:,.2f}")

            position_info = format_position_status(position, current_price)
            await notifier.send_message(
                NotificationMessage(
                    title="🛑 STOP LOSS TRIGGERED",
                    body=f"스톱로스가 발동되었습니다!\n\n{position_info}",
                    level=NotificationLevel.ERROR,
                    data={
                        "action": "CLOSE_POSITION_IMMEDIATELY",
                        "symbol": position.symbol,
                        "exit_price": current_price,
                        "loss": f"${pnl_dollar:,.2f}",
                    },
                )
            )
            return True

        # 2. 미실현 손실 임계값 체크
        if pnl_percent < -threshold:
            logger.warning(f"미실현 손실 임계값 초과: {position.symbol} ({pnl_percent * 100:.2f}%)")

            position_info = format_position_status(position, current_price)
            await notifier.send_message(
                NotificationMessage(
                    title="⚠️ UNREALIZED LOSS THRESHOLD",
                    body=f"미실현 손실이 {threshold * 100:.1f}%를 초과했습니다.\n\n{position_info}",
                    level=NotificationLevel.WARNING,
                    data={"unrealized_loss_pct": f"{pnl_percent * 100:.2f}%", "threshold": f"{-threshold * 100:.1f}%"},
                )
            )
            return True

        return False

    except Exception as e:
        logger.error(f"{position.symbol} 모니터링 오류: {e}", exc_info=True)
        return False


async def main(args):
    """메인 함수"""
    logger.info("=== 포지션 모니터링 시작 ===")

    config = load_config()
    notifier = setup_notifier(config)
    data_fetcher = DataFetcher()
    tracker = PositionTracker()

    # 오픈 포지션 로드
    try:
        open_positions = tracker.get_open_positions()
        logger.info(f"오픈 포지션: {len(open_positions)}개")

        if not open_positions:
            logger.info("오픈 포지션 없음")
            return

    except Exception as e:
        logger.error(f"포지션 로드 오류: {e}")
        await notifier.send_message(
            NotificationMessage(
                title="❌ Position Monitor Error",
                body=f"포지션을 로드할 수 없습니다.\n\n{str(e)}",
                level=NotificationLevel.ERROR,
            )
        )
        return

    # 각 포지션 모니터링
    problems_found = False
    for position in open_positions:
        try:
            has_problem = await monitor_single_position(position, data_fetcher, notifier, args.threshold, args.verbose)
            if has_problem:
                problems_found = True

        except Exception as e:
            logger.error(f"{position.symbol} 처리 오류: {e}", exc_info=True)

    # 요약 리포트
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_positions": len(open_positions),
        "problems_found": problems_found,
        "threshold": f"{args.threshold * 100:.1f}%",
    }

    if problems_found:
        logger.warning("⚠️  문제 있는 포지션이 발견되었습니다")
    else:
        logger.info("✓ 모든 포지션 정상")

    if args.verbose:
        logger.info(f"요약: {summary}")

    logger.info("=== 모니터링 완료 ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="포지션 실시간 모니터링")
    parser.add_argument("--threshold", type=float, default=0.05, help="미실현 손실 임계값 (기본값: 0.05 = 5%%)")
    parser.add_argument("--verbose", action="store_true", help="상세 로깅 활성화")

    args = parser.parse_args()

    asyncio.run(main(args))
