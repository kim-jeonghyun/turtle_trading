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
from src.types import AssetGroup, Direction


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

    def test_equity_includes_position_market_value(self, trending_up_df):
        """equity curve에 포지션 시가(market value)가 반영되는지 검증 (B1 수정 후)"""
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
                assert has_difference, "Equity should include position market value"


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
        data = pd.DataFrame(
            {
                "date": dates,
                "open": [100] * 60,
                "high": [101] * 20 + [120] * 20 + [101] * 20,
                "low": [99] * 20 + [99] * 20 + [80] * 20,
                "close": [100] * 20 + [115] * 20 + [85] * 20,
                "volume": [1000000] * 60,
            }
        )

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
            df = pd.DataFrame(
                {
                    "date": dates,
                    "open": prices,
                    "high": [p + 0.5 for p in prices],
                    "low": [p - 0.5 for p in prices],
                    "close": prices,
                    "volume": [1000000] * len(dates),
                }
            )
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
        symbols_traded = set(t.symbol for t in bt.trades) | set(bt.pyramid_manager.positions.keys())
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

        symbols_traded = set(t.symbol for t in bt.trades) | set(bt.pyramid_manager.positions.keys())
        assert len(symbols_traded) == 7, f"리스크 한도 없이 7종목 모두 진입 기대, 실제: {len(symbols_traded)}"


class TestEquityInvariants:
    """에쿼티 추적 불변 조건 (Issue #216)"""

    @staticmethod
    def _make_volatile_data() -> dict[str, pd.DataFrame]:
        """큰 변동이 있는 단일 종목 데이터 (진입→하락→청산 유도)"""
        np.random.seed(42)
        dates = pd.date_range(start="2024-01-01", periods=120, freq="B")
        prices = []
        p = 100.0
        for i in range(120):
            if i < 30:
                p += np.random.normal(0, 0.3)
            elif i < 60:
                p += abs(np.random.normal(1.0, 0.3))
            elif i < 90:
                p -= abs(np.random.normal(1.5, 0.5))
            else:
                p += np.random.normal(0, 0.3)
            p = max(p, 1.0)
            prices.append(p)

        df = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": [p + abs(np.random.normal(0.5, 0.2)) for p in prices],
                "low": [p - abs(np.random.normal(0.5, 0.2)) for p in prices],
                "close": prices,
                "volume": [1_000_000] * 120,
            }
        )
        return {"TEST": df}

    @staticmethod
    def _make_multi_symbol_data() -> dict[str, pd.DataFrame]:
        """3종목 데이터"""
        np.random.seed(99)
        dates = pd.date_range(start="2024-01-01", periods=120, freq="B")
        data = {}
        for sym_idx, sym in enumerate(["AAA", "BBB", "CCC"]):
            base = 50.0 + sym_idx * 20
            prices = []
            p = base
            for i in range(120):
                if i < 30:
                    p += np.random.normal(0, 0.2)
                elif i < 60:
                    p += abs(np.random.normal(0.8, 0.2))
                elif i < 90:
                    p -= abs(np.random.normal(1.2, 0.4))
                else:
                    p += np.random.normal(0, 0.2)
                p = max(p, 1.0)
                prices.append(p)
            df = pd.DataFrame(
                {
                    "date": dates,
                    "open": prices,
                    "high": [p + abs(np.random.normal(0.4, 0.1)) for p in prices],
                    "low": [p - abs(np.random.normal(0.4, 0.1)) for p in prices],
                    "close": prices,
                    "volume": [1_000_000] * 120,
                }
            )
            data[sym] = df
        return data

    def test_i1_equity_non_negative(self):
        """I1: Long-only 무레버리지에서 equity는 항상 >= 0"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        assert not result.equity_curve.empty, "equity curve가 비어있음"
        neg = result.equity_curve[result.equity_curve["equity"] < 0]
        assert neg.empty, (
            f"I1 위반: {len(neg)}개 시점에서 음수 equity 발생. 최솟값: {result.equity_curve['equity'].min():.2f}"
        )

    def test_i2_mdd_bounded(self):
        """I2: 0 <= MDD <= 1.0"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        assert 0 <= result.max_drawdown <= 1.0, f"I2 위반: MDD = {result.max_drawdown:.4f} (범위 초과)"

    def test_i3_cash_reconciliation_when_flat(self):
        """I3: 모든 포지션 청산 후 equity == cash == initial + realized_pnl"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)
        bt.run(self._make_volatile_data())

        assert len(bt.trades) > 0, "I3 전제조건 불충족: 거래가 발생하지 않음"
        assert len(bt.pyramid_manager.positions) == 0, (
            "I3 전제조건 불충족: 열린 포지션 존재 — 모든 포지션이 청산되어야 함"
        )

        expected = config.initial_capital + bt.account.realized_pnl
        actual_cash = bt.account.cash
        assert abs(actual_cash - expected) < 0.01, (
            f"I3 위반: cash={actual_cash:.2f}, expected={expected:.2f} (initial + realized_pnl)"
        )

    def test_i4_current_equity_consistent(self):
        """I4: account.current_equity == equity_curve 마지막 값"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        assert not result.equity_curve.empty, "equity curve가 비어있음"
        curve_last = result.equity_curve["equity"].iloc[-1]
        assert abs(bt.account.current_equity - curve_last) < 0.01, (
            f"I4 위반: current_equity={bt.account.current_equity:.2f}, curve_last={curve_last:.2f}"
        )

    def test_i5_peak_monotonic(self):
        """I5: equity peak는 단조증가"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        assert not result.equity_curve.empty, "equity curve가 비어있음"
        assert "peak" in result.equity_curve.columns, "peak 컬럼이 없음"
        peaks = result.equity_curve["peak"]
        diffs = peaks.diff().dropna()
        violations = diffs[diffs < -0.001]
        assert violations.empty, f"I5 위반: peak가 {len(violations)}개 시점에서 감소"

    def test_multi_symbol_equity_non_negative(self):
        """I1 확장: 다중 종목에서도 equity >= 0"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_multi_symbol_data())

        assert not result.equity_curve.empty
        neg = result.equity_curve[result.equity_curve["equity"] < 0]
        assert neg.empty, (
            f"I1 위반 (다중 종목): {len(neg)}개 시점에서 음수. 최솟값: {result.equity_curve['equity'].min():.2f}"
        )

    def test_multi_symbol_mdd_bounded(self):
        """I2 확장: 다중 종목에서도 MDD <= 1.0"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_multi_symbol_data())

        assert 0 <= result.max_drawdown <= 1.0, f"I2 위반 (다중 종목): MDD = {result.max_drawdown:.4f}"


class TestEquityFormula:
    """B1 수정 검증: _record_equity()가 market value를 사용하는지 확인"""

    def test_equity_at_entry_equals_initial_minus_commission(self):
        """진입 직후 equity = initial_capital - commission (not initial - notional)"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
            commission_pct=0.001,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)

        position = bt.pyramid_manager.get_position("TEST")
        assert position is not None, "포지션이 생성되지 않음"
        qty = position.total_units

        mock_data = {
            "TEST": pd.DataFrame(
                {
                    "date": [pd.Timestamp("2025-01-01")],
                    "close": [100.0],
                }
            )
        }
        bt._record_equity(pd.Timestamp("2025-01-01"), mock_data)

        recorded_equity = bt.equity_history[-1]["equity"]
        expected = 100_000.0 - qty * 100.0 * config.commission_pct
        assert abs(recorded_equity - expected) < 1.0, (
            f"진입 직후 equity={recorded_equity:.2f}, expected={expected:.2f}. "
            f"차이={recorded_equity - expected:.2f} (B1 버그 시 ~{qty * 100:.0f} 부족)"
        )

    def test_equity_tracks_price_movement(self):
        """가격 상승 시 equity가 정확히 반영"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        position = bt.pyramid_manager.get_position("TEST")
        qty = position.total_units

        mock_data = {
            "TEST": pd.DataFrame(
                {
                    "date": [pd.Timestamp("2025-01-02")],
                    "close": [110.0],
                }
            )
        }
        bt._record_equity(pd.Timestamp("2025-01-02"), mock_data)

        recorded = bt.equity_history[-1]["equity"]
        expected = 100_000.0 + qty * 10.0
        assert abs(recorded - expected) < 0.01, f"equity={recorded:.2f}, expected={expected:.2f}"


class TestRoundTripCommission:
    """B1+B3 통합 검증: 진입→청산 왕복 수수료가 정확히 차감되는지 확인"""

    def test_round_trip_cash_equals_initial_minus_commissions(self):
        """가격 변동 없이 왕복 시 cash = initial - entry_commission - exit_commission"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.001,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        position = bt.pyramid_manager.get_position("TEST")
        qty = position.total_units

        bt._close_position("TEST", pd.Timestamp("2025-01-10"), 100.0, "EXIT_LONG")

        entry_comm = qty * 100.0 * config.commission_pct
        exit_comm = qty * 100.0 * config.commission_pct
        expected = 100_000.0 - entry_comm - exit_comm
        assert abs(bt.account.cash - expected) < 0.01, (
            f"왕복 수수료 불일치: cash={bt.account.cash:.2f}, expected={expected:.2f}"
        )

    def test_short_round_trip_equity(self):
        """SHORT 왕복: equity가 정확하게 추적되는지 검증"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.SHORT)
        position = bt.pyramid_manager.get_position("TEST")
        assert position is not None, "SHORT 포지션 미생성"
        qty = position.total_units

        # 가격 하락 → 숏 수익
        mock_data = {
            "TEST": pd.DataFrame(
                {
                    "date": [pd.Timestamp("2025-01-02")],
                    "close": [90.0],
                }
            )
        }
        bt._record_equity(pd.Timestamp("2025-01-02"), mock_data)

        recorded = bt.equity_history[-1]["equity"]
        # cash = 100000 - qty*100, positions_value = qty*(2*100 - 90) = qty*110
        # equity = (100000 - qty*100) + qty*110 = 100000 + qty*10
        expected = 100_000.0 + qty * 10.0
        assert abs(recorded - expected) < 0.01, f"SHORT equity 오류: {recorded:.2f}, expected={expected:.2f}"

        # 가격 상승 → 숏 손실
        mock_data2 = {
            "TEST": pd.DataFrame(
                {
                    "date": [pd.Timestamp("2025-01-03")],
                    "close": [110.0],
                }
            )
        }
        bt._record_equity(pd.Timestamp("2025-01-03"), mock_data2)

        recorded2 = bt.equity_history[-1]["equity"]
        # positions_value = qty*(2*100 - 110) = qty*90
        expected2 = 100_000.0 - qty * 10.0
        assert abs(recorded2 - expected2) < 0.01, f"SHORT equity 오류 (상승): {recorded2:.2f}, expected={expected2:.2f}"


class TestExitCommission:
    """B3 수정 검증: 청산 시 수수료가 cash에서 차감되는지 확인"""

    def test_exit_commission_deducted_from_cash(self):
        """청산 시 cash += qty * price * (1 - commission)"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.001,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        position = bt.pyramid_manager.get_position("TEST")
        qty = position.total_units
        cash_before_close = bt.account.cash

        bt._close_position("TEST", pd.Timestamp("2025-01-10"), 110.0, "EXIT_LONG")

        expected_cash = cash_before_close + qty * 110.0 * (1 - config.commission_pct)
        assert abs(bt.account.cash - expected_cash) < 0.01, (
            f"cash={bt.account.cash:.2f}, expected={expected_cash:.2f}. "
            f"차이={bt.account.cash - expected_cash:.2f} (B3: 청산 수수료 미차감)"
        )

    def test_short_exit_commission_deducted_from_cash(self):
        """SHORT 청산 시 수수료가 cash에서 정확히 차감"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.001,
        )
        bt = TurtleBacktester(config)

        entry_price = 100.0
        exit_price = 90.0
        bt._open_position("TEST", pd.Timestamp("2025-01-01"), entry_price, 5.0, Direction.SHORT)
        position = bt.pyramid_manager.get_position("TEST")
        qty = position.total_units
        cash_before_close = bt.account.cash

        bt._close_position("TEST", pd.Timestamp("2025-01-10"), exit_price, "EXIT_SHORT")

        # SHORT close: cash += (2*entry - exit)*qty - exit*qty*commission
        collateral_return = (2 * entry_price - exit_price) * qty
        exit_comm = exit_price * qty * config.commission_pct
        expected_cash = cash_before_close + collateral_return - exit_comm
        assert abs(bt.account.cash - expected_cash) < 0.01, (
            f"SHORT 청산 수수료 불일치: cash={bt.account.cash:.2f}, expected={expected_cash:.2f}"
        )


class TestCurrentEquityUpdate:
    """B2 수정 검증: current_equity가 매 바마다 갱신되는지 확인"""

    def test_current_equity_updated_after_record(self):
        """_record_equity() 호출 후 account.current_equity가 갱신"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        qty = bt.pyramid_manager.get_position("TEST").total_units

        mock_data = {
            "TEST": pd.DataFrame(
                {
                    "date": [pd.Timestamp("2025-01-02")],
                    "close": [90.0],
                }
            )
        }
        bt._record_equity(pd.Timestamp("2025-01-02"), mock_data)

        expected = bt.account.cash + qty * 90.0
        assert abs(bt.account.current_equity - expected) < 0.01, (
            f"current_equity={bt.account.current_equity:.2f}, expected={expected:.2f}. "
            f"B2 버그: initial_capital에서 변경 안 됨"
        )

    def test_position_sizing_uses_updated_equity(self):
        """손실 후 두 번째 포지션이 줄어든 equity로 사이징"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)

        bt._open_position("AAA", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        qty1 = bt.pyramid_manager.get_position("AAA").total_units

        mock_data = {
            "AAA": pd.DataFrame(
                {
                    "date": [pd.Timestamp("2025-01-02")],
                    "close": [80.0],
                }
            )
        }
        bt._record_equity(pd.Timestamp("2025-01-02"), mock_data)

        bt._open_position("BBB", pd.Timestamp("2025-01-02"), 50.0, 5.0, Direction.LONG)
        pos_bbb = bt.pyramid_manager.get_position("BBB")

        assert pos_bbb is not None, "BBB 포지션이 생성되지 않음 (cash 부족 가능)"
        qty2 = pos_bbb.total_units
        assert qty2 <= qty1, f"B2 버그: 손실 후에도 동일 사이즈 {qty2} >= {qty1}"
