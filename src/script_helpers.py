"""
스크립트 공통 유틸리티 모듈
- 환경변수 기반 설정 로드
- 알림 채널 설정
- 리스크 매니저 통합 설정
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from src.kis_api import KISConfig

import yaml  # type: ignore[import-untyped]

from src.notifier import (
    DiscordChannel,
    EmailChannel,
    NotificationManager,
    TelegramChannel,
)
from src.risk_manager import PortfolioRiskManager
from src.types import AssetGroup

logger = logging.getLogger(__name__)

# correlation_groups.yaml 그룹명 → AssetGroup 매핑
# Note: correlation_groups.yaml의 실제 그룹명과 1:1 대응
# us_etf, crypto: 현재 YAML에 없으나 향후 그룹 추가 시 호환용 placeholder
_GROUP_MAPPING: dict[str, AssetGroup] = {
    "us_equity": AssetGroup.US_EQUITY,
    "us_etf": AssetGroup.US_EQUITY,
    "us_tech": AssetGroup.US_EQUITY,
    "kr_equity": AssetGroup.KR_EQUITY,
    "asia_equity": AssetGroup.ASIA_EQUITY,
    "china_equity": AssetGroup.CHINA_EQUITY,
    "eu_equity": AssetGroup.EU_EQUITY,
    "crypto": AssetGroup.CRYPTO,
    "commodity": AssetGroup.COMMODITY,
    "commodity_metal": AssetGroup.COMMODITY,
    "commodity_industrial": AssetGroup.COMMODITY,
    "commodity_energy": AssetGroup.COMMODITY_ENERGY,
    "commodity_agri": AssetGroup.COMMODITY_AGRI,
    "bond": AssetGroup.BOND,
    "inverse": AssetGroup.INVERSE,
    "currency": AssetGroup.CURRENCY,
    "reit": AssetGroup.REIT,
    "alternatives": AssetGroup.ALTERNATIVES,
}


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
        "kis_app_key": os.getenv("KIS_APP_KEY"),
        "kis_app_secret": os.getenv("KIS_APP_SECRET"),
        "kis_account_no": os.getenv("KIS_ACCOUNT_NO"),
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

    if config.get("email_user") and config.get("email_pass") and config.get("email_to"):
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


def setup_risk_manager(config_path: Optional[Path] = None) -> PortfolioRiskManager:
    """correlation_groups.yaml을 로드하여 PortfolioRiskManager 생성.

    모든 스크립트가 동일한 그룹 매핑을 사용하도록 보장.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "correlation_groups.yaml"

    symbol_groups: dict[str, AssetGroup] = {}

    if not config_path.exists():
        logger.warning(f"상관그룹 설정 파일 없음: {config_path}. 기본 그룹으로 운영합니다.")
        return PortfolioRiskManager(symbol_groups=symbol_groups)

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)

        if not config or "groups" not in config:
            logger.warning("상관그룹 설정이 비어있습니다.")
            return PortfolioRiskManager(symbol_groups=symbol_groups)

        for group_name, symbols in config.get("groups", {}).items():
            asset_group = _GROUP_MAPPING.get(group_name)
            if asset_group is None:
                logger.warning(f"Unknown correlation group '{group_name}', defaulting to US_EQUITY")
                asset_group = AssetGroup.US_EQUITY
            for symbol in symbols:
                symbol_groups[symbol] = asset_group

        logger.info(f"상관그룹 설정 로드: {len(symbol_groups)}개 심볼")

    except yaml.YAMLError as e:
        logger.error(f"상관그룹 YAML 파싱 오류: {e}. 기본 그룹으로 운영합니다.")

    return PortfolioRiskManager(symbol_groups=symbol_groups)


def create_kis_client(config: Dict[str, Any]) -> Optional[KISConfig]:
    """환경변수에서 KIS API 설정 조립. 미설정 시 None 반환."""
    from src.kis_api import KISConfig

    app_key = config.get("kis_app_key") or os.getenv("KIS_APP_KEY")
    app_secret = config.get("kis_app_secret") or os.getenv("KIS_APP_SECRET")
    account_no = config.get("kis_account_no") or os.getenv("KIS_ACCOUNT_NO")
    if not all([app_key, app_secret, account_no]):
        logger.warning("KIS API 미설정 — yfinance fallback 사용")
        return None
    assert isinstance(app_key, str)  # guaranteed by all() check above
    assert isinstance(app_secret, str)
    assert isinstance(account_no, str)
    return KISConfig(
        app_key=app_key,
        app_secret=app_secret,
        account_no=account_no,
        is_real=os.getenv("KIS_IS_REAL", "false").lower() == "true",
    )
