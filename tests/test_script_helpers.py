"""
script_helpers.py 단위 테스트
"""

import logging
from pathlib import Path
from unittest.mock import patch

import yaml

from src.script_helpers import _GROUP_MAPPING, load_config, setup_notifier, setup_risk_manager

_NO_DOTENV = patch("dotenv.load_dotenv", lambda *a, **kw: None)


class TestLoadConfig:
    @_NO_DOTENV
    @patch.dict(
        "os.environ",
        {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "TELEGRAM_CHAT_ID": "test_chat",
            "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test",
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
        assert config["discord_webhook"] == "https://discord.com/api/webhooks/test"
        assert config["email_user"] == "user@test.com"

    @_NO_DOTENV
    @patch.dict("os.environ", {}, clear=True)
    def test_load_empty_config(self):
        config = load_config()
        assert config["telegram_token"] is None
        assert config["discord_webhook"] is None
        assert config["email_to"] == []

    @_NO_DOTENV
    @patch.dict("os.environ", {"SMTP_HOST": "custom.host", "SMTP_PORT": "465"}, clear=True)
    def test_smtp_defaults(self):
        config = load_config()
        assert config["smtp_host"] == "custom.host"
        assert config["smtp_port"] == 465

    @_NO_DOTENV
    @patch.dict("os.environ", {}, clear=True)
    def test_smtp_fallback_defaults(self):
        config = load_config()
        assert config["smtp_host"] == "smtp.gmail.com"
        assert config["smtp_port"] == 587

    @_NO_DOTENV
    @patch.dict("os.environ", {"EMAIL_TO": "a@b.com,c@d.com"}, clear=True)
    def test_email_to_split(self):
        config = load_config()
        assert config["email_to"] == ["a@b.com", "c@d.com"]

    @_NO_DOTENV
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
        config = {"discord_webhook": "https://discord.com/api/webhooks/hook"}
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
            "discord_webhook": "https://discord.com/api/webhooks/hook",
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

    def test_email_missing_password_no_channel(self):
        """email_pass가 None이면 EmailChannel이 생성되지 않는다."""
        config = {
            "email_user": "user@test.com",
            "email_pass": None,
            "smtp_host": "localhost",
            "smtp_port": 587,
            "email_to": ["to@test.com"],
        }
        notifier = setup_notifier(config)
        assert len(notifier.channels) == 0

    def test_email_with_password_creates_channel(self):
        """email_pass가 설정되면 EmailChannel이 생성된다."""
        config = {
            "email_user": "user@test.com",
            "email_pass": "password123",
            "smtp_host": "localhost",
            "smtp_port": 587,
            "email_to": ["to@test.com"],
        }
        notifier = setup_notifier(config)
        assert len(notifier.channels) == 1


class TestSetupRiskManager:
    """setup_risk_manager() 통합 버전 테스트"""

    def test_setup_risk_manager_loads_all_groups(self, tmp_path):
        """YAML에서 모든 그룹이 로드되는지 검증"""
        yaml_content = {
            "groups": {
                "us_equity": ["SPY", "QQQ"],
                "kr_equity": ["005930.KS"],
            }
        }
        config_path = tmp_path / "test_groups.yaml"
        config_path.write_text(yaml.dump(yaml_content))
        rm = setup_risk_manager(config_path=config_path)
        assert rm is not None

    def test_setup_risk_manager_unknown_group_warns(self, tmp_path, caplog):
        """미지 그룹명에 warning 로그 발생"""
        yaml_content = {
            "groups": {
                "unknown_group": ["XYZ"],
            }
        }
        config_path = tmp_path / "test_groups.yaml"
        config_path.write_text(yaml.dump(yaml_content))
        with caplog.at_level(logging.WARNING):
            rm = setup_risk_manager(config_path=config_path)
        assert "Unknown correlation group" in caplog.text
        assert rm is not None

    def test_all_yaml_groups_have_explicit_mapping(self):
        """correlation_groups.yaml의 모든 그룹명이 _GROUP_MAPPING에 존재하는지 검증 (regression guard)"""
        config_path = Path(__file__).parent.parent / "config" / "correlation_groups.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        for group_name in config.get("groups", {}).keys():
            assert group_name in _GROUP_MAPPING, f"Unmapped group in YAML: {group_name}"

    def test_setup_risk_manager_returns_valid_instance(self):
        """실제 YAML로 유효한 PortfolioRiskManager 반환 검증"""
        rm = setup_risk_manager()
        assert rm is not None
        assert hasattr(rm, "check_position_limit") or hasattr(rm, "can_add_position")

    def test_setup_risk_manager_missing_file(self, tmp_path, caplog):
        """존재하지 않는 파일에 대해 빈 매니저 반환"""
        config_path = tmp_path / "nonexistent.yaml"
        with caplog.at_level(logging.WARNING):
            rm = setup_risk_manager(config_path=config_path)
        assert rm is not None
        assert "상관그룹 설정 파일 없음" in caplog.text

    def test_setup_risk_manager_empty_config(self, tmp_path, caplog):
        """groups 키가 없는 YAML에 대해 빈 매니저 반환"""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text(yaml.dump({"other_key": "value"}))
        with caplog.at_level(logging.WARNING):
            rm = setup_risk_manager(config_path=config_path)
        assert rm is not None
        assert "상관그룹 설정이 비어있습니다" in caplog.text

    def test_symbol_group_assignment(self, tmp_path):
        """심볼별 그룹 할당이 올바른지 검증"""
        from src.types import AssetGroup

        yaml_content = {
            "groups": {
                "us_equity": ["SPY"],
                "crypto": ["BTC"],
                "inverse": ["SH"],
            }
        }
        config_path = tmp_path / "test_groups.yaml"
        config_path.write_text(yaml.dump(yaml_content))
        rm = setup_risk_manager(config_path=config_path)
        assert rm.get_group("SPY") == AssetGroup.US_EQUITY
        assert rm.get_group("BTC") == AssetGroup.CRYPTO
        assert rm.get_group("SH") == AssetGroup.INVERSE
