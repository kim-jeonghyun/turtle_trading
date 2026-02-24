"""
스크립트 공통 유틸리티 모듈
- 환경변수 기반 설정 로드
- 알림 채널 설정
"""

import logging
import os
from typing import Any, Dict

from src.notifier import (
    DiscordChannel,
    EmailChannel,
    NotificationManager,
    TelegramChannel,
)

logger = logging.getLogger(__name__)


def load_config() -> Dict[str, Any]:
    """환경 변수에서 알림 설정을 로드한다.

    .env 파일이 있으면 자동 로드. python-dotenv가 없어도 동작.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    return {
        "telegram_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL"),
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "email_user": os.getenv("EMAIL_USER"),
        "email_pass": os.getenv("EMAIL_PASSWORD"),
        "email_to": [addr for addr in os.getenv("EMAIL_TO", "").split(",") if addr],
    }


def setup_notifier(config: Dict[str, Any]) -> NotificationManager:
    """설정 딕셔너리로 NotificationManager를 구성한다.

    각 채널은 필수 키가 모두 설정된 경우에만 활성화된다.
    """
    notifier = NotificationManager()

    if config.get("telegram_token") and config.get("telegram_chat_id"):
        notifier.add_channel(TelegramChannel(config["telegram_token"], config["telegram_chat_id"]))
        logger.info("Telegram 채널 활성화")

    if config.get("discord_webhook"):
        notifier.add_channel(DiscordChannel(config["discord_webhook"]))
        logger.info("Discord 채널 활성화")

    if config.get("email_user") and config.get("email_to"):
        notifier.add_channel(
            EmailChannel(
                config["smtp_host"],
                config["smtp_port"],
                config["email_user"],
                config["email_pass"],
                config["email_user"],
                config["email_to"],
            )
        )
        logger.info("Email 채널 활성화")

    return notifier
