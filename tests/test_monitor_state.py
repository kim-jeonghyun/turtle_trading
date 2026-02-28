"""
MonitorState 단위 테스트
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.monitor_state import MonitorState


class TestStopLossTracking:
    """스톱로스 알림 상태 추적 테스트"""

    def test_stop_loss_alert_once(self, tmp_path):
        """1회 알림 후 is_stop_loss_alerted True"""
        state = MonitorState(state_file=tmp_path / "state.json")
        assert state.is_stop_loss_alerted("pos_1") is False
        state.mark_stop_loss_alerted("pos_1")
        assert state.is_stop_loss_alerted("pos_1") is True

    def test_stop_loss_no_re_alert(self, tmp_path):
        """이미 알림 → 재알림 차단 확인"""
        state = MonitorState(state_file=tmp_path / "state.json")
        state.mark_stop_loss_alerted("pos_1")
        # 두 번째 mark는 여전히 True
        state.mark_stop_loss_alerted("pos_1")
        assert state.is_stop_loss_alerted("pos_1") is True

    def test_price_recovery_reset(self, tmp_path):
        """가격 회복 → reset → 재이탈 시 재알림 가능"""
        state = MonitorState(state_file=tmp_path / "state.json")
        # 1. 이탈 알림
        state.mark_stop_loss_alerted("pos_1")
        assert state.is_stop_loss_alerted("pos_1") is True
        # 2. 가격 회복 → 리셋
        state.reset_stop_loss_alert("pos_1")
        assert state.is_stop_loss_alerted("pos_1") is False
        # 3. 재이탈 → 재알림 가능
        state.mark_stop_loss_alerted("pos_1")
        assert state.is_stop_loss_alerted("pos_1") is True


class TestWarningCooldown:
    """P&L 경고 쿨다운 테스트"""

    def test_warning_cooldown_blocks(self, tmp_path):
        """60분 이내 → can_send_warning False"""
        state = MonitorState(state_file=tmp_path / "state.json")
        state.update_warning("pos_1")
        assert state.can_send_warning("pos_1", cooldown_minutes=60) is False

    def test_warning_cooldown_allows(self, tmp_path):
        """60분 경과 → can_send_warning True"""
        state = MonitorState(state_file=tmp_path / "state.json")
        state.update_warning("pos_1")
        # Manually set last_warning_time to 61 minutes ago
        old_time = (datetime.now() - timedelta(minutes=61)).isoformat()
        state._alerts["pos_1"].last_warning_time = old_time
        assert state.can_send_warning("pos_1", cooldown_minutes=60) is True

    def test_custom_cooldown_minutes(self, tmp_path):
        """cooldown=30 → 30분 기준 적용"""
        state = MonitorState(state_file=tmp_path / "state.json")
        state.update_warning("pos_1")
        # 31분 전으로 설정
        old_time = (datetime.now() - timedelta(minutes=31)).isoformat()
        state._alerts["pos_1"].last_warning_time = old_time
        assert state.can_send_warning("pos_1", cooldown_minutes=30) is True
        # 29분 전으로 설정
        recent_time = (datetime.now() - timedelta(minutes=29)).isoformat()
        state._alerts["pos_1"].last_warning_time = recent_time
        assert state.can_send_warning("pos_1", cooldown_minutes=30) is False

    def test_warning_count_increments(self, tmp_path):
        """update_warning 호출마다 count 증가"""
        state = MonitorState(state_file=tmp_path / "state.json")
        state.update_warning("pos_1")
        assert state._alerts["pos_1"].warning_count == 1
        state.update_warning("pos_1")
        assert state._alerts["pos_1"].warning_count == 2
        state.update_warning("pos_1")
        assert state._alerts["pos_1"].warning_count == 3


class TestPersistence:
    """파일 기반 영속성 테스트"""

    def test_load_empty_file(self, tmp_path):
        """파일 없을 때 빈 상태"""
        state = MonitorState.load(state_file=tmp_path / "nonexistent.json")
        assert state.is_stop_loss_alerted("any_pos") is False
        assert state.can_send_warning("any_pos") is True

    def test_save_and_load_roundtrip(self, tmp_path):
        """저장 → 로드 데이터 무결성"""
        state_file = tmp_path / "state.json"
        state = MonitorState(state_file=state_file)
        state.mark_stop_loss_alerted("pos_1")
        state.update_warning("pos_2")
        state.save()

        # 새 인스턴스로 로드
        loaded = MonitorState.load(state_file=state_file)
        assert loaded.is_stop_loss_alerted("pos_1") is True
        assert loaded.is_stop_loss_alerted("pos_2") is False
        assert loaded._alerts["pos_2"].warning_count == 1

    def test_atomic_save_on_failure(self, tmp_path):
        """중간 실패 시 이전 상태 유지"""
        state_file = tmp_path / "state.json"
        # 초기 상태 저장
        state = MonitorState(state_file=state_file)
        state.mark_stop_loss_alerted("pos_1")
        state.save()

        # atomic_write_json이 실패하도록 mock
        with patch("src.monitor_state.atomic_write_json", side_effect=OSError("disk full")):
            state2 = MonitorState(state_file=state_file)
            state2.mark_stop_loss_alerted("pos_2")
            with pytest.raises(OSError):
                state2.save()

        # 원본 파일은 손상되지 않음
        loaded = MonitorState.load(state_file=state_file)
        assert loaded.is_stop_loss_alerted("pos_1") is True
        assert loaded.is_stop_loss_alerted("pos_2") is False

    def test_load_corrupted_json(self, tmp_path):
        """손상된 JSON → 빈 상태 fallback"""
        state_file = tmp_path / "state.json"
        state_file.write_text("{invalid json content", encoding="utf-8")
        state = MonitorState.load(state_file=state_file)
        assert state.is_stop_loss_alerted("any") is False

    def test_cleanup_preserves_open(self, tmp_path):
        """닫힌 포지션만 제거, 열린 포지션 유지"""
        state = MonitorState(state_file=tmp_path / "state.json")
        state.mark_stop_loss_alerted("pos_open")
        state.mark_stop_loss_alerted("pos_closed")
        state.update_warning("pos_other_closed")

        state.cleanup_closed_positions(open_position_ids={"pos_open"})

        assert state.is_stop_loss_alerted("pos_open") is True
        assert state.is_stop_loss_alerted("pos_closed") is False
        assert "pos_closed" not in state._alerts
        assert "pos_other_closed" not in state._alerts
