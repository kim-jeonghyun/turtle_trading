"""
시스템 레벨 트레이딩 킬 스위치.

신규 진입(BUY)만 차단하며, 청산(SELL)은 항상 허용한다.
설정 우선순위: 환경변수 TRADING_ENABLED > config/system_status.yaml > 기본값(True)

Fail-Open 정책:
  YAML 파싱 실패 또는 파일 미존재 시 trading_enabled=True로 간주.
  근거: 설정 파일 오류로 인한 기회손실 방지. 킬 스위치는 명시적 활성화가 필요한
  안전장치이며, 파일 손상이 자동으로 거래를 중단시키면 정상 운영에 불필요한 장애를 유발.
"""

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# 프로젝트 루트 기준 절대 경로 (cron/Docker 환경 안전)
_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "system_status.yaml"


class KillSwitch:
    """시스템 레벨 트레이딩 킬 스위치.

    신규 진입(BUY)만 차단하며, 청산(SELL)은 항상 허용한다.
    설정 우선순위: 환경변수 TRADING_ENABLED > config/system_status.yaml > 기본값(True)
    """

    def __init__(self, config_path: Path | None = None):
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._state: dict = {}
        self.reload()

    def reload(self) -> None:
        """설정 파일 + 환경변수에서 상태를 다시 로드.

        매 호출 시 파일을 재로드하여 실시간으로 킬 스위치 상태를 반영한다.
        """
        # 1단계: 파일 로드 (Fail-Open)
        if not self._config_path.exists():
            self._state = {"trading_enabled": True}
        else:
            try:
                with open(self._config_path) as f:
                    self._state = yaml.safe_load(f) or {"trading_enabled": True}
            except yaml.YAMLError as e:
                logger.warning(f"system_status.yaml 파싱 오류, 기본값(enabled) 적용: {e}")
                self._state = {"trading_enabled": True}

        # 2단계: 환경변수 오버라이드 (YAML보다 우선)
        env_val = os.environ.get("TRADING_ENABLED")
        if env_val is not None:
            is_enabled = env_val.lower() not in ("false", "0", "no")
            self._state["trading_enabled"] = is_enabled
            if not is_enabled and not self._state.get("reason"):
                self._state["reason"] = "환경변수 TRADING_ENABLED=false"

    @property
    def is_trading_enabled(self) -> bool:
        """트레이딩 활성 여부"""
        return bool(self._state.get("trading_enabled", True))

    @property
    def reason(self) -> str:
        """비활성화 사유"""
        return str(self._state.get("reason", ""))

    @property
    def disabled_at(self) -> str | None:
        """비활성화 시각"""
        val = self._state.get("disabled_at")
        return str(val) if val else None

    def check_entry_allowed(self) -> tuple[bool, str]:
        """신규 진입 가능 여부 확인. (allowed, reason) 반환.

        매 호출 시 파일을 재로드하여 실시간으로 킬 스위치 상태를 반영한다.
        이는 의도적 설계: auto_trade.py의 심볼 루프 도중에도 킬 스위치 활성화를
        즉시 감지하기 위함 (defense-in-depth).
        """
        self.reload()
        if not self.is_trading_enabled:
            return False, f"킬 스위치 활성: {self.reason}"
        return True, ""

    def activate(self, reason: str = "수동 킬 스위치") -> None:
        """킬 스위치 활성화 (트레이딩 중단)."""
        self._state["trading_enabled"] = False
        self._state["reason"] = reason
        self._state["disabled_at"] = datetime.now().isoformat()
        self._save()
        logger.critical(f"킬 스위치 활성화: {reason}")

    def deactivate(self) -> None:
        """킬 스위치 해제 (트레이딩 재개)."""
        self._state["trading_enabled"] = True
        self._state["reason"] = ""
        self._state["disabled_at"] = None
        self._save()
        logger.info("킬 스위치 해제: 트레이딩 재개")

    def _save(self) -> None:
        """원자적 파일 저장 (torn read 방지).

        tempfile + os.replace()로 동시 접근 시에도 파일 손상을 방지한다.
        """
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path_str = tempfile.mkstemp(dir=self._config_path.parent, suffix=".tmp")
        temp_path = Path(temp_path_str)
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(self._state, f, default_flow_style=False, allow_unicode=True)
            os.replace(temp_path, self._config_path)
        except Exception:
            logger.error(f"system_status.yaml 저장 실패: {self._config_path}")
            temp_path.unlink(missing_ok=True)
            raise
