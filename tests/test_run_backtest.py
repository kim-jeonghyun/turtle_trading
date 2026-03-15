"""
scripts/run_backtest.py 테스트
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# 백테스트 스크립트 임포트
from scripts.run_backtest import (
    export_trades_csv,
    fetch_data,
    parse_args,
    plot_equity_curve,
    print_results,
    run_backtest,
)
from src.backtester import BacktestConfig, BacktestResult, Trade


class TestArgumentParsing:
    """인자 파싱 테스트"""

    def test_minimal_args(self):
        """최소 필수 인자"""
        with patch("sys.argv", ["run_backtest.py", "--symbols", "SPY"]):
            args = parse_args()
            assert args.symbols == ["SPY"]
            assert args.period == "2y"
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
        with patch("sys.argv", ["run_backtest.py", "--symbols", "SPY", "QQQ", "IWM"]):
            args = parse_args()
            assert args.symbols == ["SPY", "QQQ", "IWM"]

    def test_custom_config(self):
        """커스텀 설정"""
        with patch(
            "sys.argv",
            [
                "run_backtest.py",
                "--symbols",
                "AAPL",
                "--period",
                "5y",
                "--system",
                "2",
                "--capital",
                "50000",
                "--risk",
                "0.02",
                "--commission",
                "0.0005",
                "--no-filter",
            ],
        ):
            args = parse_args()
            assert args.symbols == ["AAPL"]
            assert args.period == "5y"
            assert args.system == 2
            assert args.capital == 50000.0
            assert args.risk == 0.02
            assert args.commission == 0.0005
            assert args.no_filter is True

    def test_output_options(self):
        """출력 옵션"""
        with patch("sys.argv", ["run_backtest.py", "--symbols", "SPY", "--plot", "--csv", "trades.csv", "--verbose"]):
            args = parse_args()
            assert args.plot is True
            assert args.csv == "trades.csv"
            assert args.verbose is True

    def test_no_risk_limits_flag(self):
        """--no-risk-limits 플래그 파싱"""
        with patch("sys.argv", ["run_backtest.py", "--symbols", "SPY", "--no-risk-limits"]):
            args = parse_args()
            assert args.no_risk_limits is True

    def test_no_risk_limits_default_false(self):
        """--no-risk-limits 기본값 False"""
        with patch("sys.argv", ["run_backtest.py", "--symbols", "SPY"]):
            args = parse_args()
            assert args.no_risk_limits is False

    def test_invalid_system(self):
        """잘못된 시스템 번호"""
        with patch("sys.argv", ["run_backtest.py", "--symbols", "SPY", "--system", "3"]):
            with pytest.raises(SystemExit):
                parse_args()


class TestBacktestConfigCreation:
    """BacktestConfig 생성 테스트"""

    def test_config_from_args_system1(self):
        """System 1 설정"""
        with patch(
            "sys.argv",
            [
                "run_backtest.py",
                "--symbols",
                "SPY",
                "--system",
                "1",
                "--capital",
                "100000",
                "--risk",
                "0.01",
                "--commission",
                "0.001",
            ],
        ):
            args = parse_args()
            config = BacktestConfig(
                initial_capital=args.capital,
                risk_percent=args.risk,
                system=args.system,
                max_units=4,
                pyramid_interval_n=0.5,
                stop_distance_n=2.0,
                use_filter=not args.no_filter,
                commission_pct=args.commission,
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
        with patch("sys.argv", ["run_backtest.py", "--symbols", "SPY", "--system", "2", "--no-filter"]):
            args = parse_args()
            config = BacktestConfig(
                initial_capital=args.capital,
                risk_percent=args.risk,
                system=args.system,
                use_filter=not args.no_filter,
                commission_pct=args.commission,
            )

            assert config.system == 2
            assert config.use_filter is False


class TestOutputFormatting:
    """출력 포맷 테스트"""

    @pytest.fixture
    def mock_result(self):
        """모의 백테스트 결과"""
        config = BacktestConfig(initial_capital=100000.0, risk_percent=0.01, system=1)

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
                entry_reason="System 1 롱 진입: 450.00 돌파",
                exit_reason="exit_long",
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
                entry_reason="System 1 롱 진입: 455.00 돌파",
                exit_reason="stop_loss",
            ),
        ]

        equity_data = {
            "date": pd.date_range("2024-01-01", periods=100, freq="D"),
            "equity": [100000 + i * 100 for i in range(100)],
            "cash": [50000 + i * 50 for i in range(100)],
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
            avg_loss=500.0,
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
            "symbol",
            "direction",
            "entry_date",
            "entry_price",
            "exit_date",
            "exit_price",
            "quantity",
            "pnl",
            "pnl_pct",
            "entry_reason",
            "er_at_entry",
            "exit_reason",
        ]

        # 첫 거래 확인
        assert df.iloc[0]["symbol"] == "SPY"
        assert df.iloc[0]["direction"] == "long"
        assert df.iloc[0]["pnl"] == 1000.0
        assert df.iloc[0]["entry_reason"] == "System 1 롱 진입: 450.00 돌파"
        assert df.iloc[0]["pnl_pct"] == pytest.approx(2.2, rel=0.1)

        # 두 번째 거래 entry_reason 확인
        assert df.iloc[1]["entry_reason"] == "System 1 롱 진입: 455.00 돌파"

    def test_plot_equity_curve(self, mock_result, tmp_path):
        """차트 생성 테스트"""
        # matplotlib.pyplot.savefig를 모킹하여 실제 파일 저장 방지
        with patch("matplotlib.pyplot.savefig") as mock_savefig:
            plot_equity_curve(mock_result, ["SPY"])
            # savefig가 호출되었는지 확인
            assert mock_savefig.called
            # 첫 번째 인자가 파일 경로인지 확인
            args, kwargs = mock_savefig.call_args
            assert str(args[0]).endswith(".png")


class TestDataFetching:
    """데이터 수집 테스트"""

    @patch("src.data_fetcher.DataFetcher.fetch_multiple")
    def test_fetch_data_success(self, mock_fetch):
        """데이터 수집 성공"""
        mock_df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=100, freq="D"),
                "open": [100] * 100,
                "high": [105] * 100,
                "low": [95] * 100,
                "close": [102] * 100,
                "volume": [1000000] * 100,
            }
        )
        mock_fetch.return_value = {"SPY": mock_df}

        with patch("logging.Logger.info"):
            data = fetch_data(["SPY"], "1y", verbose=False)

        assert "SPY" in data
        assert len(data["SPY"]) == 100

    @patch("src.data_fetcher.DataFetcher.fetch_multiple")
    def test_fetch_data_empty(self, mock_fetch):
        """데이터 수집 실패"""
        mock_fetch.return_value = {}

        with pytest.raises(SystemExit):
            fetch_data(["INVALID"], "1y", verbose=False)


class TestCLIRiskWiring:
    """CLI에서 symbol_groups가 TurtleBacktester에 올바르게 전달되는지 테스트"""

    @pytest.fixture
    def mock_data(self):
        """모의 OHLCV 데이터"""
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        df = pd.DataFrame(
            {
                "date": dates,
                "open": [100.0] * 100,
                "high": [105.0] * 100,
                "low": [95.0] * 100,
                "close": [102.0] * 100,
                "volume": [1000000] * 100,
            }
        )
        return {"SPY": df, "QQQ": df.copy()}

    @patch("scripts.run_backtest.TurtleBacktester")
    @patch("scripts.run_backtest.UniverseManager")
    def test_run_backtest_passes_symbol_groups(self, mock_um_cls, mock_bt_cls, mock_data):
        """--no-risk-limits 미설정 시 symbol_groups가 TurtleBacktester에 전달됨"""
        from src.types import AssetGroup

        mock_um = MagicMock()
        mock_um.get_group_mapping.return_value = {
            "SPY": AssetGroup.US_EQUITY,
            "QQQ": AssetGroup.US_EQUITY,
        }
        mock_um_cls.return_value = mock_um

        mock_bt = MagicMock()
        mock_bt.run.return_value = BacktestResult(config=BacktestConfig())
        mock_bt_cls.return_value = mock_bt

        args = MagicMock()
        args.capital = 100000.0
        args.risk = 0.01
        args.system = 1
        args.no_filter = False
        args.commission = 0.001
        args.no_risk_limits = False

        run_backtest(mock_data, args)

        # UniverseManager가 호출되었는지 확인
        mock_um_cls.assert_called_once()
        # TurtleBacktester에 symbol_groups가 전달되었는지 확인
        _, kwargs = mock_bt_cls.call_args
        assert kwargs["symbol_groups"] is not None
        assert "SPY" in kwargs["symbol_groups"]
        assert "QQQ" in kwargs["symbol_groups"]

    @patch("scripts.run_backtest.TurtleBacktester")
    @patch("scripts.run_backtest.UniverseManager")
    def test_run_backtest_no_risk_limits_skips_universe(
        self, mock_um_cls, mock_bt_cls, mock_data
    ):
        """--no-risk-limits 설정 시 symbol_groups=None이지만 short_restricted_symbols는 로드됨"""
        from src.types import AssetGroup

        mock_um = MagicMock()
        mock_um.get_short_restricted_symbols.return_value = {"005930", "000660"}
        mock_um.get_group_mapping.return_value = {"SPY": AssetGroup.US_EQUITY}
        mock_um_cls.return_value = mock_um

        mock_bt = MagicMock()
        mock_bt.run.return_value = BacktestResult(config=BacktestConfig())
        mock_bt_cls.return_value = mock_bt

        args = MagicMock()
        args.capital = 100000.0
        args.risk = 0.01
        args.system = 1
        args.no_filter = False
        args.commission = 0.001
        args.no_risk_limits = True
        args.trend_filter = False
        args.er_threshold = 0.0
        args.regime_proxy = None

        run_backtest(mock_data, args)

        # symbol_groups는 여전히 None (리스크 한도 비활성)
        _, kwargs = mock_bt_cls.call_args
        assert kwargs["symbol_groups"] is None
        # short_restricted_symbols는 비어 있지 않음 (항상 로드)
        assert kwargs["short_restricted_symbols"] == {"005930", "000660"}

    @patch("scripts.run_backtest.TurtleBacktester")
    @patch("scripts.run_backtest.UniverseManager")
    def test_no_risk_limits_still_loads_short_restricted(
        self, mock_um_cls, mock_bt_cls, mock_data
    ):
        """회귀 테스트: --no-risk-limits 여도 short_restricted_symbols는 항상 UniverseManager에서 로드됨"""
        from src.types import AssetGroup

        mock_um = MagicMock()
        mock_um.get_short_restricted_symbols.return_value = {"005930", "000660"}
        mock_um.get_group_mapping.return_value = {"SPY": AssetGroup.US_EQUITY}
        mock_um_cls.return_value = mock_um

        mock_bt = MagicMock()
        mock_bt.run.return_value = BacktestResult(config=BacktestConfig())
        mock_bt_cls.return_value = mock_bt

        args = MagicMock()
        args.capital = 100000.0
        args.risk = 0.01
        args.system = 1
        args.no_filter = False
        args.commission = 0.001
        args.no_risk_limits = True
        args.trend_filter = False
        args.er_threshold = 0.0
        args.regime_proxy = None

        run_backtest(mock_data, args)

        _, kwargs = mock_bt_cls.call_args
        # 리스크 한도 비활성화 시 symbol_groups는 None
        assert kwargs["symbol_groups"] is None
        # short_restricted_symbols는 --no-risk-limits와 무관하게 항상 로드됨
        assert kwargs["short_restricted_symbols"] == {"005930", "000660"}


class TestPathResolution:
    """경로 해석 회귀 테스트"""

    @patch("scripts.run_backtest.TurtleBacktester")
    def test_universe_yaml_resolves_from_any_cwd(self, mock_bt_cls, tmp_path):
        """CWD가 프로젝트 루트가 아니어도 config/universe.yaml이 올바르게 로드되는지 검증"""
        import os

        mock_bt = MagicMock()
        mock_bt.run.return_value = BacktestResult(config=BacktestConfig())
        mock_bt_cls.return_value = mock_bt

        mock_data = {
            "SPY": pd.DataFrame(
                {
                    "date": pd.date_range("2024-01-01", periods=10, freq="B"),
                    "open": [100.0] * 10,
                    "high": [105.0] * 10,
                    "low": [95.0] * 10,
                    "close": [102.0] * 10,
                    "volume": [1000000] * 10,
                }
            )
        }

        args = MagicMock()
        args.capital = 100000.0
        args.risk = 0.01
        args.system = 1
        args.no_filter = False
        args.commission = 0.001
        args.no_risk_limits = False

        # CWD를 임시 디렉터리로 변경하여 상대경로가 깨지는 상황 재현
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            # 상대경로였다면 여기서 FileNotFoundError 또는 기본 8종목 fallback 발생
            run_backtest(mock_data, args)
        finally:
            os.chdir(original_cwd)

        # UniverseManager가 호출되었고 TurtleBacktester에 symbol_groups가 전달됨
        _, kwargs = mock_bt_cls.call_args
        # symbol_groups가 None이 아니면 universe.yaml이 정상 로드된 것
        assert kwargs["symbol_groups"] is not None


class TestMultiCurrencyArgs:
    """다통화 모드 인자 테스트"""

    def test_multi_currency_flag_requires_no_symbols(self, monkeypatch):
        """--multi-currency는 --symbols 없이도 동작"""
        monkeypatch.setattr("sys.argv", ["run_backtest.py", "--multi-currency"])
        args = parse_args()
        assert args.multi_currency is True
        assert args.symbols is None

    def test_multi_currency_with_symbols(self, monkeypatch):
        """--multi-currency + --symbols 조합"""
        monkeypatch.setattr("sys.argv", ["run_backtest.py", "--multi-currency", "--symbols", "SPY", "005930.KS"])
        args = parse_args()
        assert args.multi_currency is True
        assert args.symbols == ["SPY", "005930.KS"]

    def test_multi_currency_capital_defaults(self, monkeypatch):
        """다통화 자본 기본값"""
        monkeypatch.setattr("sys.argv", ["run_backtest.py", "--multi-currency"])
        args = parse_args()
        assert args.krw_capital == 100_000_000.0
        assert args.usd_capital == 100_000.0

    def test_multi_currency_custom_capital(self, monkeypatch):
        """다통화 자본 커스텀"""
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_backtest.py",
                "--multi-currency",
                "--krw-capital",
                "50000000",
                "--usd-capital",
                "200000",
            ],
        )
        args = parse_args()
        assert args.krw_capital == 50_000_000.0
        assert args.usd_capital == 200_000.0

    def test_no_symbols_no_multi_currency_exits(self, monkeypatch):
        """--symbols도 --multi-currency도 없으면 종료"""
        monkeypatch.setattr("sys.argv", ["run_backtest.py"])
        from scripts.run_backtest import main

        with pytest.raises(SystemExit):
            main()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
