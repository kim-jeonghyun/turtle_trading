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


class TestCheckStopLoss:
    """check_stop_loss 메서드 테스트"""

    def test_long_stop_triggered(self, tracker):
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        # stop_loss = 100 - 2*2.5 = 95.0
        triggered = tracker.check_stop_loss({"SPY": 94.0})
        assert len(triggered) == 1
        assert triggered[0].position_id == pos.position_id

    def test_long_stop_not_triggered(self, tracker):
        tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        triggered = tracker.check_stop_loss({"SPY": 96.0})
        assert len(triggered) == 0

    def test_short_stop_triggered(self, tracker):
        pos = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        # stop_loss = 100 + 2*2.5 = 105.0
        triggered = tracker.check_stop_loss({"SPY": 106.0})
        assert len(triggered) == 1
        assert triggered[0].position_id == pos.position_id

    def test_short_stop_not_triggered(self, tracker):
        tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        triggered = tracker.check_stop_loss({"SPY": 104.0})
        assert len(triggered) == 0

    def test_multiple_symbols(self, tracker):
        pos1 = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)  # stop=95
        pos2 = tracker.open_position("QQQ", 1, "SHORT", 200.0, 5.0, 20)  # stop=210
        # SPY: 94 <= 95 -> triggered, QQQ: 211 >= 210 -> triggered
        triggered = tracker.check_stop_loss({"SPY": 94.0, "QQQ": 211.0})
        assert len(triggered) == 2

    def test_missing_symbol_skipped(self, tracker):
        tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        # No SPY in prices -> skip
        triggered = tracker.check_stop_loss({"QQQ": 50.0})
        assert len(triggered) == 0


class TestPnLCalculation:
    def test_pnl_with_pyramid_weighted_average(self, tracker):
        """피라미딩 시 가중평균 기반 P&L% 계산"""
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        # 피라미딩: 105에 추가 진입
        tracker.add_pyramid(pos.position_id, 105.0, 2.5, 40)

        # 110에 청산
        closed = tracker.close_position(pos.position_id, 110.0)

        # 가중평균 단가: (100*40 + 105*40) / 80 = 102.5
        # PnL: (110 - 102.5) * 80 = 600
        # PnL%: 600 / (102.5 * 80) * 100 = 600 / 8200 * 100 = 7.317...
        assert closed.pnl == 600.0
        assert abs(closed.pnl_pct - 7.317) < 0.1

    def test_pnl_single_entry(self, tracker):
        """단일 진입 시 기존 방식과 동일"""
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        closed = tracker.close_position(pos.position_id, 110.0)

        # PnL: (110-100)*40 = 400
        # PnL%: 400 / (100*40) * 100 = 10.0
        assert closed.pnl == 400.0
        assert abs(closed.pnl_pct - 10.0) < 0.01


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
