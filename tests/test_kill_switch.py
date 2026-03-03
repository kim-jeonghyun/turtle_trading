"""
KillSwitch 단위 테스트 (TDD RED phase)

킬 스위치는 시스템 레벨 트레이딩 안전장치로,
신규 진입(BUY)만 차단하며 청산(SELL)은 항상 허용한다.
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.kill_switch import KillSwitch


@pytest.fixture
def temp_config_dir():
    """임시 설정 디렉토리"""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


@pytest.fixture
def config_path(temp_config_dir):
    """임시 system_status.yaml 경로"""
    return temp_config_dir / "system_status.yaml"


def _write_yaml(path: Path, data: dict) -> None:
    """헬퍼: YAML 파일 작성"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


class TestKillSwitchDefaults:
    """파일 미존재/빈 파일/손상 시 기본 동작"""

    def test_default_trading_enabled(self, config_path):
        """파일 미존재 시 trading_enabled=True"""
        ks = KillSwitch(config_path=config_path)
        assert ks.is_trading_enabled is True

    def test_empty_file_defaults_to_enabled(self, config_path):
        """빈 파일 → 기본값 True"""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("")
        ks = KillSwitch(config_path=config_path)
        assert ks.is_trading_enabled is True

    def test_malformed_yaml_defaults_to_enabled(self, config_path):
        """파싱 에러 발생하는 YAML → 기본값 True + WARNING 로그"""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("trading_enabled: [[[invalid")
        ks = KillSwitch(config_path=config_path)
        assert ks.is_trading_enabled is True


class TestKillSwitchConfigLoading:
    """YAML 설정 파일 로드"""

    def test_trading_disabled_from_config(self, config_path):
        """YAML에서 trading_enabled=false 로드"""
        _write_yaml(config_path, {"trading_enabled": False, "reason": "테스트"})
        ks = KillSwitch(config_path=config_path)
        assert ks.is_trading_enabled is False

    def test_trading_enabled_from_config(self, config_path):
        """YAML에서 trading_enabled=true 로드"""
        _write_yaml(config_path, {"trading_enabled": True})
        ks = KillSwitch(config_path=config_path)
        assert ks.is_trading_enabled is True

    def test_reason_preserved(self, config_path):
        """reason 필드 보존"""
        _write_yaml(config_path, {"trading_enabled": False, "reason": "시장 급변"})
        ks = KillSwitch(config_path=config_path)
        assert ks.reason == "시장 급변"


class TestKillSwitchCheckEntry:
    """check_entry_allowed() 동작"""

    def test_check_entry_allowed_when_enabled(self, config_path):
        """활성 상태에서 (True, '') 반환"""
        _write_yaml(config_path, {"trading_enabled": True})
        ks = KillSwitch(config_path=config_path)
        allowed, reason = ks.check_entry_allowed()
        assert allowed is True
        assert reason == ""

    def test_check_entry_allowed_when_disabled(self, config_path):
        """비활성 상태에서 (False, '킬 스위치 활성: ...') 반환"""
        _write_yaml(config_path, {"trading_enabled": False, "reason": "긴급 중단"})
        ks = KillSwitch(config_path=config_path)
        allowed, reason = ks.check_entry_allowed()
        assert allowed is False
        assert "킬 스위치 활성" in reason
        assert "긴급 중단" in reason


class TestKillSwitchActivateDeactivate:
    """activate/deactivate 상태 전환 + 파일 저장"""

    def test_activate_saves_state(self, config_path):
        """activate() 호출 시 파일 저장 + 상태 변경"""
        ks = KillSwitch(config_path=config_path)
        ks.activate(reason="API 장애")

        assert ks.is_trading_enabled is False
        assert ks.reason == "API 장애"

        # 파일에도 저장되었는지 확인
        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert saved["trading_enabled"] is False
        assert saved["reason"] == "API 장애"
        assert saved["disabled_at"] is not None

    def test_deactivate_saves_state(self, config_path):
        """deactivate() 후 trading_enabled=true"""
        ks = KillSwitch(config_path=config_path)
        ks.activate(reason="테스트")
        ks.deactivate()

        assert ks.is_trading_enabled is True
        assert ks.reason == ""

        with open(config_path) as f:
            saved = yaml.safe_load(f)
        assert saved["trading_enabled"] is True

    def test_reload_picks_up_external_change(self, config_path):
        """외부에서 파일 수정 후 reload() 반영"""
        _write_yaml(config_path, {"trading_enabled": True})
        ks = KillSwitch(config_path=config_path)
        assert ks.is_trading_enabled is True

        # 외부에서 파일 변경
        _write_yaml(config_path, {"trading_enabled": False, "reason": "외부 변경"})
        ks.reload()
        assert ks.is_trading_enabled is False

    def test_atomic_save_creates_valid_yaml(self, config_path):
        """activate() 후 저장된 파일이 valid YAML"""
        ks = KillSwitch(config_path=config_path)
        ks.activate(reason="원자적 저장 테스트")

        # 파일이 valid YAML인지 확인
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "trading_enabled" in data
        assert "reason" in data
        assert "disabled_at" in data


class TestKillSwitchEnvVar:
    """환경변수 TRADING_ENABLED 오버라이드"""

    def test_env_var_overrides_yaml_to_disabled(self, config_path):
        """YAML=true + TRADING_ENABLED=false → disabled"""
        _write_yaml(config_path, {"trading_enabled": True})
        with patch.dict(os.environ, {"TRADING_ENABLED": "false"}):
            ks = KillSwitch(config_path=config_path)
            assert ks.is_trading_enabled is False

    def test_env_var_overrides_yaml_to_enabled(self, config_path):
        """YAML=false + TRADING_ENABLED=true → enabled"""
        _write_yaml(config_path, {"trading_enabled": False, "reason": "수동"})
        with patch.dict(os.environ, {"TRADING_ENABLED": "true"}):
            ks = KillSwitch(config_path=config_path)
            assert ks.is_trading_enabled is True

    def test_env_var_absent_falls_through_to_yaml(self, config_path):
        """환경변수 미설정 → YAML 값 사용"""
        _write_yaml(config_path, {"trading_enabled": False, "reason": "YAML만"})
        with patch.dict(os.environ, {}, clear=False):
            # TRADING_ENABLED 키가 없는 상태
            env_backup = os.environ.pop("TRADING_ENABLED", None)
            try:
                ks = KillSwitch(config_path=config_path)
                assert ks.is_trading_enabled is False
                assert ks.reason == "YAML만"
            finally:
                if env_backup is not None:
                    os.environ["TRADING_ENABLED"] = env_backup
