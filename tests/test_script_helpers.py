"""
script_helpers.py 단위 테스트
"""

from unittest.mock import patch

from src.script_helpers import load_config, setup_notifier


class TestLoadConfig:
    @patch.dict(
        "os.environ",
        {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_CHAT_ID": "test_chat",
            "DISCORD_WEBHOOK_URL": "https://discord.webhook",
            "EMAIL_USER": "user@test.com",
            "EMAIL_PASSWORD": "pass",
            "EMAIL_TO": "to@test.com",
        },
        clear=True,
    )
    def test_load_all_config(self):
        config = load_config()
        assert config["telegram_token"] == "test_token"
        assert config["telegram_chat_id"] == "test_chat"
        assert config["discord_webhook"] == "https://discord.webhook"
        assert config["email_user"] == "user@test.com"

    @patch.dict("os.environ", {}, clear=True)
    def test_load_empty_config(self):
        config = load_config()
        assert config["telegram_token"] is None
        assert config["discord_webhook"] is None
        assert config["email_to"] == []

    @patch.dict("os.environ", {"SMTP_HOST": "custom.host", "SMTP_PORT": "465"}, clear=True)
    def test_smtp_defaults(self):
        config = load_config()
        assert config["smtp_host"] == "custom.host"
        assert config["smtp_port"] == 465

    @patch.dict("os.environ", {}, clear=True)
    def test_smtp_fallback_defaults(self):
        config = load_config()
        assert config["smtp_host"] == "smtp.gmail.com"
        assert config["smtp_port"] == 587

    @patch.dict("os.environ", {"EMAIL_TO": "a@b.com,c@d.com"}, clear=True)
    def test_email_to_split(self):
        config = load_config()
        assert config["email_to"] == ["a@b.com", "c@d.com"]

    @patch.dict("os.environ", {"EMAIL_TO": ""}, clear=True)
    def test_email_to_empty_string(self):
        config = load_config()
        assert config["email_to"] == []


class TestSetupNotifier:
    def test_no_channels_when_empty(self):
        notifier = setup_notifier({})
        assert len(notifier.channels) == 0

    def test_telegram_only(self):
        config = {"telegram_token": "tok", "telegram_chat_id": "chat"}
        notifier = setup_notifier(config)
        assert len(notifier.channels) == 1

    def test_discord_only(self):
        config = {"discord_webhook": "https://hook"}
        notifier = setup_notifier(config)
        assert len(notifier.channels) == 1

    def test_email_only(self):
        config = {
            "email_user": "user@test.com",
            "email_pass": "pass",
            "smtp_host": "localhost",
            "smtp_port": 587,
            "email_to": ["to@test.com"],
        }
        notifier = setup_notifier(config)
        assert len(notifier.channels) == 1

    def test_all_channels(self):
        config = {
            "telegram_token": "tok",
            "telegram_chat_id": "chat",
            "discord_webhook": "https://hook",
            "email_user": "user@test.com",
            "email_pass": "pass",
            "smtp_host": "localhost",
            "smtp_port": 587,
            "email_to": ["to@test.com"],
        }
        notifier = setup_notifier(config)
        assert len(notifier.channels) == 3

    def test_telegram_missing_chat_id(self):
        config = {"telegram_token": "tok"}
        notifier = setup_notifier(config)
        assert len(notifier.channels) == 0

    def test_email_missing_email_to(self):
        config = {"email_user": "user@test.com", "email_pass": "pass", "smtp_host": "localhost", "smtp_port": 587}
        notifier = setup_notifier(config)
        assert len(notifier.channels) == 0
