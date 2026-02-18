"""
position_sizer.py 단위 테스트
- 2% 리스크 기반 포지션 사이징
- 스톱 계산
- 경계값
- AccountState 상태 추적
- Position 데이터 클래스
"""

import pytest
from datetime import datetime
from src.position_sizer import PositionSizer, AccountState, Position
from src.types import Direction


class TestPosition:
    def test_market_value(self):
        pos = Position(
            symbol="SPY",
            direction=Direction.LONG,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=95.0,
            current_price=105.0,
        )
        assert pos.market_value == 1050.0  # 10 * 105

    def test_market_value_zero_price(self):
        pos = Position(
            symbol="SPY",
            direction=Direction.LONG,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=95.0,
            current_price=0.0,
        )
        assert pos.market_value == 0.0

    def test_unrealized_pnl_long_profit(self):
        pos = Position(
            symbol="SPY",
            direction=Direction.LONG,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=95.0,
            current_price=110.0,
        )
        assert pos.unrealized_pnl == 100.0  # (110 - 100) * 10

    def test_unrealized_pnl_long_loss(self):
        pos = Position(
            symbol="SPY",
            direction=Direction.LONG,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=95.0,
            current_price=90.0,
        )
        assert pos.unrealized_pnl == -100.0  # (90 - 100) * 10

    def test_unrealized_pnl_short_profit(self):
        pos = Position(
            symbol="SPY",
            direction=Direction.SHORT,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=105.0,
            current_price=90.0,
        )
        assert pos.unrealized_pnl == 100.0  # (100 - 90) * 10

    def test_unrealized_pnl_short_loss(self):
        pos = Position(
            symbol="SPY",
            direction=Direction.SHORT,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=105.0,
            current_price=110.0,
        )
        assert pos.unrealized_pnl == -100.0  # (100 - 110) * 10

    def test_default_current_price(self):
        pos = Position(
            symbol="SPY",
            direction=Direction.LONG,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=95.0,
        )
        assert pos.current_price == 0.0


class TestPositionSizer:
    def test_basic_unit_size(self):
        sizer = PositionSizer(risk_percent=0.01)
        # 100000 * 0.01 / 5.0 = 200
        unit = sizer.calculate_unit(100000.0, 5.0)
        assert unit == 200

    def test_default_risk_percent(self):
        sizer = PositionSizer()
        assert sizer.risk_percent == 0.01

    def test_zero_n_returns_zero(self):
        sizer = PositionSizer()
        assert sizer.calculate_unit(100000.0, 0.0) == 0

    def test_zero_equity_returns_zero(self):
        sizer = PositionSizer()
        assert sizer.calculate_unit(0.0, 5.0) == 0

    def test_negative_n_returns_zero(self):
        sizer = PositionSizer()
        assert sizer.calculate_unit(100000.0, -1.0) == 0

    def test_negative_equity_returns_zero(self):
        sizer = PositionSizer()
        assert sizer.calculate_unit(-50000.0, 5.0) == 0

    def test_minimum_one_unit(self):
        sizer = PositionSizer(risk_percent=0.001)
        # Very small result: 1000 * 0.001 / 100 = 0.01, max(1, 0) = 1
        unit = sizer.calculate_unit(1000.0, 100.0)
        assert unit >= 1

    def test_large_account(self):
        sizer = PositionSizer(risk_percent=0.02)
        # 1000000 * 0.02 / 10.0 = 2000
        unit = sizer.calculate_unit(1000000.0, 10.0)
        assert unit == 2000

    def test_point_value(self):
        sizer = PositionSizer(risk_percent=0.01)
        # 100000 * 0.01 / (5.0 * 2.0) = 100
        unit = sizer.calculate_unit(100000.0, 5.0, point_value=2.0)
        assert unit == 100

    def test_stop_price_long(self):
        sizer = PositionSizer()
        stop = sizer.calculate_stop_price(100.0, 2.5, Direction.LONG)
        assert stop == 95.0  # 100 - 2*2.5

    def test_stop_price_short(self):
        sizer = PositionSizer()
        stop = sizer.calculate_stop_price(100.0, 2.5, Direction.SHORT)
        assert stop == 105.0  # 100 + 2*2.5

    def test_stop_price_custom_distance(self):
        sizer = PositionSizer()
        stop = sizer.calculate_stop_price(100.0, 2.5, Direction.LONG, stop_distance_n=3.0)
        assert stop == 92.5  # 100 - 3*2.5

    def test_stop_price_short_custom_distance(self):
        sizer = PositionSizer()
        stop = sizer.calculate_stop_price(100.0, 2.5, Direction.SHORT, stop_distance_n=1.0)
        assert stop == 102.5  # 100 + 1*2.5


class TestAccountState:
    def test_initial_state(self):
        account = AccountState(initial_capital=100000.0)
        assert account.current_equity == 100000.0
        assert account.cash == 100000.0
        assert account.peak_equity == 100000.0
        assert account.max_drawdown == 0.0

    def test_initial_realized_pnl(self):
        account = AccountState(initial_capital=100000.0)
        assert account.realized_pnl == 0.0
        assert account.total_trades == 0
        assert account.winning_trades == 0

    def test_update_equity_no_positions(self):
        account = AccountState(initial_capital=100000.0)
        account.cash = 110000.0
        account.update_equity()
        assert account.current_equity == 110000.0
        assert account.peak_equity == 110000.0

    def test_update_equity_tracks_peak(self):
        account = AccountState(initial_capital=100000.0)
        account.cash = 110000.0
        account.update_equity()
        assert account.peak_equity == 110000.0

        # Equity drops but peak stays
        account.cash = 105000.0
        account.update_equity()
        assert account.peak_equity == 110000.0

    def test_drawdown_calculation(self):
        account = AccountState(initial_capital=100000.0)
        account.cash = 110000.0
        account.update_equity()  # peak = 110k
        account.cash = 99000.0
        account.update_equity()  # dd = (110k - 99k)/110k = 10%
        assert abs(account.max_drawdown - 0.1) < 0.01

    def test_max_drawdown_persists(self):
        """max_drawdown은 더 큰 값만 기록"""
        account = AccountState(initial_capital=100000.0)
        account.cash = 80000.0
        account.update_equity()  # dd = 20%
        dd_20 = account.max_drawdown

        account.cash = 90000.0
        account.update_equity()  # dd 줄어듦
        assert account.max_drawdown == dd_20  # 여전히 20%

    def test_update_equity_with_positions(self):
        account = AccountState(initial_capital=100000.0)
        pos = Position(
            symbol="SPY",
            direction=Direction.LONG,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=95.0,
            current_price=100.0,
        )
        account.positions["SPY"] = pos
        account.cash = 99000.0
        account.update_equity()
        # equity = cash(99000) + position_value(10*100=1000) = 100000
        assert account.current_equity == 100000.0

    def test_update_equity_with_prices(self):
        account = AccountState(initial_capital=100000.0)
        pos = Position(
            symbol="SPY",
            direction=Direction.LONG,
            entry_date=datetime(2025, 1, 1),
            entry_price=100.0,
            quantity=10,
            n_at_entry=2.5,
            stop_price=95.0,
            current_price=100.0,
        )
        account.positions["SPY"] = pos
        account.cash = 99000.0
        account.update_equity(prices={"SPY": 110.0})
        # equity = cash(99000) + position_value(10*110=1100) = 100100
        assert account.current_equity == 100100.0
        assert pos.current_price == 110.0

    def test_empty_positions_dict(self):
        account = AccountState(initial_capital=100000.0)
        assert len(account.positions) == 0
