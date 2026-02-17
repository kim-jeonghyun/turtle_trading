"""
scripts/run_backtest.py 테스트
"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import argparse
from unittest.mock import Mock, patch
import pandas as pd
from datetime import datetime

# 백테스트 스크립트 임포트
from scripts.run_backtest import (
    parse_args,
    fetch_data,
    run_backtest,
    print_results,
    plot_equity_curve,
    export_trades_csv
)
from src.backtester import BacktestConfig, BacktestResult, Trade


class TestArgumentParsing:
    """인자 파싱 테스트"""

    def test_minimal_args(self):
        """최소 필수 인자"""
        with patch('sys.argv', ['run_backtest.py', '--symbols', 'SPY']):
            args = parse_args()
            assert args.symbols == ['SPY']
            assert args.period == '2y'
            assert args.system == 1
            assert args.capital == 100000.0
            assert args.risk == 0.01
            assert args.commission == 0.001
            assert args.no_filter is False
            assert args.plot is False
            assert args.csv is None
            assert args.verbose is False

    def test_multiple_symbols(self):
        """여러 종목 지정"""
        with patch('sys.argv', ['run_backtest.py', '--symbols', 'SPY', 'QQQ', 'IWM']):
            args = parse_args()
            assert args.symbols == ['SPY', 'QQQ', 'IWM']

    def test_custom_config(self):
        """커스텀 설정"""
        with patch('sys.argv', [
            'run_backtest.py',
            '--symbols', 'AAPL',
            '--period', '5y',
            '--system', '2',
            '--capital', '50000',
            '--risk', '0.02',
            '--commission', '0.0005',
            '--no-filter'
        ]):
            args = parse_args()
            assert args.symbols == ['AAPL']
            assert args.period == '5y'
            assert args.system == 2
            assert args.capital == 50000.0
            assert args.risk == 0.02
            assert args.commission == 0.0005
            assert args.no_filter is True

    def test_output_options(self):
        """출력 옵션"""
        with patch('sys.argv', [
            'run_backtest.py',
            '--symbols', 'SPY',
            '--plot',
            '--csv', 'trades.csv',
            '--verbose'
        ]):
            args = parse_args()
            assert args.plot is True
            assert args.csv == 'trades.csv'
            assert args.verbose is True

    def test_invalid_system(self):
        """잘못된 시스템 번호"""
        with patch('sys.argv', ['run_backtest.py', '--symbols', 'SPY', '--system', '3']):
            with pytest.raises(SystemExit):
                parse_args()


class TestBacktestConfigCreation:
    """BacktestConfig 생성 테스트"""

    def test_config_from_args_system1(self):
        """System 1 설정"""
        with patch('sys.argv', [
            'run_backtest.py',
            '--symbols', 'SPY',
            '--system', '1',
            '--capital', '100000',
            '--risk', '0.01',
            '--commission', '0.001'
        ]):
            args = parse_args()
            config = BacktestConfig(
                initial_capital=args.capital,
                risk_percent=args.risk,
                system=args.system,
                max_units=4,
                pyramid_interval_n=0.5,
                stop_distance_n=2.0,
                use_filter=not args.no_filter,
                commission_pct=args.commission
            )

            assert config.initial_capital == 100000.0
            assert config.risk_percent == 0.01
            assert config.system == 1
            assert config.max_units == 4
            assert config.pyramid_interval_n == 0.5
            assert config.stop_distance_n == 2.0
            assert config.use_filter is True
            assert config.commission_pct == 0.001

    def test_config_from_args_system2_no_filter(self):
        """System 2 필터 비활성화"""
        with patch('sys.argv', [
            'run_backtest.py',
            '--symbols', 'SPY',
            '--system', '2',
            '--no-filter'
        ]):
            args = parse_args()
            config = BacktestConfig(
                initial_capital=args.capital,
                risk_percent=args.risk,
                system=args.system,
                use_filter=not args.no_filter,
                commission_pct=args.commission
            )

            assert config.system == 2
            assert config.use_filter is False


class TestOutputFormatting:
    """출력 포맷 테스트"""

    @pytest.fixture
    def mock_result(self):
        """모의 백테스트 결과"""
        config = BacktestConfig(
            initial_capital=100000.0,
            risk_percent=0.01,
            system=1
        )

        trades = [
            Trade(
                symbol="SPY",
                entry_date=datetime(2024, 1, 1),
                entry_price=450.0,
                exit_date=datetime(2024, 2, 1),
                exit_price=460.0,
                direction="long",
                quantity=100,
                pnl=1000.0,
                pnl_pct=0.022,
                exit_reason="exit_long"
            ),
            Trade(
                symbol="SPY",
                entry_date=datetime(2024, 3, 1),
                entry_price=455.0,
                exit_date=datetime(2024, 4, 1),
                exit_price=450.0,
                direction="long",
                quantity=100,
                pnl=-500.0,
                pnl_pct=-0.011,
                exit_reason="stop_loss"
            )
        ]

        equity_data = {
            "date": pd.date_range("2024-01-01", periods=100, freq="D"),
            "equity": [100000 + i * 100 for i in range(100)],
            "cash": [50000 + i * 50 for i in range(100)]
        }
        equity_df = pd.DataFrame(equity_data)

        result = BacktestResult(
            config=config,
            trades=trades,
            equity_curve=equity_df,
            final_equity=110000.0,
            total_return=0.10,
            cagr=0.12,
            max_drawdown=0.15,
            sharpe_ratio=1.5,
            win_rate=0.5,
            profit_factor=2.0,
            total_trades=2,
            winning_trades=1,
            losing_trades=1,
            avg_win=1000.0,
            avg_loss=500.0
        )

        return result

    def test_print_results(self, mock_result, capsys):
        """결과 출력 테스트"""
        print_results(mock_result)
        captured = capsys.readouterr()

        assert "백테스트 결과 요약" in captured.out
        assert "$100,000.00" in captured.out
        assert "$110,000.00" in captured.out
        assert "10.00%" in captured.out
        assert "12.00%" in captured.out
        assert "15.00%" in captured.out
        assert "1.50" in captured.out
        assert "50.00%" in captured.out
        assert "2.00" in captured.out

    def test_export_trades_csv(self, mock_result, tmp_path):
        """CSV 저장 테스트"""
        csv_path = tmp_path / "test_trades.csv"
        export_trades_csv(mock_result, str(csv_path))

        assert csv_path.exists()

        df = pd.read_csv(csv_path)
        assert len(df) == 2
        assert list(df.columns) == [
            "symbol", "direction", "entry_date", "entry_price",
            "exit_date", "exit_price", "quantity", "pnl", "pnl_pct", "exit_reason"
        ]

        # 첫 거래 확인
        assert df.iloc[0]["symbol"] == "SPY"
        assert df.iloc[0]["direction"] == "long"
        assert df.iloc[0]["pnl"] == 1000.0
        assert df.iloc[0]["pnl_pct"] == pytest.approx(2.2, rel=0.1)

    def test_plot_equity_curve(self, mock_result, tmp_path):
        """차트 생성 테스트"""
        # matplotlib.pyplot.savefig를 모킹하여 실제 파일 저장 방지
        with patch('matplotlib.pyplot.savefig') as mock_savefig:
            plot_equity_curve(mock_result, ["SPY"])
            # savefig가 호출되었는지 확인
            assert mock_savefig.called
            # 첫 번째 인자가 파일 경로인지 확인
            args, kwargs = mock_savefig.call_args
            assert str(args[0]).endswith('.png')


class TestDataFetching:
    """데이터 수집 테스트"""

    @patch('src.data_fetcher.DataFetcher.fetch_multiple')
    def test_fetch_data_success(self, mock_fetch):
        """데이터 수집 성공"""
        mock_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=100, freq="D"),
            "open": [100] * 100,
            "high": [105] * 100,
            "low": [95] * 100,
            "close": [102] * 100,
            "volume": [1000000] * 100
        })
        mock_fetch.return_value = {"SPY": mock_df}

        with patch('logging.Logger.info'):
            data = fetch_data(["SPY"], "1y", verbose=False)

        assert "SPY" in data
        assert len(data["SPY"]) == 100

    @patch('src.data_fetcher.DataFetcher.fetch_multiple')
    def test_fetch_data_empty(self, mock_fetch):
        """데이터 수집 실패"""
        mock_fetch.return_value = {}

        with pytest.raises(SystemExit):
            fetch_data(["INVALID"], "1y", verbose=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
