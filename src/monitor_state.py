"""
장중 모니터링 알림 상태 관리 모듈.

5분 폴링 × 6시간 = 72회/일, 알림 스팸 방지를 위한 상태 관리.
저장: data/monitor_state.json (atomic_write_json 사용)
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.utils import atomic_write_json

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent.parent / "data" / "monitor_state.json"


@dataclass
class PositionAlert:
    """포지션별 알림 상태."""

    stop_loss_alerted: bool = False
    last_warning_time: Optional[str] = None  # ISO 8601
    warning_count: int = 0


class MonitorState:
    """장중 모니터링 알림 상태 관리.

    리셋 정책:
    - 스톱로스: position_id당 1회 알림, 가격 회복 시 리셋
    - P&L 경고: 쿨다운 60분 (기본), --warning-cooldown으로 조정
    - 일일 리셋: cleanup_closed_positions()에서 닫힌 포지션 정리
    """

    def __init__(self, state_file: Path = STATE_FILE):
        self._file = state_file
        self._alerts: dict[str, PositionAlert] = {}

    @classmethod
    def load(cls, state_file: Path = STATE_FILE) -> "MonitorState":
        """파일에서 상태 로드. 파일 없거나 손상 시 빈 상태."""
        instance = cls(state_file=state_file)
        if not state_file.exists():
            return instance

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
            for pos_id, alert_data in data.items():
                instance._alerts[pos_id] = PositionAlert(
                    stop_loss_alerted=alert_data.get("stop_loss_alerted", False),
                    last_warning_time=alert_data.get("last_warning_time"),
                    warning_count=alert_data.get("warning_count", 0),
                )
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"상태 파일 손상, 빈 상태로 시작: {e}")
            instance._alerts = {}
        except Exception as e:
            logger.error(f"상태 파일 로드 오류: {e}")
            instance._alerts = {}

        return instance

    def save(self) -> None:
        """원자적 저장 (atomic_write_json, src/utils.py:77)."""
        data = {}
        for pos_id, alert in self._alerts.items():
            data[pos_id] = asdict(alert)
        atomic_write_json(self._file, data)

    def _get_or_create(self, position_id: str) -> PositionAlert:
        """포지션 알림 상태 가져오기 (없으면 생성)."""
        if position_id not in self._alerts:
            self._alerts[position_id] = PositionAlert()
        return self._alerts[position_id]

    def is_stop_loss_alerted(self, position_id: str) -> bool:
        """스톱로스 알림 발송 여부."""
        alert = self._alerts.get(position_id)
        if alert is None:
            return False
        return alert.stop_loss_alerted

    def mark_stop_loss_alerted(self, position_id: str) -> None:
        """스톱로스 알림 발송 기록."""
        alert = self._get_or_create(position_id)
        alert.stop_loss_alerted = True

    def reset_stop_loss_alert(self, position_id: str) -> None:
        """가격 회복 시 스톱로스 알림 상태 리셋.

        시나리오: 월요일 이탈 알림 → 화요일 회복 → 수요일 재이탈 시 재알림.
        """
        alert = self._alerts.get(position_id)
        if alert is not None:
            alert.stop_loss_alerted = False

    def can_send_warning(self, position_id: str, cooldown_minutes: int = 60) -> bool:
        """P&L 경고 발송 가능 여부 (쿨다운 확인)."""
        alert = self._alerts.get(position_id)
        if alert is None or alert.last_warning_time is None:
            return True

        try:
            last_time = datetime.fromisoformat(alert.last_warning_time)
            if last_time.tzinfo is None:
                # 레거시 naive 저장값 — 로컬 타임 기준으로 비교
                now = datetime.now()
            else:
                now = datetime.now(tz=timezone.utc)
            return now - last_time >= timedelta(minutes=cooldown_minutes)
        except (ValueError, TypeError):
            return True

    def update_warning(self, position_id: str) -> None:
        """P&L 경고 발송 시간 기록."""
        alert = self._get_or_create(position_id)
        alert.last_warning_time = datetime.now(tz=timezone.utc).isoformat()
        alert.warning_count += 1

    def cleanup_closed_positions(self, open_position_ids: set[str]) -> None:
        """닫힌 포지션 상태 제거 (무한 증가 방지)."""
        closed_ids = [pid for pid in self._alerts if pid not in open_position_ids]
        for pid in closed_ids:
            del self._alerts[pid]
        if closed_ids:
            logger.info(f"닫힌 포지션 상태 정리: {len(closed_ids)}건")
