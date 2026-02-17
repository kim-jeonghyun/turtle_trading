"""
position_tracker.py 단위 테스트
- 포지션 라이프사이클
- 피라미딩
- 스톱로스
- R-배수 계산
"""

import pytest
import json
from pathlib import Path
from src.position_tracker import PositionTracker, Position, PositionStatus


@pytest.fixture
def tracker(temp_data_dir):
    return PositionTracker(base_dir=str(temp_data_dir))


class TestPositionLifecycle:
    def test_open_position(self, tracker):
        pos = tracker.open_position(
            symbol="SPY", system=1, direction="LONG",
            entry_price=100.0, n_value=2.5, shares=40
        )
        assert pos.symbol == "SPY"
        assert pos.status == "open"
        assert pos.units == 1
        assert pos.total_shares == 40
        assert pos.stop_loss == 95.0  # 100 - 2*2.5

    def test_close_position(self, tracker):
        pos = tracker.open_position(
            symbol="SPY", system=1, direction="LONG",
            entry_price=100.0, n_value=2.5, shares=40
        )
        closed = tracker.close_position(pos.position_id, 110.0, "Exit Signal")
        assert closed.status == "closed"
        assert closed.pnl == 400.0  # (110-100) * 40
        assert closed.exit_price == 110.0

    def test_get_open_positions(self, tracker):
        tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        tracker.open_position("QQQ", 1, "LONG", 200.0, 3.0, 30)

        all_open = tracker.get_open_positions()
        assert len(all_open) == 2

        spy_open = tracker.get_open_positions("SPY")
        assert len(spy_open) == 1

    def test_close_removes_from_open(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        tracker.close_position(pos.position_id, 110.0)

        open_pos = tracker.get_open_positions()
        assert len(open_pos) == 0


class TestPyramiding:
    def test_add_pyramid(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        updated = tracker.add_pyramid(pos.position_id, 101.25, 2.5, 40)

        assert updated.units == 2
        assert updated.total_shares == 80
        assert updated.pyramid_level == 1

    def test_max_pyramid_limit(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        tracker.add_pyramid(pos.position_id, 101.25, 2.5, 40)  # Level 1
        tracker.add_pyramid(pos.position_id, 102.50, 2.5, 40)  # Level 2
        tracker.add_pyramid(pos.position_id, 103.75, 2.5, 40)  # Level 3

        result = tracker.add_pyramid(pos.position_id, 105.0, 2.5, 40)  # Level 4 - should fail
        assert result is None  # Max 4 units reached

    def test_should_pyramid(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)

        # 0.5N = 1.25 상승 필요
        assert tracker.should_pyramid(pos, 101.0) is False  # Not enough
        assert tracker.should_pyramid(pos, 101.25) is True   # Exactly 0.5N


class TestRMultiple:
    def test_positive_r(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        closed = tracker.close_position(pos.position_id, 105.0)
        # R = (105-100) / (2*2.5) = 5/5 = 1.0R
        assert closed.r_multiple == 1.0

    def test_negative_r(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        closed = tracker.close_position(pos.position_id, 95.0)
        # R = (95-100) / (2*2.5) = -5/5 = -1.0R
        assert closed.r_multiple == -1.0

    def test_stop_loss_r(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        # 스톱로스에서 청산 시 -1.0R
        closed = tracker.close_position(pos.position_id, pos.stop_loss)
        assert abs(closed.r_multiple - (-1.0)) < 0.01


class TestStopLoss:
    def test_long_stop_loss(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        # 스톱: 100 - 2*2.5 = 95
        assert pos.stop_loss == 95.0

    def test_short_stop_loss(self, tracker):
        pos = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        # 스톱: 100 + 2*2.5 = 105
        assert pos.stop_loss == 105.0


class TestPersistence:
    def test_data_survives_reload(self, temp_data_dir):
        tracker1 = PositionTracker(base_dir=str(temp_data_dir))
        tracker1.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)

        # 새 인스턴스로 로드
        tracker2 = PositionTracker(base_dir=str(temp_data_dir))
        positions = tracker2.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "SPY"

    def test_summary(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        tracker.close_position(pos.position_id, 110.0)
        tracker.open_position("QQQ", 1, "LONG", 200.0, 3.0, 30)

        summary = tracker.get_summary()
        assert summary['total_positions'] == 2
        assert summary['open_positions'] == 1
        assert summary['closed_positions'] == 1
