"""
position_tracker.py 단위 테스트
- 포지션 라이프사이클
- 피라미딩
- 스톱로스
- R-배수 계산
"""

import json

import pytest

from src.position_tracker import Position, PositionTracker
from src.types import Direction


@pytest.fixture
def tracker(temp_data_dir):
    return PositionTracker(base_dir=str(temp_data_dir))


class TestPositionLifecycle:
    def test_open_position(self, tracker):
        pos = tracker.open_position(symbol="SPY", system=1, direction="LONG", entry_price=100.0, n_value=2.5, shares=40)
        assert pos.symbol == "SPY"
        assert pos.status == "open"
        assert pos.units == 1
        assert pos.total_shares == 40
        assert pos.stop_loss == 95.0  # 100 - 2*2.5

    def test_close_position(self, tracker):
        pos = tracker.open_position(symbol="SPY", system=1, direction="LONG", entry_price=100.0, n_value=2.5, shares=40)
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
        assert tracker.should_pyramid(pos, 101.25) is True  # Exactly 0.5N


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
        tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)  # stop=95
        tracker.open_position("QQQ", 1, "SHORT", 200.0, 5.0, 20)  # stop=210
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


class TestDirectionEnum:
    """Direction enum 변환 및 직렬화 테스트"""

    def test_post_init_converts_string_to_enum(self, tracker):
        """str 'LONG' → Direction.LONG 자동 변환"""
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        assert isinstance(pos.direction, Direction)
        assert pos.direction == Direction.LONG

    def test_post_init_converts_short_string(self, tracker):
        """str 'SHORT' → Direction.SHORT 자동 변환"""
        pos = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        assert isinstance(pos.direction, Direction)
        assert pos.direction == Direction.SHORT

    def test_post_init_accepts_enum_directly(self, tracker):
        """Direction enum 직접 전달 시 그대로 유지"""
        pos = tracker.open_position("SPY", 1, Direction.LONG, 100.0, 2.5, 40)
        assert pos.direction == Direction.LONG

    def test_invalid_direction_raises(self):
        """잘못된 direction 값 → ValueError"""
        with pytest.raises(ValueError):
            Position(
                position_id="test",
                symbol="SPY",
                system=1,
                direction="INVALID",
                entry_date="2025-01-01",
                entry_price=100.0,
                entry_n=2.0,
                units=1,
                max_units=4,
                shares_per_unit=40,
                total_shares=40,
                stop_loss=95.0,
                pyramid_level=0,
                exit_period=10,
                status="open",
                last_update="2025-01-01",
            )

    def test_to_dict_serializes_as_string(self, tracker):
        """to_dict()는 direction을 문자열로 출력"""
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        d = pos.to_dict()
        assert d["direction"] == "LONG"
        assert isinstance(d["direction"], str)

    def test_from_dict_round_trip(self, tracker):
        """to_dict() → from_dict() 왕복 시 데이터 무결성 유지"""
        original = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        restored = Position.from_dict(original.to_dict())

        assert restored.direction == Direction.SHORT
        assert isinstance(restored.direction, Direction)
        assert restored.symbol == original.symbol
        assert restored.entry_price == original.entry_price
        assert restored.stop_loss == original.stop_loss

    def test_json_round_trip(self, tracker):
        """JSON 직렬화·역직렬화 시 Direction 복원"""
        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        json_str = json.dumps(pos.to_dict())
        restored = Position.from_dict(json.loads(json_str))

        assert restored.direction == Direction.LONG
        assert isinstance(restored.direction, Direction)

    def test_persistence_preserves_direction_type(self, temp_data_dir):
        """파일 저장 후 재로드 시 Direction enum 타입 유지"""
        tracker1 = PositionTracker(base_dir=str(temp_data_dir))
        tracker1.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)

        tracker2 = PositionTracker(base_dir=str(temp_data_dir))
        loaded = tracker2.get_open_positions()[0]
        assert isinstance(loaded.direction, Direction)
        assert loaded.direction == Direction.SHORT


class TestShortDirection:
    """SHORT 방향 PnL 및 R-multiple 테스트"""

    def test_short_pnl_profit(self, tracker):
        """SHORT 수익 시 PnL 양수"""
        pos = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        closed = tracker.close_position(pos.position_id, 90.0)
        # PnL: (100-90) * 40 = 400
        assert closed.pnl == 400.0

    def test_short_pnl_loss(self, tracker):
        """SHORT 손실 시 PnL 음수"""
        pos = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        closed = tracker.close_position(pos.position_id, 110.0)
        # PnL: (100-110) * 40 = -400
        assert closed.pnl == -400.0

    def test_short_r_multiple(self, tracker):
        """SHORT R-배수 계산"""
        pos = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        closed = tracker.close_position(pos.position_id, 95.0)
        # R = (100-95) / (2*2.5) = 5/5 = 1.0R
        assert closed.r_multiple == 1.0

    def test_short_stop_loss_r(self, tracker):
        """SHORT 스톱로스 청산 시 -1.0R"""
        pos = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        # stop_loss = 100 + 2*2.5 = 105
        closed = tracker.close_position(pos.position_id, pos.stop_loss)
        assert abs(closed.r_multiple - (-1.0)) < 0.01

    def test_short_pyramid(self, tracker):
        """SHORT 피라미딩: 가격 하락 시 트리거"""
        pos = tracker.open_position("SPY", 1, "SHORT", 100.0, 2.5, 40)
        # 0.5N = 1.25 하락 필요
        assert tracker.should_pyramid(pos, 99.0) is False  # Not enough
        assert tracker.should_pyramid(pos, 98.75) is True  # Exactly 0.5N


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
        assert summary["total_positions"] == 2
        assert summary["open_positions"] == 1
        assert summary["closed_positions"] == 1


class TestEntryReason:
    def test_entry_reason_serialization(self, tracker):
        """entry_reason 필드가 직렬화/역직렬화된다"""
        from src.position_tracker import Position

        pos = tracker.open_position("SPY", 1, "LONG", 100.0, 2.5, 40)
        pos.entry_reason = "S1_20D_BREAKOUT"
        d = pos.to_dict()
        restored = Position.from_dict(d)
        assert restored.entry_reason == "S1_20D_BREAKOUT"

    def test_from_dict_unknown_key_resilience(self):
        """from_dict은 알 수 없는 키를 무시한다"""
        from src.position_tracker import Position
        from src.types import Direction

        data = {
            "position_id": "pos-001",
            "symbol": "SPY",
            "system": 1,
            "direction": Direction.LONG,
            "entry_date": "2025-01-01",
            "entry_price": 100.0,
            "entry_n": 2.5,
            "stop_loss": 95.0,
            "total_shares": 40,
            "units": 1,
            "max_units": 4,
            "shares_per_unit": 40,
            "pyramid_level": 0,
            "exit_period": 10,
            "status": "open",
            "last_update": "2025-01-01",
            "unknown_future_field": "some_value",  # 알 수 없는 키
        }
        pos = Position.from_dict(data)
        assert pos.symbol == "SPY"
        assert pos.entry_price == 100.0

    def test_from_dict_missing_optional_key(self):
        """from_dict은 entry_reason 없이도 동작한다 (하위 호환)"""
        from src.position_tracker import Position
        from src.types import Direction

        data = {
            "position_id": "pos-002",
            "symbol": "QQQ",
            "system": 2,
            "direction": Direction.LONG,
            "entry_date": "2025-02-01",
            "entry_price": 200.0,
            "entry_n": 3.0,
            "stop_loss": 194.0,
            "total_shares": 30,
            "units": 1,
            "max_units": 4,
            "shares_per_unit": 30,
            "pyramid_level": 0,
            "exit_period": 20,
            "status": "open",
            "last_update": "2025-02-01",
            # entry_reason 없음
        }
        pos = Position.from_dict(data)
        assert pos.entry_reason is None
