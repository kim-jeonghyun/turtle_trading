"""
pyramid_manager.py 단위 테스트
- 0.5N 간격 피라미딩
- 최대 4 Units
- LONG/SHORT 방향
- Trailing Stop
"""

import pytest
from datetime import datetime
from src.pyramid_manager import PyramidManager, PyramidPosition, PyramidEntry
from src.types import Direction


class TestPyramidEntry:
    def test_dataclass_fields(self):
        entry = PyramidEntry(
            entry_number=1,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            units=10,
            n_at_entry=2.5,
            stop_price=95.0,
        )
        assert entry.entry_number == 1
        assert entry.entry_price == 100.0
        assert entry.units == 10
        assert entry.n_at_entry == 2.5
        assert entry.stop_price == 95.0


class TestPyramidPosition:
    def test_initial_entry(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        entry = pos.add_entry(datetime.now(), 100.0, 1, 2.5)

        assert pos.total_units == 1
        assert not pos.is_full
        assert entry.entry_number == 1
        assert entry.stop_price == 95.0  # 100 - 2*2.5

    def test_max_units_default(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        assert pos.max_units == 4

    def test_max_units_custom(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG, max_units=6)
        assert pos.max_units == 6

    def test_is_full(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG, max_units=4)
        for i in range(4):
            pos.add_entry(datetime.now(), 100.0 + i, 1, 2.5)
        assert pos.is_full
        assert pos.total_units == 4

    def test_total_units_multiple_entries(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 2, 2.5)
        pos.add_entry(datetime.now(), 101.25, 3, 2.5)
        assert pos.total_units == 5

    def test_average_entry_price(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 2, 2.5)
        pos.add_entry(datetime.now(), 105.0, 2, 2.5)
        # (100*2 + 105*2) / 4 = 102.5
        assert pos.average_entry_price == 102.5

    def test_average_entry_price_empty(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        assert pos.average_entry_price == 0.0

    def test_current_stop_empty(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        assert pos.current_stop == 0.0

    def test_current_stop_after_entry(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        assert pos.current_stop == 95.0  # 100 - 2*2.5

    def test_long_pyramid_price(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        # Next pyramid at 100 + 0.5*2.5 = 101.25
        assert pos.get_next_pyramid_price(2.5) == 101.25

    def test_short_pyramid_price(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.SHORT)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        # Next pyramid at 100 - 0.5*2.5 = 98.75
        assert pos.get_next_pyramid_price(2.5) == 98.75

    def test_get_next_pyramid_price_empty(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        assert pos.get_next_pyramid_price(2.5) == 0.0

    def test_can_pyramid_long_not_enough(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)

        can, msg = pos.can_pyramid(101.0, 2.5)  # Not enough
        assert not can

    def test_can_pyramid_long_exact(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)

        can, msg = pos.can_pyramid(101.25, 2.5)  # Exactly 0.5N
        assert can

    def test_can_pyramid_long_above(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)

        can, msg = pos.can_pyramid(102.0, 2.5)  # Above 0.5N
        assert can

    def test_can_pyramid_short_not_enough(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.SHORT)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)

        can, msg = pos.can_pyramid(99.0, 2.5)  # Not enough
        assert not can

    def test_can_pyramid_short_exact(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.SHORT)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)

        can, msg = pos.can_pyramid(98.75, 2.5)  # Exactly 0.5N down
        assert can

    def test_can_pyramid_when_full(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG, max_units=2)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        pos.add_entry(datetime.now(), 101.25, 1, 2.5)
        can, msg = pos.can_pyramid(105.0, 2.5)
        assert not can
        assert "최대 Unit" in msg

    def test_can_pyramid_empty_position(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        can, msg = pos.can_pyramid(100.0, 2.5)
        assert can
        assert "초기 진입" in msg

    def test_trailing_stop_update_long(self):
        """피라미딩 시 이전 진입의 스톱이 올라가야 함"""
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        e1 = pos.add_entry(datetime.now(), 100.0, 1, 2.5)  # stop=95.0
        assert pos.entries[0].stop_price == 95.0
        e2 = pos.add_entry(datetime.now(), 101.25, 1, 2.5)  # stop=96.25
        # e1's stop should be raised to 96.25
        assert pos.entries[0].stop_price == 96.25
        assert pos.entries[1].stop_price == 96.25

    def test_trailing_stop_update_short(self):
        """SHORT: 피라미딩 시 이전 스톱이 내려가야 함"""
        pos = PyramidPosition(symbol="SPY", direction=Direction.SHORT)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)  # stop=105.0
        assert pos.entries[0].stop_price == 105.0
        pos.add_entry(datetime.now(), 98.75, 1, 2.5)  # stop=103.75
        # e1's stop should be lowered to 103.75
        assert pos.entries[0].stop_price == 103.75

    def test_single_entry_no_trailing_stop_change(self):
        """단일 진입에서는 trailing stop 변경 없음"""
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        assert pos.entries[0].stop_price == 95.0

    def test_long_stop_hit_at_stop(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        assert pos.check_stop_hit(95.0)  # At stop

    def test_long_stop_hit_below(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        assert pos.check_stop_hit(94.0)  # Below stop

    def test_long_stop_not_hit(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        assert not pos.check_stop_hit(96.0)  # Above stop

    def test_short_stop_hit_at_stop(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.SHORT)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)  # stop=105
        assert pos.check_stop_hit(105.0)

    def test_short_stop_hit_above(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.SHORT)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        assert pos.check_stop_hit(106.0)

    def test_short_stop_not_hit(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.SHORT)
        pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        assert not pos.check_stop_hit(104.0)

    def test_stop_hit_empty_position(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG)
        assert not pos.check_stop_hit(50.0)

    def test_short_entry_stop_price(self):
        pos = PyramidPosition(symbol="SPY", direction=Direction.SHORT)
        entry = pos.add_entry(datetime.now(), 100.0, 1, 2.5)
        assert entry.stop_price == 105.0  # 100 + 2*2.5

    def test_multiple_pyramids_sequence(self):
        """4회 피라미딩 전체 시퀀스"""
        pos = PyramidPosition(symbol="SPY", direction=Direction.LONG, max_units=4)
        n = 2.5

        pos.add_entry(datetime.now(), 100.0, 1, n)   # entry 1
        pos.add_entry(datetime.now(), 101.25, 1, n)   # entry 2 (100 + 0.5*2.5)
        pos.add_entry(datetime.now(), 102.50, 1, n)   # entry 3
        pos.add_entry(datetime.now(), 103.75, 1, n)   # entry 4

        assert pos.is_full
        assert pos.total_units == 4
        assert len(pos.entries) == 4

        # All stops should be at the last entry's stop
        last_stop = 103.75 - 2 * 2.5  # 98.75
        for entry in pos.entries:
            assert entry.stop_price == last_stop


class TestPyramidManager:
    def test_create_position(self):
        pm = PyramidManager()
        pos = pm.create_position("SPY", Direction.LONG, datetime.now(), 100.0, 1, 2.5)
        assert pos.symbol == "SPY"
        assert len(pos.entries) == 1

    def test_create_position_uses_manager_settings(self):
        pm = PyramidManager(max_units=6, pyramid_interval_n=0.75)
        pos = pm.create_position("SPY", Direction.LONG, datetime.now(), 100.0, 1, 2.5)
        assert pos.max_units == 6
        assert pos.pyramid_interval_n == 0.75

    def test_get_position_exists(self):
        pm = PyramidManager()
        pm.create_position("SPY", Direction.LONG, datetime.now(), 100.0, 1, 2.5)
        assert pm.get_position("SPY") is not None

    def test_get_position_not_exists(self):
        pm = PyramidManager()
        assert pm.get_position("QQQ") is None

    def test_close_position(self):
        pm = PyramidManager()
        pm.create_position("SPY", Direction.LONG, datetime.now(), 100.0, 1, 2.5)
        pm.close_position("SPY")
        assert pm.get_position("SPY") is None

    def test_close_nonexistent_position(self):
        """존재하지 않는 포지션 close는 에러 없이 진행"""
        pm = PyramidManager()
        pm.close_position("NONEXISTENT")  # Should not raise

    def test_multiple_positions(self):
        pm = PyramidManager()
        pm.create_position("SPY", Direction.LONG, datetime.now(), 100.0, 1, 2.5)
        pm.create_position("QQQ", Direction.SHORT, datetime.now(), 300.0, 1, 5.0)

        spy = pm.get_position("SPY")
        qqq = pm.get_position("QQQ")
        assert spy is not None
        assert qqq is not None
        assert spy.direction == Direction.LONG
        assert qqq.direction == Direction.SHORT

    def test_overwrite_position(self):
        """같은 심볼로 새 포지션 생성하면 덮어씀"""
        pm = PyramidManager()
        pm.create_position("SPY", Direction.LONG, datetime.now(), 100.0, 1, 2.5)
        pm.create_position("SPY", Direction.SHORT, datetime.now(), 200.0, 2, 3.0)

        pos = pm.get_position("SPY")
        assert pos.direction == Direction.SHORT
        assert pos.entries[0].entry_price == 200.0

    def test_default_settings(self):
        pm = PyramidManager()
        assert pm.max_units == 4
        assert pm.pyramid_interval_n == 0.5
