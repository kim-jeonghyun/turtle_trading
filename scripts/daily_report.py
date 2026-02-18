#!/usr/bin/env python3
"""
일일 리포트 생성 및 전송 스크립트
"""

import asyncio
import logging
from datetime import datetime, timedelta

from src.data_store import ParquetDataStore
from src.notifier import (
    NotificationManager,
    TelegramChannel,
    DiscordChannel,
    EmailChannel,
    NotificationMessage,
    NotificationLevel
)
from src.position_tracker import PositionTracker
from src.risk_manager import PortfolioRiskManager
from src.analytics import TradeAnalytics
from src.market_calendar import get_market_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config():
    import os
    try:
        from dotenv import load_dotenv
    except ImportError:
        def load_dotenv(): pass
    load_dotenv()

    return {
        "telegram_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL"),
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "email_user": os.getenv("EMAIL_USER"),
        "email_pass": os.getenv("EMAIL_PASSWORD"),
        "email_to": os.getenv("EMAIL_TO", "").split(",")
    }


def setup_notifier(config: dict) -> NotificationManager:
    notifier = NotificationManager()

    if config.get("telegram_token") and config.get("telegram_chat_id"):
        notifier.add_channel(TelegramChannel(
            config["telegram_token"],
            config["telegram_chat_id"]
        ))

    if config.get("discord_webhook"):
        notifier.add_channel(DiscordChannel(config["discord_webhook"]))

    if config.get("email_user") and config.get("email_to"):
        notifier.add_channel(EmailChannel(
            config["smtp_host"],
            config["smtp_port"],
            config["email_user"],
            config["email_pass"],
            config["email_user"],
            config["email_to"]
        ))

    return notifier


def generate_report(
    data_store: ParquetDataStore,
    tracker: PositionTracker = None,
    risk_manager: PortfolioRiskManager = None
) -> dict:
    """Enhanced 일일 리포트 데이터 생성"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 오늘 시그널
    today_signals = data_store.load_signals(today.replace("-", ""))
    signal_count = len(today_signals) if not today_signals.empty else 0

    # 최근 30일 거래
    trades = data_store.load_trades(
        start_date=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
        end_date=today
    )

    if not trades.empty:
        total_trades = len(trades)
        winning_trades = len(trades[trades["pnl"] > 0])
        total_pnl = trades["pnl"].sum()
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
    else:
        total_trades = 0
        winning_trades = 0
        total_pnl = 0
        win_rate = 0

    # 캐시 상태
    cache_stats = data_store.get_cache_stats()

    # 마켓 상태
    try:
        kr_status = get_market_status("KR")
        us_status = get_market_status("US")
        market_status_text = f"KR: {kr_status} | US: {us_status}"
    except Exception as e:
        logger.warning(f"마켓 상태 조회 실패: {e}")
        market_status_text = "마켓 상태 조회 불가"

    # 오픈 포지션 (PositionTracker가 전달된 경우)
    open_positions = []
    position_data = []
    if tracker is not None:
        try:
            open_positions = tracker.get_open_positions()
            for pos in open_positions:
                position_data.append({
                    "symbol": pos.symbol,
                    "system": pos.system,
                    "entry_price": pos.entry_price,
                    "units": pos.units,
                    "direction": pos.direction,
                })
        except Exception as e:
            logger.warning(f"오픈 포지션 조회 실패: {e}")

    # 리스크 요약 (PortfolioRiskManager가 전달된 경우)
    risk_summary = {}
    if risk_manager is not None:
        try:
            risk_summary = risk_manager.get_risk_summary()
        except Exception as e:
            logger.warning(f"리스크 요약 조회 실패: {e}")

    # R-배수 분포 (최근 30일 거래 기반)
    r_distribution = {}
    system_comparison = {}
    if not trades.empty:
        try:
            # DataFrame을 딕셔너리 리스트로 변환
            recent_trade_dicts = trades.to_dict(orient="records")
            analytics = TradeAnalytics(recent_trade_dicts)
            r_distribution = analytics.get_r_distribution()
            system_comparison = analytics.get_system_comparison()
        except Exception as e:
            logger.warning(f"R-배수 분석 실패: {e}")

    return {
        "날짜": today,
        "마켓 상태": market_status_text,
        "오늘 시그널": signal_count,
        "오픈 포지션": len(open_positions),
        "포지션 상세": position_data,
        "리스크 요약": risk_summary,
        "30일 거래수": total_trades,
        "30일 승률": f"{win_rate:.1f}%",
        "30일 수익": f"${total_pnl:,.2f}",
        "R배수 분포": r_distribution,
        "시스템 비교": system_comparison,
        "캐시 파일": cache_stats["cache_files"],
        "데이터 크기": f"{cache_stats['total_size_mb']:.1f}MB"
    }


async def main():
    logger.info("=== 일일 리포트 생성 시작 ===")

    config = load_config()
    notifier = setup_notifier(config)
    data_store = ParquetDataStore()

    # 추가 모듈 인스턴스화
    tracker = PositionTracker()
    risk_manager = PortfolioRiskManager()

    # 리포트 생성
    report_data = generate_report(data_store, tracker, risk_manager)
    logger.info(f"리포트 데이터: {report_data}")

    # 알림 전송
    await notifier.send_daily_report(report_data)

    # 오래된 캐시 정리
    data_store.cleanup_old_cache(max_age_days=7)

    logger.info("=== 일일 리포트 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
