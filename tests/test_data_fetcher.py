"""
data_fetcher.py 단위 테스트
- 마켓 타입 추론
- 컬럼 정규화
- Mock 데이터 페칭
- 에러 처리
"""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.data_fetcher import DataFetcher, DataSource, MarketType, get_market_type


class TestMarketType:
    def test_us_stock(self):
        assert get_market_type("AAPL") == MarketType.US_STOCK
        assert get_market_type("MSFT") == MarketType.US_STOCK
        assert get_market_type("SPY") == MarketType.US_STOCK

    def test_kr_stock_ks(self):
        assert get_market_type("005930.KS") == MarketType.KR_STOCK

    def test_kr_stock_kq(self):
        assert get_market_type("035420.KQ") == MarketType.KR_STOCK

    def test_kr_stock_numeric(self):
        assert get_market_type("005930") == MarketType.KR_STOCK

    def test_crypto_usdt(self):
        assert get_market_type("BTCUSDT") == MarketType.CRYPTO

    def test_crypto_slash(self):
        assert get_market_type("BTC/USDT") == MarketType.CRYPTO

    def test_commodity(self):
        assert get_market_type("GLD") == MarketType.COMMODITY
        assert get_market_type("SLV") == MarketType.COMMODITY
        assert get_market_type("USO") == MarketType.COMMODITY
        assert get_market_type("UNG") == MarketType.COMMODITY
        assert get_market_type("DBA") == MarketType.COMMODITY
        assert get_market_type("DBC") == MarketType.COMMODITY

    def test_bond(self):
        assert get_market_type("TLT") == MarketType.BOND
        assert get_market_type("IEF") == MarketType.BOND
        assert get_market_type("SHY") == MarketType.BOND
        assert get_market_type("BND") == MarketType.BOND
        assert get_market_type("AGG") == MarketType.BOND
        assert get_market_type("LQD") == MarketType.BOND


class TestDataSourceEnum:
    def test_values(self):
        assert DataSource.YFINANCE.value == "yfinance"
        assert DataSource.FDR.value == "fdr"
        assert DataSource.CCXT.value == "ccxt"
        assert DataSource.KIS.value == "kis"


class TestDataFetcher:
    def test_default_period(self):
        fetcher = DataFetcher()
        assert fetcher.default_period == "2y"

    def test_custom_period(self):
        fetcher = DataFetcher(default_period="1y")
        assert fetcher.default_period == "1y"


class TestFetchYFinance:
    def _mock_yf_data(self):
        """yfinance가 반환할 mock DataFrame"""
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        df = pd.DataFrame({
            "Date": dates,
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "Volume": [1000000, 1100000, 1200000, 1300000, 1400000],
        })
        df = df.set_index("Date")
        return df

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_yfinance_with_period(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch_yfinance("SPY", period="1y")

        assert not df.empty
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
        assert len(df) == 5
        mock_ticker.history.assert_called_once_with(period="1y")

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_yfinance_with_dates(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch_yfinance("SPY", start="2025-01-01", end="2025-01-10")

        assert not df.empty
        mock_ticker.history.assert_called_once_with(start="2025-01-01", end="2025-01-10")

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_yfinance_empty_data(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch_yfinance("INVALID")

        assert df.empty

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_yfinance_exception(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("API Error")
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch_yfinance("SPY", period="1y")

        assert df.empty

    @patch("src.data_fetcher.yf.Ticker")
    def test_column_normalization(self, mock_ticker_cls):
        """컬럼명이 소문자로 정규화되는지 확인"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch_yfinance("SPY", period="1y")

        for col in ["date", "open", "high", "low", "close", "volume"]:
            assert col in df.columns


class TestFetchIntegrated:
    def _mock_yf_data(self):
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        df = pd.DataFrame({
            "Date": dates,
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "Volume": [1000000, 1100000, 1200000, 1300000, 1400000],
        })
        df = df.set_index("Date")
        return df

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_us_stock(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch("SPY", period="1y")

        assert not df.empty

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_with_explicit_source(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch("SPY", period="1y", source=DataSource.YFINANCE)

        assert not df.empty

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_multiple(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        results = fetcher.fetch_multiple(["SPY", "QQQ"], period="1y")

        assert "SPY" in results
        assert "QQQ" in results

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_multiple_skips_empty(self, mock_ticker_cls):
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return self._mock_yf_data()
            return pd.DataFrame()

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = side_effect
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        results = fetcher.fetch_multiple(["SPY", "INVALID"], period="1y")

        assert "SPY" in results
        assert "INVALID" not in results

    @patch("src.data_fetcher.yf.Ticker")
    def test_get_latest_price(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        price = fetcher.get_latest_price("SPY")

        assert price is not None
        assert isinstance(price, float)
        assert price == 104.5  # Last close

    @patch("src.data_fetcher.yf.Ticker")
    def test_get_latest_price_empty(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        price = fetcher.get_latest_price("INVALID")

        assert price is None

    @patch("src.data_fetcher.yf.Ticker")
    def test_get_latest_prices(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        prices = fetcher.get_latest_prices(["SPY", "QQQ"])

        assert "SPY" in prices
        assert "QQQ" in prices


class TestFetchCrypto:
    @patch("src.data_fetcher.yf.Ticker")
    def test_crypto_fallback_to_yfinance(self, mock_ticker_cls):
        """ccxt가 없을 때 yfinance로 fallback"""
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        df = pd.DataFrame({
            "Date": dates,
            "Open": [50000.0] * 5,
            "High": [51000.0] * 5,
            "Low": [49000.0] * 5,
            "Close": [50500.0] * 5,
            "Volume": [1000] * 5,
        })
        df = df.set_index("Date")

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        # Force _get_ccxt_exchange to return None (simulate ccxt not available)
        with patch.object(fetcher, '_get_ccxt_exchange', return_value=None):
            result = fetcher.fetch_crypto("BTC/USDT")

        # Should fall back to yfinance with BTC-USD
        assert mock_ticker_cls.called


class TestFetchFDR:
    @patch("src.data_fetcher.yf.Ticker")
    def test_fdr_import_error_fallback(self, mock_ticker_cls):
        """FinanceDataReader가 없을 때 yfinance로 fallback"""
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        df = pd.DataFrame({
            "Date": dates,
            "Open": [80000.0] * 5,
            "High": [81000.0] * 5,
            "Low": [79000.0] * 5,
            "Close": [80500.0] * 5,
            "Volume": [500000] * 5,
        })
        df = df.set_index("Date")

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        # This should attempt FDR first, fail on import, then fall back to yfinance
        result = fetcher.fetch_fdr("005930.KS", start="2025-01-01", end="2025-06-01")

        # Either we get data from fallback or empty (depending on environment)
        # The key point: no exception raised
        assert isinstance(result, pd.DataFrame)


class TestFetchRouting:
    """fetch() 메서드의 마켓 타입에 따른 라우팅 테스트"""

    def _mock_yf_data(self):
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        df = pd.DataFrame({
            "Date": dates,
            "Open": [100.0] * 5,
            "High": [101.0] * 5,
            "Low": [99.0] * 5,
            "Close": [100.5] * 5,
            "Volume": [1000000] * 5,
        })
        df = df.set_index("Date")
        return df

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_commodity(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch("GLD", period="1y")
        assert not df.empty

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_bond(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch("TLT", period="1y")
        assert not df.empty

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_with_fdr_source(self, mock_ticker_cls):
        """FDR source 지정시 fetch_fdr 호출"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch("005930.KS", source=DataSource.FDR, start="2025-01-01", end="2025-06-01")
        assert isinstance(df, pd.DataFrame)

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_with_ccxt_source(self, mock_ticker_cls):
        """CCXT source 지정시 fetch_crypto 호출"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        with patch.object(fetcher, '_get_ccxt_exchange', return_value=None):
            df = fetcher.fetch("BTC/USDT", source=DataSource.CCXT)
        assert isinstance(df, pd.DataFrame)

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_kr_stock_auto(self, mock_ticker_cls):
        """한국 주식은 자동으로 FDR -> yfinance fallback"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        df = fetcher.fetch("005930.KS", period="1y")
        assert isinstance(df, pd.DataFrame)

    @patch("src.data_fetcher.yf.Ticker")
    def test_fetch_crypto_auto(self, mock_ticker_cls):
        """암호화폐는 자동으로 CCXT -> yfinance fallback"""
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = self._mock_yf_data()
        mock_ticker_cls.return_value = mock_ticker

        fetcher = DataFetcher()
        with patch.object(fetcher, '_get_ccxt_exchange', return_value=None):
            df = fetcher.fetch("BTC/USDT")
        assert isinstance(df, pd.DataFrame)
