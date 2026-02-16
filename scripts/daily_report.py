#!/usr/bin/env python3
"""
일일 리포트 생성 및 전송 스크립트
"""

import sys
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_store import ParquetDataStore
from src.notifier import (
    NotificationManager,
    TelegramChannel,
    DiscordChannel,
    EmailChannel,
    NotificationMessage,
    NotificationLevel
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config():
    import os
    from dotenv import load_dotenv
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


def generate_report(data_store: ParquetDataStore) -> dict:
    """일일 리포트 데이터 생성"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 오늘 시그널
    today_signals = data_store.load_signals(today.replace("-", ""))
    signal_count = len(today_signals) if not today_signals.empty else 0

    # 최근 거래
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

    return {
        "날짜": today,
        "오늘 시그널": signal_count,
        "30일 거래수": total_trades,
        "30일 승률": f"{win_rate:.1f}%",
        "30일 수익": f"${total_pnl:,.2f}",
        "캐시 파일": cache_stats["cache_files"],
        "데이터 크기": f"{cache_stats['total_size_mb']:.1f}MB"
    }


async def main():
    logger.info("=== 일일 리포트 생성 시작 ===")

    config = load_config()
    notifier = setup_notifier(config)
    data_store = ParquetDataStore()

    # 리포트 생성
    report_data = generate_report(data_store)
    logger.info(f"리포트 데이터: {report_data}")

    # 알림 전송
    await notifier.send_daily_report(report_data)

    # 오래된 캐시 정리
    data_store.cleanup_old_cache(max_age_days=7)

    logger.info("=== 일일 리포트 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
