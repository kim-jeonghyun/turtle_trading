"""
알림 시스템 모듈
- Telegram
- Discord
- Email
- 재시도 (retry) 및 에스컬레이션 로직
"""

import asyncio
import html as html_lib
import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from src.utils import retry_async

logger = logging.getLogger(__name__)


class NotificationLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    SIGNAL = "signal"
    ERROR = "error"


@dataclass
class NotificationMessage:
    title: str
    body: str
    level: NotificationLevel = NotificationLevel.INFO
    data: Optional[Dict[str, Any]] = None


class NotificationChannel(ABC):
    @abstractmethod
    async def send(self, message: NotificationMessage) -> bool:
        pass


class TelegramChannel(NotificationChannel):
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def _format_message(self, message: NotificationMessage) -> str:
        emoji_map = {
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.SIGNAL: "🚨",
            NotificationLevel.ERROR: "❌",
        }
        emoji = emoji_map.get(message.level, "📢")
        text = f"{emoji} *{message.title}*\n\n{message.body}"
        if message.data:
            text += "\n\n```\n"
            for k, v in message.data.items():
                text += f"{k}: {v}\n"
            text += "```"
        return text

    @retry_async(max_retries=2, base_delay=1.0)
    async def _send_with_retry(self, message: NotificationMessage) -> bool:
        """재시도 로직을 포함한 실제 전송 (예외를 그대로 전파하여 retry가 동작)"""
        text = self._format_message(message)
        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    logger.info(f"Telegram 전송 성공: {message.title}")
                    return True
                else:
                    raise RuntimeError(f"Telegram 전송 실패: HTTP {resp.status}")

    async def send(self, message: NotificationMessage) -> bool:
        try:
            return await self._send_with_retry(message)
        except Exception as e:
            logger.error(f"Telegram 오류 (모든 재시도 소진): {e}")
            return False


_DISCORD_ALLOWED_HOSTS = ("discord.com", "discordapp.com")


class DiscordChannel(NotificationChannel):
    def __init__(self, webhook_url: str):
        parsed = urlparse(webhook_url)
        if parsed.scheme != "https":
            raise ValueError(f"Discord webhook URL must use HTTPS, got: {parsed.scheme!r}")
        if parsed.hostname not in _DISCORD_ALLOWED_HOSTS:
            raise ValueError(f"Invalid Discord webhook URL domain: {parsed.hostname}")
        if not parsed.path.startswith("/api/webhooks/"):
            raise ValueError(f"Invalid Discord webhook path: {parsed.path!r}")
        self.webhook_url = webhook_url

    def _format_embed(self, message: NotificationMessage) -> Dict:
        color_map = {
            NotificationLevel.INFO: 0x3498DB,
            NotificationLevel.WARNING: 0xF39C12,
            NotificationLevel.SIGNAL: 0xE74C3C,
            NotificationLevel.ERROR: 0x992D22,
        }
        embed = {"title": message.title, "description": message.body, "color": color_map.get(message.level, 0x95A5A6)}
        if message.data:
            embed["fields"] = [{"name": k, "value": str(v), "inline": True} for k, v in message.data.items()]
        return embed

    @retry_async(max_retries=2, base_delay=1.0)
    async def _send_with_retry(self, message: NotificationMessage) -> bool:
        """재시도 로직을 포함한 실제 전송 (예외를 그대로 전파하여 retry가 동작)"""
        payload = {"embeds": [self._format_embed(message)]}
        async with aiohttp.ClientSession() as session:
            async with session.post(self.webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    logger.info(f"Discord 전송 성공: {message.title}")
                    return True
                else:
                    raise RuntimeError(f"Discord 전송 실패: HTTP {resp.status}")

    async def send(self, message: NotificationMessage) -> bool:
        try:
            return await self._send_with_retry(message)
        except Exception as e:
            logger.error(f"Discord 오류 (모든 재시도 소진): {e}")
            return False


class EmailChannel(NotificationChannel):
    def __init__(
        self, smtp_host: str, smtp_port: int, username: str, password: str, from_addr: str, to_addrs: List[str]
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs

    def _format_html(self, message: NotificationMessage) -> str:
        html = f"""
        <html>
        <body>
        <h2>{html_lib.escape(message.title)}</h2>
        <p>{html_lib.escape(message.body)}</p>
        """
        if message.data:
            html += "<table border='1' cellpadding='5'>"
            for k, v in message.data.items():
                html += f"<tr><td><b>{html_lib.escape(str(k))}</b></td><td>{html_lib.escape(str(v))}</td></tr>"
            html += "</table>"
        html += "</body></html>"
        return html

    @retry_async(max_retries=2, base_delay=1.0)
    async def _send_with_retry(self, message: NotificationMessage) -> bool:
        """재시도 로직을 포함한 실제 전송 (예외를 그대로 전파하여 retry가 동작)"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Turtle] {message.title}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)

        html_content = self._format_html(message)
        msg.attach(MIMEText(message.body, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._send_email, msg)
        logger.info(f"Email 전송 성공: {message.title}")
        return True

    async def send(self, message: NotificationMessage) -> bool:
        try:
            return await self._send_with_retry(message)
        except Exception as e:
            logger.error(f"Email 오류 (모든 재시도 소진): {e}")
            return False

    def _send_email(self, msg: MIMEMultipart):
        context = ssl.create_default_context()
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
            server.starttls(context=context)
            server.login(self.username, self.password)
            server.send_message(msg)


class NotificationManager:
    def __init__(self):
        self.channels: List[NotificationChannel] = []
        # 채널별 성공/실패 카운터
        self._health: Dict[str, Dict[str, int]] = {}

    def add_channel(self, channel: NotificationChannel):
        self.channels.append(channel)
        channel_name = channel.__class__.__name__
        if channel_name not in self._health:
            self._health[channel_name] = {"success": 0, "failure": 0}

    async def send_all(self, message: NotificationMessage) -> Dict[str, bool]:
        """모든 채널에 병렬 전송; ERROR 레벨 시 전체 실패 시 CRITICAL 로그"""
        if not self.channels:
            return {}

        channel_names = [ch.__class__.__name__ for ch in self.channels]
        tasks = [ch.send(message) for ch in self.channels]

        # 병렬 전송
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        results: Dict[str, bool] = {}
        for name, result in zip(channel_names, results_list):
            if isinstance(result, Exception):
                success = False
            else:
                success = bool(result)
            results[name] = success
            # 건강 지표 업데이트
            if name not in self._health:
                self._health[name] = {"success": 0, "failure": 0}
            if success:
                self._health[name]["success"] += 1
            else:
                self._health[name]["failure"] += 1

        # ERROR 레벨이고 모든 채널이 실패하면 CRITICAL 로그
        if message.level == NotificationLevel.ERROR and not any(results.values()):
            logger.critical(f"[ESCALATION] 모든 알림 채널 전송 실패: {message.title} - 채널: {list(results.keys())}")

        return results

    def get_channel_health(self) -> Dict[str, Dict[str, int]]:
        """채널별 성공/실패 횟수 반환"""
        return dict(self._health)

    async def send_with_escalation(self, message: NotificationMessage) -> Dict[str, bool]:
        """
        레벨에 따른 에스컬레이션 전송:
        - INFO/WARNING: 첫 번째 사용 가능한 채널에만 전송
        - SIGNAL: 모든 채널에 전송
        - ERROR: 모든 채널에 전송, 1차 실패 시 나머지 채널로 재시도
        """
        if not self.channels:
            return {}

        if message.level in (NotificationLevel.INFO, NotificationLevel.WARNING):
            # 첫 번째 채널에만 시도
            for channel in self.channels:
                name = channel.__class__.__name__
                success = await channel.send(message)
                if name not in self._health:
                    self._health[name] = {"success": 0, "failure": 0}
                if success:
                    self._health[name]["success"] += 1
                    return {name: True}
                else:
                    self._health[name]["failure"] += 1
            return {}

        if message.level == NotificationLevel.SIGNAL:
            return await self.send_all(message)

        if message.level == NotificationLevel.ERROR:
            results = await self.send_all(message)
            # 전체 실패 시 이미 send_all에서 CRITICAL 처리됨
            return results

        # 기타 레벨은 send_all
        return await self.send_all(message)

    async def send_message(self, message: "NotificationMessage") -> Dict[str, bool]:
        """send_with_escalation alias for backward compatibility"""
        return await self.send_with_escalation(message)

    async def send_signal(self, symbol: str, action: str, price: float, quantity: int, reason: str):
        message = NotificationMessage(
            title=f"매매 시그널: {symbol}",
            body=f"{action} 신호 발생\n사유: {reason}",
            level=NotificationLevel.SIGNAL,
            data={"종목": symbol, "액션": action, "가격": f"{price:,.2f}", "수량": quantity},
        )
        return await self.send_all(message)

    async def send_daily_report(self, report_data: Dict):
        message = NotificationMessage(
            title="일일 리포트", body="오늘의 포트폴리오 현황입니다.", level=NotificationLevel.INFO, data=report_data
        )
        return await self.send_all(message)
