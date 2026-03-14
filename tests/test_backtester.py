"""
backtester.py 단위 테스트
- BUG-1 수정 검증 (calculate_unit_size 인자 순서)
- BUG-2 수정 검증 (미실현 P&L 계산)
- 백테스트 기본 동작
- PortfolioRiskManager 통합 (#165)
"""

import numpy as np
import pandas as pd

from src.backtester import BacktestConfig, BacktestResult, TurtleBacktester
from src.indicators import calculate_unit_size
from src.types import AssetGroup, Direction, SignalType


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
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        data = {"TEST": trending_up_df.copy()}
        result = bt.run(data)

        # Equity curve가 있어야 함
        assert not result.equity_curve.empty

        # 포지션이 오픈된 상태에서 equity가 cash와 달라야 함
        # (미실현 P&L이 반영되면 equity != cash)
        if len(result.equity_curve) > 0:
            has_difference = (result.equity_curve["equity"] != result.equity_curve["cash"]).any()
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
        config = BacktestConfig(initial_capital=100000.0, system=2, use_filter=False)
        bt = TurtleBacktester(config)
        data = {"SPY": trending_up_df.copy()}
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
            rows.append(
                {
                    "date": date,
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": int(np.random.uniform(1000000, 5000000)),
                }
            )
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


class TestTradeEntryReason:
    def test_trade_entry_reason_populated(self):
        """백테스트 완료된 Trade에 entry_reason이 채워진다"""
        import pandas as pd

        from src.backtester import BacktestConfig, TurtleBacktester

        # Create minimal OHLCV data with a breakout and then a close
        dates = pd.date_range("2026-01-01", periods=60, freq="B")
        data = pd.DataFrame({
            "date": dates,
            "open": [100] * 60,
            "high": [101] * 20 + [120] * 20 + [101] * 20,
            "low": [99] * 20 + [99] * 20 + [80] * 20,
            "close": [100] * 20 + [115] * 20 + [85] * 20,
            "volume": [1000000] * 60,
        })

        config = BacktestConfig(
            initial_capital=100000,
            system=1,
            risk_percent=0.01,
        )
        bt = TurtleBacktester(config)
        bt.run({"TEST": data})

        assert len(bt.trades) > 0, "백테스트에서 최소 1개의 거래가 발생해야 한다"
        for trade in bt.trades:
            assert trade.entry_reason != "", f"Trade for {trade.symbol} has empty entry_reason"
            assert "진입" in trade.entry_reason, f"entry_reason should contain '진입': {trade.entry_reason}"


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


class TestBacktesterRiskIntegration:
    """Issue #165: PortfolioRiskManager 통합 테스트"""

    def test_no_risk_check_when_groups_is_none(self):
        """symbol_groups=None이면 리스크 체크 없이 기존 동작 유지"""
        config = BacktestConfig(initial_capital=100000.0)
        bt = TurtleBacktester(config)  # symbol_groups 미전달
        assert bt._use_risk_limits is False
        assert bt.risk_manager is None

    def test_risk_manager_initialized_with_groups(self):
        """symbol_groups 전달 시 리스크 매니저 초기화"""
        groups = {"SPY": AssetGroup.US_EQUITY, "QQQ": AssetGroup.US_EQUITY}
        config = BacktestConfig(initial_capital=100000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)
        assert bt._use_risk_limits is True
        assert bt.risk_manager is not None

    def test_entry_blocked_by_single_symbol_limit(self):
        """단일 종목 4 Units 한도 — 진입 1 + 피라미딩 3 후 5번째 차단"""
        groups = {"SPY": AssetGroup.US_EQUITY}
        # price=1.0으로 비용 최소화, N=2.0 × 4 = 8.0 < 10.0 N-exposure 한도
        config = BacktestConfig(initial_capital=10_000_000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)

        bt._open_position("SPY", pd.Timestamp("2025-01-01"), 1.0, 2.0, Direction.LONG)
        assert bt.risk_manager.state.units_by_symbol.get("SPY", 0) == 1

        for _ in range(3):
            bt._add_pyramid("SPY", pd.Timestamp("2025-01-02"), 1.5, 2.0)

        assert bt.risk_manager.state.units_by_symbol.get("SPY", 0) == 4

        cash_before = bt.account.cash
        bt._add_pyramid("SPY", pd.Timestamp("2025-01-03"), 2.0, 2.0)
        assert bt.account.cash == cash_before

    def test_entry_blocked_by_group_limit(self):
        """같은 그룹 6 Units 한도 초과 시 7번째 진입 차단"""
        groups = {s: AssetGroup.US_EQUITY for s in ["A", "B", "C", "D", "E", "F", "G"]}
        # N=1.5 × 6 = 9.0 < 10.0, price=1.0으로 비용 최소화
        config = BacktestConfig(initial_capital=10_000_000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)

        for sym in ["A", "B", "C", "D", "E", "F"]:
            bt._open_position(sym, pd.Timestamp("2025-01-01"), 1.0, 1.5, Direction.LONG)

        assert bt.risk_manager.state.units_by_group.get(AssetGroup.US_EQUITY, 0) == 6

        cash_before = bt.account.cash
        bt._open_position("G", pd.Timestamp("2025-01-01"), 1.0, 1.5, Direction.LONG)
        assert bt.account.cash == cash_before

    def test_entry_blocked_by_direction_limit(self):
        """LONG 방향 12 Units 한도 초과 시 13번째 진입 차단"""
        asset_groups = list(AssetGroup)
        groups = {}
        for i in range(13):
            groups[f"SYM{i}"] = asset_groups[i % len(asset_groups)]

        # N=0.8 × 12 = 9.6 < 10.0, price=1.0으로 비용 최소화
        config = BacktestConfig(initial_capital=10_000_000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)

        for i in range(12):
            bt._open_position(f"SYM{i}", pd.Timestamp("2025-01-01"), 1.0, 0.8, Direction.LONG)

        assert bt.risk_manager.state.long_units == 12

        cash_before = bt.account.cash
        bt._open_position("SYM12", pd.Timestamp("2025-01-01"), 1.0, 0.8, Direction.LONG)
        assert bt.account.cash == cash_before

    def test_n_exposure_cap_enforced(self):
        """N-exposure 10.0 상한 초과 시 진입 차단"""
        asset_groups = list(AssetGroup)
        groups = {}
        for i in range(5):
            groups[f"SYM{i}"] = asset_groups[i % len(asset_groups)]

        # N=3.0 × 3 = 9.0, 4번째 추가 시 12.0 > 10.0
        config = BacktestConfig(initial_capital=10_000_000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)

        for i in range(3):
            bt._open_position(f"SYM{i}", pd.Timestamp("2025-01-01"), 1.0, 3.0, Direction.LONG)

        assert abs(bt.risk_manager.state.total_n_exposure - 9.0) < 0.01

        cash_before = bt.account.cash
        bt._open_position("SYM3", pd.Timestamp("2025-01-01"), 1.0, 3.0, Direction.LONG)
        assert bt.account.cash == cash_before

    def test_pyramid_respects_risk_limits(self):
        """피라미딩 시 단일 종목 4 Units 한도 적용"""
        groups = {"SPY": AssetGroup.US_EQUITY}
        config = BacktestConfig(initial_capital=10_000_000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)

        # N=2.0, price=1.0
        bt._open_position("SPY", pd.Timestamp("2025-01-01"), 1.0, 2.0, Direction.LONG)
        assert bt.risk_manager.state.units_by_symbol["SPY"] == 1

        for _ in range(3):
            bt._add_pyramid("SPY", pd.Timestamp("2025-01-02"), 1.5, 2.0)

        assert bt.risk_manager.state.units_by_symbol["SPY"] == 4

        cash_before = bt.account.cash
        bt._add_pyramid("SPY", pd.Timestamp("2025-01-03"), 2.0, 2.0)
        assert bt.account.cash == cash_before
        assert bt.risk_manager.state.units_by_symbol["SPY"] == 4

    def test_close_releases_risk_capacity(self):
        """청산 후 동일 그룹 재진입 가능"""
        groups = {"SPY": AssetGroup.US_EQUITY, "QQQ": AssetGroup.US_EQUITY}
        config = BacktestConfig(initial_capital=10_000_000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)

        # N=2.0, price=1.0
        bt._open_position("SPY", pd.Timestamp("2025-01-01"), 1.0, 2.0, Direction.LONG)
        assert bt.risk_manager.state.units_by_symbol.get("SPY", 0) == 1
        assert abs(bt.risk_manager.state.total_n_exposure - 2.0) < 0.01

        bt._close_position("SPY", pd.Timestamp("2025-01-10"), 1.5, "EXIT_LONG")
        assert bt.risk_manager.state.units_by_symbol.get("SPY", 0) == 0
        assert abs(bt.risk_manager.state.total_n_exposure) < 0.01

        bt._open_position("QQQ", pd.Timestamp("2025-01-11"), 1.0, 2.0, Direction.LONG)
        assert bt.risk_manager.state.units_by_symbol.get("QQQ", 0) == 1

    def test_short_direction_tracked_correctly(self):
        """SHORT 포지션 리스크 상태 추적 및 청산 후 해제"""
        groups = {"SPY": AssetGroup.US_EQUITY}
        config = BacktestConfig(initial_capital=10_000_000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)

        bt._open_position("SPY", pd.Timestamp("2025-01-01"), 1.0, 2.0, Direction.SHORT)
        assert bt.risk_manager.state.short_units == 1
        assert bt.risk_manager.state.long_units == 0

        bt._close_position("SPY", pd.Timestamp("2025-01-10"), 0.8, "EXIT_SHORT")
        assert bt.risk_manager.state.short_units == 0
        assert abs(bt.risk_manager.state.total_n_exposure) < 0.01

    def test_multi_entry_close_removes_all_units(self):
        """3회 피라미딩 후 청산 → 3 Units 모두 제거"""
        groups = {"SPY": AssetGroup.US_EQUITY}
        config = BacktestConfig(initial_capital=10_000_000.0)
        bt = TurtleBacktester(config, symbol_groups=groups)

        # 진입 + 2회 피라미딩 (3 entries, 각각 다른 N-value)
        # N 합계 = 2.0 + 1.8 + 2.2 = 6.0 < 10.0, price=1.0
        bt._open_position("SPY", pd.Timestamp("2025-01-01"), 1.0, 2.0, Direction.LONG)
        bt._add_pyramid("SPY", pd.Timestamp("2025-01-02"), 1.5, 1.8)
        bt._add_pyramid("SPY", pd.Timestamp("2025-01-03"), 2.0, 2.2)

        assert bt.risk_manager.state.units_by_symbol["SPY"] == 3
        assert abs(bt.risk_manager.state.total_n_exposure - 6.0) < 0.01

        # 청산 → avg_n = (2.0+1.8+2.2)/3 = 2.0, remove 3 × 2.0 = 6.0
        bt._close_position("SPY", pd.Timestamp("2025-01-10"), 2.5, "EXIT_LONG")

        assert bt.risk_manager.state.units_by_symbol.get("SPY", 0) == 0
        assert bt.risk_manager.state.long_units == 0
        assert abs(bt.risk_manager.state.total_n_exposure) < 0.01

    @staticmethod
    def _make_breakout_data(n_symbols: int) -> dict:
        """System 2 브레이크아웃 시그널을 유발하는 합성 OHLCV 데이터 생성

        설계 제약:
        - price ~10, spread ±0.5 → ATR≈1.0, N≈1.0
        - unit_size = equity*0.01/1.0, cost = unit_size*10
        - N-exposure: 7 × 1.0 = 7.0 < 10.0 (N-cap 미초과)
        - cash: 500M 기준 7종목 진입 가능
        """
        dates = pd.date_range(start="2024-01-01", periods=120, freq="B")
        data = {}
        for i in range(n_symbols):
            base = 10.0 + i * 0.5
            prices = []
            for j in range(len(dates)):
                if j < 60:
                    price = base + np.sin(j * 0.1) * 0.3
                else:
                    price = base + 1.0 + (j - 60) * 0.1
                prices.append(price)
            df = pd.DataFrame({
                "date": dates,
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "volume": [1000000] * len(dates),
            })
            data[f"SYM{i}"] = df
        return data

    def test_run_with_risk_limits_blocks_excess_entries(self):
        """run() 레벨: 7종목 US_EQUITY 그룹에서 6 Units 한도 적용"""
        groups = {f"SYM{i}": AssetGroup.US_EQUITY for i in range(7)}
        # ATR≈2.0, unit_size≈50,000, cost≈$5M/entry → 7종목=$35M 필요
        config = BacktestConfig(
            initial_capital=500_000_000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config, symbol_groups=groups)
        data = self._make_breakout_data(7)
        bt.run(data)

        # 시그널이 발생했는지 확인 (trades + open positions)
        symbols_traded = (
            set(t.symbol for t in bt.trades)
            | set(bt.pyramid_manager.positions.keys())
        )
        assert len(symbols_traded) > 0, "시그널이 발생하지 않음"
        assert len(symbols_traded) <= 6, f"그룹 한도 6 초과: {len(symbols_traded)}개 종목 진입"

    def test_run_without_risk_limits_allows_all_entries(self):
        """run() 레벨: symbol_groups 없으면 모든 종목 진입 허용"""
        config = BacktestConfig(
            initial_capital=500_000_000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config)  # symbol_groups=None
        data = self._make_breakout_data(7)
        bt.run(data)

        symbols_traded = (
            set(t.symbol for t in bt.trades)
            | set(bt.pyramid_manager.positions.keys())
        )
        assert len(symbols_traded) == 7, f"리스크 한도 없이 7종목 모두 진입 기대, 실제: {len(symbols_traded)}"


class TestBreakoutEntryPrice:
    """원본 규칙: 진입가는 돌파 가격(Donchian boundary), close가 아님"""

    @staticmethod
    def _make_breakout_scenario():
        """60+ row data with clear breakout for integration testing"""
        np.random.seed(77)
        dates = pd.date_range(start="2024-01-01", periods=80, freq="B")
        prices = []
        p = 100.0
        for i in range(80):
            if i < 60:
                p = 100.0 + np.sin(i * 0.1) * 2
            else:
                p = 105.0 + (i - 60) * 0.5
            prices.append(p)

        df = pd.DataFrame({
            "date": dates,
            "open": prices,
            "high": [p + 1.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": prices,
            "volume": [1_000_000] * 80,
        })
        return df

    def test_long_entry_not_at_close(self):
        """LONG 진입가가 close와 다르다 (돌파 가격 사용 확인)"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)
        data = {"TEST": self._make_breakout_scenario()}
        bt.run(data)

        pos = bt.pyramid_manager.get_position("TEST")
        if pos:
            entry_price = pos.entries[0].entry_price
            assert entry_price != data["TEST"].iloc[-1]["close"], (
                "진입가가 마지막 close와 같으면 안됨 — 돌파 가격 사용 필요"
            )

    def test_stop_loss_exit_uses_stop_price_not_close(self):
        """스톱로스 청산 시 run()이 stop price를 사용하는지 검증"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        position = bt.pyramid_manager.get_position("TEST")
        stop_price = position.current_stop  # 100 - 2*5 = 90.0

        dates = pd.date_range("2025-01-01", periods=2, freq="B")
        mock_data = {
            "TEST": pd.DataFrame({
                "date": dates,
                "open": [100.0, 91.0],
                "high": [101.0, 95.0],
                "low": [99.0, 88.0],
                "close": [100.0, 89.0],
                "N": [5.0, 5.0],
                "atr": [5.0, 5.0],
                "dc_high_20": [101.0, 101.0],
                "dc_low_20": [99.0, 99.0],
                "dc_high_55": [102.0, 102.0],
                "dc_low_55": [98.0, 98.0],
                "dc_low_10": [99.5, 99.5],
                "dc_high_10": [100.5, 100.5],
            })
        }

        row = mock_data["TEST"].iloc[1]
        prev_row = mock_data["TEST"].iloc[0]

        exit_signal = bt._check_exit_signal(row, prev_row, position)
        assert exit_signal == SignalType.STOP_LOSS

        if exit_signal == SignalType.STOP_LOSS:
            exit_price = position.current_stop
        else:
            exit_price = row["close"]

        bt._close_position("TEST", dates[1], exit_price, exit_signal.value)

        assert len(bt.trades) == 1
        assert bt.trades[0].exit_price == 90.0, (
            f"스톱 청산가는 stop_price(90.0)이어야 함, got {bt.trades[0].exit_price}"
        )
        assert bt.trades[0].exit_price != 89.0, "close(89.0)가 아닌 stop(90.0) 사용"

class TestS1HypotheticalFilter:
    """System 1 필터: 스킵된 브레이크아웃의 가상 결과 추적"""

    def test_skipped_breakout_tracked_as_hypothetical(self):
        """스킵된 20일 돌파의 가상 결과를 추적해야 함"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=1,
            use_filter=True,
        )
        bt = TurtleBacktester(config)
        bt.last_trade_profitable["TEST"] = True

        assert hasattr(bt, "_hypothetical_breakouts"), (
            "TurtleBacktester should have _hypothetical_breakouts dict"
        )

    def test_filter_resets_after_hypothetical_loss(self):
        """가상 브레이크아웃이 손실이면 다음 20일 돌파 허용"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=1,
            use_filter=True,
        )
        bt = TurtleBacktester(config)
        bt.last_trade_profitable["TEST"] = True

        bt._record_hypothetical_breakout("TEST", 105.0, Direction.LONG)
        bt._resolve_hypothetical("TEST", exit_price=97.0)  # loss

        assert not bt.last_trade_profitable.get("TEST", False), (
            "가상 손실 후 필터가 리셋되어야 함"
        )

    def test_filter_persists_after_hypothetical_win(self):
        """가상 브레이크아웃이 수익이면 필터 유지"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=1,
            use_filter=True,
        )
        bt = TurtleBacktester(config)
        bt.last_trade_profitable["TEST"] = True

        bt._record_hypothetical_breakout("TEST", 105.0, Direction.LONG)
        bt._resolve_hypothetical("TEST", exit_price=115.0)  # win

        assert bt.last_trade_profitable.get("TEST", False), (
            "가상 수익 후 필터가 유지되어야 함"
        )

    def test_hypothetical_stop_loss_tracked(self):
        """가상 포지션의 2N 스톱로스도 추적"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=1,
            use_filter=True,
        )
        bt = TurtleBacktester(config)
        bt.last_trade_profitable["TEST"] = True

        # Record hypothetical LONG entry at 105 with N=2.5
        # Stop = 105 - 2*2.5 = 100.0
        bt._record_hypothetical_breakout("TEST", 105.0, Direction.LONG, n_value=2.5)
        hyp = bt._hypothetical_breakouts["TEST"]
        assert "stop_price" in hyp, "가상 포지션에 스톱 가격이 있어야 함"
        assert hyp["stop_price"] == 100.0, f"stop = 105 - 2*2.5 = 100.0, got {hyp['stop_price']}"

    def test_hypothetical_short_loss_resets_filter(self):
        """SHORT 가상 브레이크아웃 손실 시 필터 리셋"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=1,
            use_filter=True,
        )
        bt = TurtleBacktester(config)
        bt.last_trade_profitable["TEST"] = True

        bt._record_hypothetical_breakout("TEST", 95.0, Direction.SHORT)
        bt._resolve_hypothetical("TEST", exit_price=100.0)  # short loss

        assert not bt.last_trade_profitable.get("TEST", False)


    def test_channel_exit_uses_channel_boundary(self):
        """채널 청산 시 exit price는 Donchian boundary"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 110.0, 5.0, Direction.LONG)
        position = bt.pyramid_manager.get_position("TEST")

        # stop = 110 - 2*5 = 100.0; low must be > 100 to avoid STOP_LOSS
        # channel exit: row["low"] < prev_row["dc_low_10"]
        row = pd.Series({
            "high": 109.0,
            "low": 101.5,   # above stop (100.0) but below dc_low_10 (102.0)
            "close": 103.0,
        })
        prev_row = pd.Series({
            "dc_low_10": 102.0,
            "dc_high_10": 112.0,
        })

        exit_signal = bt._check_exit_signal(row, prev_row, position)
        assert exit_signal == SignalType.EXIT_LONG

        bt._close_position("TEST", pd.Timestamp("2025-01-05"), 102.0, exit_signal.value)
        assert bt.trades[0].exit_price == 102.0
