#!/usr/bin/env python3
"""
터틀 트레이딩 시그널 체크 스크립트
- Cron으로 매일 실행
- 시그널 발생 시 알림 전송
"""

import sys
import asyncio
import logging
from pathlib import Path
from datetime import datetime

# 상위 디렉토리 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_fetcher import DataFetcher
from src.data_store import ParquetDataStore
from src.indicators import add_turtle_indicators
from src.universe_manager import UniverseManager
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
    """환경 변수에서 설정 로드"""
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
    """알림 채널 설정"""
    notifier = NotificationManager()

    if config.get("telegram_token") and config.get("telegram_chat_id"):
        notifier.add_channel(TelegramChannel(
            config["telegram_token"],
            config["telegram_chat_id"]
        ))
        logger.info("Telegram 채널 추가")

    if config.get("discord_webhook"):
        notifier.add_channel(DiscordChannel(config["discord_webhook"]))
        logger.info("Discord 채널 추가")

    if config.get("email_user") and config.get("email_to"):
        notifier.add_channel(EmailChannel(
            config["smtp_host"],
            config["smtp_port"],
            config["email_user"],
            config["email_pass"],
            config["email_user"],
            config["email_to"]
        ))
        logger.info("Email 채널 추가")

    return notifier


def check_signals(df, symbol: str, system: int = 1) -> list:
    """시그널 확인"""
    signals = []
    if len(df) < 2:
        return signals

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    # System 1: 20일 돌파
    # System 2: 55일 돌파
    if system == 1:
        high_col, low_col = "dc_high_20", "dc_low_20"
        exit_low, exit_high = "dc_low_10", "dc_high_10"
    else:
        high_col, low_col = "dc_high_55", "dc_low_55"
        exit_low, exit_high = "dc_low_20", "dc_high_20"

    # 롱 진입 시그널
    if today["high"] > yesterday[high_col]:
        signals.append({
            "symbol": symbol,
            "type": "ENTRY_LONG",
            "price": yesterday[high_col],
            "current": today["close"],
            "n": today["N"],
            "message": f"System {system} 롱 진입: {yesterday[high_col]:.2f} 돌파"
        })

    # 숏 진입 시그널
    if today["low"] < yesterday[low_col]:
        signals.append({
            "symbol": symbol,
            "type": "ENTRY_SHORT",
            "price": yesterday[low_col],
            "current": today["close"],
            "n": today["N"],
            "message": f"System {system} 숏 진입: {yesterday[low_col]:.2f} 이탈"
        })

    return signals


async def main():
    logger.info("=== 터틀 트레이딩 시그널 체크 시작 ===")

    config = load_config()
    notifier = setup_notifier(config)
    data_fetcher = DataFetcher()
    data_store = ParquetDataStore()

    # 유니버스 로드
    universe_path = Path(__file__).parent.parent / "data" / "turtle_universe_full.csv"
    universe = UniverseManager(str(universe_path) if universe_path.exists() else None)
    symbols = universe.get_enabled_symbols()

    logger.info(f"대상 종목: {len(symbols)}개")

    all_signals = []

    for symbol in symbols:
        try:
            # 캐시 확인
            df = data_store.load_ohlcv(symbol, max_age_hours=4)
            if df is None:
                df = data_fetcher.fetch(symbol, period="6mo")
                if not df.empty:
                    data_store.save_ohlcv(symbol, df)

            if df is None or df.empty:
                continue

            # 지표 계산
            df = add_turtle_indicators(df)

            # 시그널 체크 (System 1 & 2)
            signals_s1 = check_signals(df, symbol, system=1)
            signals_s2 = check_signals(df, symbol, system=2)

            all_signals.extend(signals_s1)
            all_signals.extend(signals_s2)

        except Exception as e:
            logger.error(f"{symbol} 처리 오류: {e}")

    # 시그널 저장 및 알림
    if all_signals:
        logger.info(f"발견된 시그널: {len(all_signals)}개")

        for signal in all_signals:
            # 시그널 저장
            data_store.save_signal({
                **signal,
                "timestamp": datetime.now().isoformat()
            })

            # 알림 전송
            await notifier.send_signal(
                symbol=signal["symbol"],
                action=signal["type"],
                price=signal["price"],
                quantity=0,  # 실제 수량은 사용자가 결정
                reason=signal["message"]
            )

    else:
        logger.info("오늘 발생한 시그널 없음")

    logger.info("=== 시그널 체크 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
