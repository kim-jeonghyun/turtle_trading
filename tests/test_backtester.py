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
