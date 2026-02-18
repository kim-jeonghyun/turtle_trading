"""
backtester.py 단위 테스트
- BUG-1 수정 검증 (calculate_unit_size 인자 순서)
- BUG-2 수정 검증 (미실현 P&L 계산)
- 백테스트 기본 동작
"""

import pytest
import pandas as pd
import numpy as np
from src.backtester import TurtleBacktester, BacktestConfig, BacktestResult
from src.indicators import add_turtle_indicators, calculate_unit_size


class TestBugFixes:
    def test_bug1_argument_order(self):
        """BUG-1: calculate_unit_size 인자 순서 검증"""
        n_value = 5.0
        equity = 100000.0
        risk = 0.01

        # 올바른 호출: (n_value, equity, risk_per_unit=risk)
        correct = calculate_unit_size(n_value, equity, risk_per_unit=risk)
        # 100000 * 0.01 / 5.0 = 200
        assert correct == 200

        # 잘못된 호출 (이전 버그): (equity, n_value, risk)
        # 이는 equity를 n_value로, n_value를 equity로 사용
        wrong = calculate_unit_size(equity, n_value, risk)
        # 5.0 * risk(=100000) / 100000(=n_value) -> 완전히 다른 결과
        assert wrong != correct

    def test_bug2_equity_includes_unrealized(self, trending_up_df):
        """BUG-2: equity curve에 미실현 P&L이 반영되는지 검증"""
        config = BacktestConfig(
            initial_capital=100000.0,
            risk_percent=0.01,
            system=2,  # System 2 (55일) - 필터 없음
            use_filter=False
        )
        bt = TurtleBacktester(config)
        data = {'TEST': trending_up_df.copy()}
        result = bt.run(data)

        # Equity curve가 있어야 함
        assert not result.equity_curve.empty

        # 포지션이 오픈된 상태에서 equity가 cash와 달라야 함
        # (미실현 P&L이 반영되면 equity != cash)
        if len(result.equity_curve) > 0:
            has_difference = (result.equity_curve['equity'] != result.equity_curve['cash']).any()
            # 포지션이 있었다면 차이가 있어야 함
            if result.total_trades > 0 or len(bt.pyramid_manager.positions) > 0:
                assert has_difference, "Equity should include unrealized P&L"


class TestBacktestBasic:
    def test_empty_data(self):
        """빈 데이터로 백테스트"""
        config = BacktestConfig()
        bt = TurtleBacktester(config)
        result = bt.run({})
        assert result.total_trades == 0

    def test_backtest_runs_without_error(self, trending_up_df):
        """백테스트가 에러 없이 실행"""
        config = BacktestConfig(
            initial_capital=100000.0,
            system=2,
            use_filter=False
        )
        bt = TurtleBacktester(config)
        data = {'SPY': trending_up_df.copy()}
        result = bt.run(data)

        assert isinstance(result, BacktestResult)
        assert result.final_equity > 0

    def test_config_defaults(self):
        """기본 설정값 확인"""
        config = BacktestConfig()
        assert config.initial_capital == 100000.0
        assert config.risk_percent == 0.01
        assert config.max_units == 4
        assert config.pyramid_interval_n == 0.5
        assert config.stop_distance_n == 2.0


class TestBacktestSystem1:
    """System 1 백테스트: 20일 돌파, 10일 청산, 필터 적용"""

    def _make_breakout_data(self):
        """20일 돌파 발생하는 데이터 생성"""
        np.random.seed(123)
        dates = pd.date_range(start="2025-01-01", periods=120, freq="B")
        price = 100.0
        rows = []
        for i, date in enumerate(dates):
            if i < 60:
                # 횡보 구간
                change = np.random.normal(0, 0.5)
            elif i < 80:
                # 강한 상승 (20일 최고가 돌파 유도)
                change = abs(np.random.normal(1.5, 0.5))
            elif i < 100:
                # 하락 (10일 최저가 이탈 유도)
                change = -abs(np.random.normal(1.5, 0.5))
            else:
                # 재횡보
                change = np.random.normal(0, 0.5)

            open_price = price
            close = price + change
            high = max(open_price, close) + abs(np.random.normal(0.3, 0.1))
            low = min(open_price, close) - abs(np.random.normal(0.3, 0.1))
            rows.append({
                "date": date,
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": int(np.random.uniform(1000000, 5000000)),
            })
            price = close

        return pd.DataFrame(rows)

    def test_system1_with_filter(self):
        """System 1 필터 포함 백테스트"""
        config = BacktestConfig(
            initial_capital=100000.0,
            system=1,
            use_filter=True,
        )
        bt = TurtleBacktester(config)
        data = {"SPY": self._make_breakout_data()}
        result = bt.run(data)

        assert isinstance(result, BacktestResult)
        assert result.final_equity > 0

    def test_system1_without_filter(self):
        """System 1 필터 없이"""
        config = BacktestConfig(
            initial_capital=100000.0,
            system=1,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        data = {"SPY": self._make_breakout_data()}
        result = bt.run(data)

        assert isinstance(result, BacktestResult)

    def test_system2_full_run(self):
        """System 2 (55일 돌파) 전체 실행"""
        config = BacktestConfig(
            initial_capital=100000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        data = {"SPY": self._make_breakout_data()}
        result = bt.run(data)

        assert isinstance(result, BacktestResult)

    def test_multiple_symbols(self):
        """여러 종목 동시 백테스트"""
        config = BacktestConfig(
            initial_capital=200000.0,
            system=1,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        data = {
            "SPY": self._make_breakout_data(),
            "QQQ": self._make_breakout_data(),
        }
        result = bt.run(data)

        assert isinstance(result, BacktestResult)
        assert result.final_equity > 0


class TestBacktestTradeDataclass:
    def test_trade_defaults(self):
        from src.backtester import Trade
        trade = Trade(symbol="SPY", entry_date=pd.Timestamp("2025-01-01"), entry_price=100.0)
        assert trade.exit_date is None
        assert trade.exit_price is None
        assert trade.direction == "LONG"
        assert trade.quantity == 0
        assert trade.pnl == 0.0
        assert trade.exit_reason == ""


class TestBacktestEntryExitColumns:
    def test_system1_columns(self):
        config = BacktestConfig(system=1)
        bt = TurtleBacktester(config)
        cols = bt._get_entry_exit_columns()
        assert cols == ("dc_high_20", "dc_low_20", "dc_low_10", "dc_high_10")

    def test_system2_columns(self):
        config = BacktestConfig(system=2)
        bt = TurtleBacktester(config)
        cols = bt._get_entry_exit_columns()
        assert cols == ("dc_high_55", "dc_low_55", "dc_low_20", "dc_high_20")
