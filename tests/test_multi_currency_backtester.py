import pandas as pd

from src.backtester import BacktestConfig
from src.commission import KRXCommissionModel, USCommissionModel
from src.multi_currency_backtester import MultiCurrencyBacktester


def _make_ohlcv(prices: list, start_date: str = "2024-01-01") -> pd.DataFrame:
    dates = pd.date_range(start_date, periods=len(prices), freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": prices,
            "high": [p * 1.02 for p in prices],
            "low": [p * 0.98 for p in prices],
            "close": prices,
            "volume": [1000000] * len(prices),
        }
    )


class TestMultiCurrencyBacktester:
    def test_separates_data_by_currency(self):
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
            krw_config=BacktestConfig(initial_capital=100_000_000.0),
        )
        data = {
            "SPY": _make_ohlcv([400 + i for i in range(60)]),
            "005930.KS": _make_ohlcv([70000 + i * 100 for i in range(60)]),
        }
        currency_map = {"SPY": "USD", "005930.KS": "KRW"}
        usd_data, krw_data = mcbt._split_by_currency(data, currency_map)
        assert "SPY" in usd_data
        assert "005930.KS" in krw_data
        assert "SPY" not in krw_data
        assert "005930.KS" not in usd_data

    def test_independent_equity(self):
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
            krw_config=BacktestConfig(initial_capital=100_000_000.0),
        )
        assert mcbt.usd_backtester is not None
        assert mcbt.krw_backtester is not None
        assert mcbt.usd_backtester.account.currency == "USD"
        assert mcbt.krw_backtester.account.currency == "KRW"

    def test_usd_only(self):
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
        )
        assert mcbt.usd_backtester is not None
        assert mcbt.krw_backtester is None

    def test_result_contains_only_active_currencies(self):
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
        )
        result = mcbt.run({}, {})
        assert "KRW" not in result.results

    def test_usd_uses_us_commission(self):
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
            krw_config=BacktestConfig(initial_capital=100_000_000.0),
        )
        assert isinstance(mcbt.usd_backtester.commission_model, USCommissionModel)
        assert isinstance(mcbt.krw_backtester.commission_model, KRXCommissionModel)
