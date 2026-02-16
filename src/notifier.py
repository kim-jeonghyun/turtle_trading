"""
알림 시스템 모듈
- Telegram
- Discord
- Email
"""

import asyncio
import aiohttp
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum
import logging

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
            NotificationLevel.ERROR: "❌"
        }
        emoji = emoji_map.get(message.level, "📢")
        text = f"{emoji} *{message.title}*\n\n{message.body}"
        if message.data:
            text += "\n\n```\n"
            for k, v in message.data.items():
                text += f"{k}: {v}\n"
            text += "```"
        return text

    async def send(self, message: NotificationMessage) -> bool:
        text = self._format_message(message)
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(f"Telegram 전송 성공: {message.title}")
                        return True
                    else:
                        logger.error(f"Telegram 전송 실패: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Telegram 오류: {e}")
            return False


class DiscordChannel(NotificationChannel):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def _format_embed(self, message: NotificationMessage) -> Dict:
        color_map = {
            NotificationLevel.INFO: 0x3498db,
            NotificationLevel.WARNING: 0xf39c12,
            NotificationLevel.SIGNAL: 0xe74c3c,
            NotificationLevel.ERROR: 0x992d22
        }
        embed = {
            "title": message.title,
            "description": message.body,
            "color": color_map.get(message.level, 0x95a5a6)
        }
        if message.data:
            embed["fields"] = [
                {"name": k, "value": str(v), "inline": True}
                for k, v in message.data.items()
            ]
        return embed

    async def send(self, message: NotificationMessage) -> bool:
        payload = {"embeds": [self._format_embed(message)]}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status in (200, 204):
                        logger.info(f"Discord 전송 성공: {message.title}")
                        return True
                    else:
                        logger.error(f"Discord 전송 실패: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Discord 오류: {e}")
            return False


class EmailChannel(NotificationChannel):
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: List[str]
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
        <h2>{message.title}</h2>
        <p>{message.body}</p>
        """
        if message.data:
            html += "<table border='1' cellpadding='5'>"
            for k, v in message.data.items():
                html += f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
            html += "</table>"
        html += "</body></html>"
        return html

    async def send(self, message: NotificationMessage) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[Turtle] {message.title}"
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)

            html_content = self._format_html(message)
            msg.attach(MIMEText(message.body, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_email, msg)
            logger.info(f"Email 전송 성공: {message.title}")
            return True
        except Exception as e:
            logger.error(f"Email 오류: {e}")
            return False

    def _send_email(self, msg: MIMEMultipart):
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.send_message(msg)


class NotificationManager:
    def __init__(self):
        self.channels: List[NotificationChannel] = []

    def add_channel(self, channel: NotificationChannel):
        self.channels.append(channel)

    async def send_all(self, message: NotificationMessage) -> Dict[str, bool]:
        results = {}
        tasks = []
        for channel in self.channels:
            channel_name = channel.__class__.__name__
            tasks.append((channel_name, channel.send(message)))

        for channel_name, task in tasks:
            results[channel_name] = await task
        return results

    async def send_signal(
        self,
        symbol: str,
        action: str,
        price: float,
        quantity: int,
        reason: str
    ):
        message = NotificationMessage(
            title=f"매매 시그널: {symbol}",
            body=f"{action} 신호 발생\n사유: {reason}",
            level=NotificationLevel.SIGNAL,
            data={
                "종목": symbol,
                "액션": action,
                "가격": f"{price:,.2f}",
                "수량": quantity
            }
        )
        return await self.send_all(message)

    async def send_daily_report(self, report_data: Dict):
        message = NotificationMessage(
            title="일일 리포트",
            body="오늘의 포트폴리오 현황입니다.",
            level=NotificationLevel.INFO,
            data=report_data
        )
        return await self.send_all(message)
