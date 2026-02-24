"""
notifier.py 단위 테스트
- NotificationLevel, NotificationMessage 데이터 타입
- TelegramChannel, DiscordChannel 포매팅
- EmailChannel HTML 포매팅
- NotificationManager 채널 관리
"""

import smtplib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.notifier import (
    DiscordChannel,
    EmailChannel,
    NotificationLevel,
    NotificationManager,
    NotificationMessage,
    TelegramChannel,
)


class TestNotificationLevel:
    def test_all_levels(self):
        assert NotificationLevel.INFO.value == "info"
        assert NotificationLevel.WARNING.value == "warning"
        assert NotificationLevel.SIGNAL.value == "signal"
        assert NotificationLevel.ERROR.value == "error"


class TestNotificationMessage:
    def test_basic_message(self):
        msg = NotificationMessage(title="Test", body="Hello")
        assert msg.title == "Test"
        assert msg.body == "Hello"
        assert msg.level == NotificationLevel.INFO
        assert msg.data is None

    def test_message_with_data(self):
        msg = NotificationMessage(
            title="Signal",
            body="Buy SPY",
            level=NotificationLevel.SIGNAL,
            data={"price": 500.0, "qty": 10},
        )
        assert msg.level == NotificationLevel.SIGNAL
        assert msg.data["price"] == 500.0


class TestTelegramChannelFormatting:
    def test_format_info_message(self):
        ch = TelegramChannel(bot_token="fake_token", chat_id="fake_chat")
        msg = NotificationMessage(title="Test", body="Hello World")
        formatted = ch._format_message(msg)
        assert "*Test*" in formatted
        assert "Hello World" in formatted

    def test_format_with_data(self):
        ch = TelegramChannel(bot_token="fake_token", chat_id="fake_chat")
        msg = NotificationMessage(
            title="Signal",
            body="Buy",
            data={"price": 100.0, "qty": 10},
        )
        formatted = ch._format_message(msg)
        assert "price" in formatted
        assert "100.0" in formatted

    def test_format_error_level(self):
        ch = TelegramChannel(bot_token="fake_token", chat_id="fake_chat")
        msg = NotificationMessage(
            title="Error",
            body="Something failed",
            level=NotificationLevel.ERROR,
        )
        formatted = ch._format_message(msg)
        assert "Error" in formatted

    def test_format_signal_level(self):
        ch = TelegramChannel(bot_token="fake_token", chat_id="fake_chat")
        msg = NotificationMessage(
            title="Alert",
            body="Buy signal",
            level=NotificationLevel.SIGNAL,
        )
        formatted = ch._format_message(msg)
        assert "Alert" in formatted

    def test_format_warning_level(self):
        ch = TelegramChannel(bot_token="fake_token", chat_id="fake_chat")
        msg = NotificationMessage(
            title="Warning",
            body="Check this",
            level=NotificationLevel.WARNING,
        )
        formatted = ch._format_message(msg)
        assert "Warning" in formatted


class TestDiscordChannelFormatting:
    def test_format_embed_basic(self):
        ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/fake")
        msg = NotificationMessage(title="Test", body="Hello")
        embed = ch._format_embed(msg)
        assert embed["title"] == "Test"
        assert embed["description"] == "Hello"
        assert "color" in embed

    def test_format_embed_with_data(self):
        ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/fake")
        msg = NotificationMessage(
            title="Signal",
            body="Buy",
            data={"price": 100.0, "qty": 10},
        )
        embed = ch._format_embed(msg)
        assert "fields" in embed
        assert len(embed["fields"]) == 2

    def test_format_embed_no_data(self):
        ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/fake")
        msg = NotificationMessage(title="Test", body="No data")
        embed = ch._format_embed(msg)
        assert "fields" not in embed

    def test_embed_color_by_level(self):
        ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/fake")
        info_embed = ch._format_embed(NotificationMessage(title="", body="", level=NotificationLevel.INFO))
        error_embed = ch._format_embed(NotificationMessage(title="", body="", level=NotificationLevel.ERROR))
        assert info_embed["color"] != error_embed["color"]


class TestEmailChannelFormatting:
    def test_format_html_basic(self):
        ch = EmailChannel(
            smtp_host="localhost",
            smtp_port=587,
            username="user",
            password="pass",
            from_addr="from@test.com",
            to_addrs=["to@test.com"],
        )
        msg = NotificationMessage(title="Report", body="Daily summary")
        html = ch._format_html(msg)
        assert "<h2>Report</h2>" in html
        assert "Daily summary" in html
        assert "<html>" in html

    def test_format_html_with_data(self):
        ch = EmailChannel(
            smtp_host="localhost",
            smtp_port=587,
            username="user",
            password="pass",
            from_addr="from@test.com",
            to_addrs=["to@test.com"],
        )
        msg = NotificationMessage(
            title="Report",
            body="Summary",
            data={"total_pnl": 1000, "trades": 5},
        )
        html = ch._format_html(msg)
        assert "<table" in html
        assert "total_pnl" in html

    def test_format_html_escapes_special_chars(self):
        ch = EmailChannel(
            smtp_host="localhost",
            smtp_port=587,
            username="user",
            password="pass",
            from_addr="from@test.com",
            to_addrs=["to@test.com"],
        )
        msg = NotificationMessage(title="<script>alert</script>", body="test & test")
        html = ch._format_html(msg)
        assert "<script>" not in html
        assert "&amp;" in html


class TestNotificationManager:
    def test_add_channel(self):
        manager = NotificationManager()
        ch = TelegramChannel(bot_token="fake", chat_id="fake")
        manager.add_channel(ch)
        assert len(manager.channels) == 1

    def test_get_channel_health_empty(self):
        manager = NotificationManager()
        health = manager.get_channel_health()
        assert health == {}

    def test_get_channel_health_after_add(self):
        manager = NotificationManager()
        ch = TelegramChannel(bot_token="fake", chat_id="fake")
        manager.add_channel(ch)
        health = manager.get_channel_health()
        assert "TelegramChannel" in health
        assert health["TelegramChannel"]["success"] == 0
        assert health["TelegramChannel"]["failure"] == 0

    @pytest.mark.asyncio
    async def test_send_all_empty_channels(self):
        manager = NotificationManager()
        msg = NotificationMessage(title="Test", body="Hello")
        results = await manager.send_all(msg)
        assert results == {}

    @pytest.mark.asyncio
    async def test_send_all_with_mock_channel(self):
        manager = NotificationManager()
        mock_channel = AsyncMock()
        mock_channel.__class__.__name__ = "MockChannel"
        mock_channel.send = AsyncMock(return_value=True)
        manager.add_channel(mock_channel)
        manager._health["MockChannel"] = {"success": 0, "failure": 0}

        msg = NotificationMessage(title="Test", body="Hello")
        results = await manager.send_all(msg)
        assert results["MockChannel"] is True

    @pytest.mark.asyncio
    async def test_send_all_with_failure(self):
        manager = NotificationManager()
        mock_channel = AsyncMock()
        mock_channel.__class__.__name__ = "MockChannel"
        mock_channel.send = AsyncMock(return_value=False)
        manager.add_channel(mock_channel)
        manager._health["MockChannel"] = {"success": 0, "failure": 0}

        msg = NotificationMessage(
            title="Error",
            body="Bad",
            level=NotificationLevel.ERROR,
        )
        results = await manager.send_all(msg)
        assert results["MockChannel"] is False

    @pytest.mark.asyncio
    async def test_send_with_escalation_empty(self):
        manager = NotificationManager()
        msg = NotificationMessage(title="Test", body="Hello")
        results = await manager.send_with_escalation(msg)
        assert results == {}

    @pytest.mark.asyncio
    async def test_send_with_escalation_info_uses_first_channel(self):
        manager = NotificationManager()
        mock_ch1 = AsyncMock()
        mock_ch1.__class__.__name__ = "Channel1"
        mock_ch1.send = AsyncMock(return_value=True)
        manager.add_channel(mock_ch1)
        manager._health["Channel1"] = {"success": 0, "failure": 0}

        msg = NotificationMessage(
            title="Info",
            body="Hello",
            level=NotificationLevel.INFO,
        )
        results = await manager.send_with_escalation(msg)
        assert "Channel1" in results

    @pytest.mark.asyncio
    async def test_send_with_escalation_signal_sends_all(self):
        manager = NotificationManager()
        for name in ["Ch1", "Ch2"]:
            mock_ch = AsyncMock()
            mock_ch.__class__.__name__ = name
            mock_ch.send = AsyncMock(return_value=True)
            manager.add_channel(mock_ch)
            manager._health[name] = {"success": 0, "failure": 0}

        msg = NotificationMessage(
            title="Signal",
            body="Buy SPY",
            level=NotificationLevel.SIGNAL,
        )
        results = await manager.send_with_escalation(msg)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_send_with_escalation_error_sends_all(self):
        manager = NotificationManager()
        mock_ch = AsyncMock()
        mock_ch.__class__.__name__ = "ErrCh"
        mock_ch.send = AsyncMock(return_value=True)
        manager.add_channel(mock_ch)
        manager._health["ErrCh"] = {"success": 0, "failure": 0}

        msg = NotificationMessage(
            title="Error",
            body="Crash",
            level=NotificationLevel.ERROR,
        )
        results = await manager.send_with_escalation(msg)
        assert "ErrCh" in results

    @pytest.mark.asyncio
    async def test_send_message_alias(self):
        manager = NotificationManager()
        msg = NotificationMessage(title="Test", body="Hello")
        results = await manager.send_message(msg)
        assert results == {}

    @pytest.mark.asyncio
    async def test_send_signal_method(self):
        manager = NotificationManager()
        mock_ch = AsyncMock()
        mock_ch.__class__.__name__ = "TestCh"
        mock_ch.send = AsyncMock(return_value=True)
        manager.add_channel(mock_ch)
        manager._health["TestCh"] = {"success": 0, "failure": 0}

        results = await manager.send_signal(
            symbol="SPY",
            action="BUY",
            price=500.0,
            quantity=10,
            reason="20일 돌파",
        )
        assert "TestCh" in results

    @pytest.mark.asyncio
    async def test_send_daily_report(self):
        manager = NotificationManager()
        mock_ch = AsyncMock()
        mock_ch.__class__.__name__ = "TestCh"
        mock_ch.send = AsyncMock(return_value=True)
        manager.add_channel(mock_ch)
        manager._health["TestCh"] = {"success": 0, "failure": 0}

        results = await manager.send_daily_report({"pnl": 1000, "positions": 3})
        assert "TestCh" in results

    @pytest.mark.asyncio
    async def test_send_with_escalation_warning_tries_first(self):
        """WARNING 레벨도 첫 번째 채널만 사용"""
        manager = NotificationManager()
        mock_ch = AsyncMock()
        mock_ch.__class__.__name__ = "WarnCh"
        mock_ch.send = AsyncMock(return_value=True)
        manager.add_channel(mock_ch)
        manager._health["WarnCh"] = {"success": 0, "failure": 0}

        msg = NotificationMessage(
            title="Warning",
            body="Something",
            level=NotificationLevel.WARNING,
        )
        results = await manager.send_with_escalation(msg)
        assert "WarnCh" in results

    @pytest.mark.asyncio
    async def test_send_with_escalation_info_all_fail(self):
        """INFO 레벨에서 모든 채널 실패 시 빈 결과 반환"""
        manager = NotificationManager()
        mock_ch = AsyncMock()
        mock_ch.__class__.__name__ = "FailCh"
        mock_ch.send = AsyncMock(return_value=False)
        manager.add_channel(mock_ch)
        manager._health["FailCh"] = {"success": 0, "failure": 0}

        msg = NotificationMessage(
            title="Info",
            body="Hello",
            level=NotificationLevel.INFO,
        )
        results = await manager.send_with_escalation(msg)
        assert results == {}


def _make_email_channel() -> EmailChannel:
    return EmailChannel(
        smtp_host="localhost",
        smtp_port=587,
        username="user",
        password="pass",
        from_addr="from@test.com",
        to_addrs=["to@test.com"],
    )


class TestEmailChannelRetry:
    @pytest.mark.asyncio
    async def test_email_send_success(self):
        """_send_email 성공 시 send()가 True를 반환한다."""
        ch = _make_email_channel()
        with patch.object(ch, "_send_email", return_value=None) as mock_send:
            msg = NotificationMessage(title="Test", body="Hello")
            result = await ch.send(msg)
        assert result is True
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_email_send_retry_on_failure(self):
        """_send_email이 첫 번째에 실패하고 두 번째에 성공하면 retry가 동작하여 True를 반환한다."""
        ch = _make_email_channel()
        call_count = 0

        def _fail_then_succeed(msg):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise smtplib.SMTPException("Connection refused")

        with patch.object(ch, "_send_email", side_effect=_fail_then_succeed):
            msg = NotificationMessage(title="Retry Test", body="Hello")
            result = await ch.send(msg)

        assert result is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_email_send_all_retries_exhausted(self):
        """_send_email이 항상 실패하면 모든 재시도 소진 후 False를 반환하고 에러를 로깅한다."""
        ch = _make_email_channel()

        with patch.object(ch, "_send_email", side_effect=smtplib.SMTPException("Always fails")):
            with patch("src.notifier.logger") as mock_logger:
                msg = NotificationMessage(title="Fail Test", body="Hello")
                result = await ch.send(msg)

        assert result is False
        mock_logger.error.assert_called_once()
        error_call_args = mock_logger.error.call_args[0][0]
        assert "모든 재시도 소진" in error_call_args

    @pytest.mark.asyncio
    async def test_email_smtp_timeout(self):
        """SMTP가 timeout=10 파라미터와 함께 호출된다."""
        ch = _make_email_channel()

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            msg = NotificationMessage(title="Timeout Test", body="Hello")
            await ch.send(msg)

        mock_smtp_cls.assert_called_once_with("localhost", 587, timeout=10)


class TestSecurityFixes:
    """보안 수정 검증 테스트"""

    @pytest.mark.asyncio
    async def test_smtp_starttls_uses_ssl_context(self):
        """SMTP starttls()가 SSL context와 함께 호출된다."""
        ch = _make_email_channel()

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            with patch("src.notifier.ssl.create_default_context") as mock_ssl:
                mock_context = MagicMock()
                mock_ssl.return_value = mock_context
                msg = NotificationMessage(title="SSL Test", body="Hello")
                await ch.send(msg)

            mock_server.starttls.assert_called_once_with(context=mock_context)

    def test_discord_valid_url_accepted(self):
        """discord.com 도메인 URL은 정상 생성된다."""
        ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/12345/abcde")
        assert ch.webhook_url == "https://discord.com/api/webhooks/12345/abcde"

    def test_discord_discordapp_url_accepted(self):
        """discordapp.com 도메인도 허용된다."""
        ch = DiscordChannel(webhook_url="https://discordapp.com/api/webhooks/12345/abcde")
        assert ch.webhook_url == "https://discordapp.com/api/webhooks/12345/abcde"

    def test_discord_invalid_url_rejected(self):
        """Discord 외 도메인은 ValueError를 발생시킨다."""
        with pytest.raises(ValueError, match="Invalid Discord webhook URL domain"):
            DiscordChannel(webhook_url="https://evil.com/api/webhooks/12345")

    def test_discord_no_host_rejected(self):
        """호스트가 없는 URL은 거부된다."""
        with pytest.raises(ValueError, match="HTTPS"):
            DiscordChannel(webhook_url="not-a-url")

    def test_discord_http_scheme_rejected(self):
        """HTTP 스킴은 ValueError를 발생시킨다."""
        with pytest.raises(ValueError, match="HTTPS"):
            DiscordChannel(webhook_url="http://discord.com/api/webhooks/123")

    def test_discord_invalid_path_rejected(self):
        """올바르지 않은 경로는 ValueError를 발생시킨다."""
        with pytest.raises(ValueError, match="webhook path"):
            DiscordChannel(webhook_url="https://discord.com/other/path")
