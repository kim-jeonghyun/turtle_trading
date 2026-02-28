"""
SpotPriceFetcher 단위 테스트
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.spot_price import SpotPriceFetcher


class TestKRSpotPrice:
    """KR 종목 KIS API 조회 테스트"""

    async def test_kr_spot_price_success(self):
        """KR KIS mock -> 정상 반환"""
        kis = AsyncMock()
        kis.get_korea_price.return_value = {
            "symbol": "005930",
            "price": 70000.0,
            "high": 71000.0,
            "low": 69000.0,
            "open": 69500.0,
            "volume": 1000000,
        }
        fetcher = SpotPriceFetcher(kis_client=kis)
        result = await fetcher.fetch_spot_price("005930.KS")
        assert result is not None
        assert result["price"] == 70000.0
        assert result["is_delayed"] is False
        kis.get_korea_price.assert_called_once_with("005930")

    async def test_kr_ks_symbol_conversion(self):
        """'005930.KS' -> '005930' 변환 확인"""
        kis = AsyncMock()
        kis.get_korea_price.return_value = {"price": 70000.0, "high": 71000.0, "low": 69000.0, "volume": 100}
        fetcher = SpotPriceFetcher(kis_client=kis)
        await fetcher.fetch_spot_price("005930.KS")
        kis.get_korea_price.assert_called_once_with("005930")

    async def test_kr_kq_symbol_conversion(self):
        """'035420.KQ' -> '035420' 변환 확인"""
        kis = AsyncMock()
        kis.get_korea_price.return_value = {"price": 300000.0, "high": 310000.0, "low": 290000.0, "volume": 50}
        fetcher = SpotPriceFetcher(kis_client=kis)
        await fetcher.fetch_spot_price("035420.KQ")
        kis.get_korea_price.assert_called_once_with("035420")

    async def test_kr_kis_empty_dict(self):
        """KIS 실패 -> {} 반환 -> None"""
        kis = AsyncMock()
        kis.get_korea_price.return_value = {}
        fetcher = SpotPriceFetcher(kis_client=kis)
        result = await fetcher.fetch_spot_price("005930.KS")
        assert result is None


class TestUSSpotPrice:
    """US 종목 KIS API 조회 테스트"""

    async def test_us_spot_price_success(self):
        """US KIS mock -> 정상 반환"""
        kis = AsyncMock()
        kis.get_overseas_price.return_value = {
            "symbol": "AAPL",
            "price": 180.0,
            "high": 182.0,
            "low": 178.0,
            "open": 179.0,
            "volume": 5000000,
        }
        fetcher = SpotPriceFetcher(kis_client=kis)
        result = await fetcher.fetch_spot_price("AAPL")
        assert result is not None
        assert result["price"] == 180.0
        assert result["is_delayed"] is False

    async def test_us_excd_nas_code(self):
        """KISMarket.USA -> 'NAS' 코드로 호출 확인"""
        from src.kis_api import KISMarket

        kis = AsyncMock()
        kis.get_overseas_price.return_value = {"price": 180.0, "high": 182.0, "low": 178.0, "volume": 100}
        fetcher = SpotPriceFetcher(kis_client=kis)
        await fetcher.fetch_spot_price("AAPL")
        kis.get_overseas_price.assert_called_once_with("AAPL", KISMarket.USA)


class TestCryptoSpotPrice:
    """Crypto CCXT 조회 테스트"""

    async def test_crypto_spot_price_success(self):
        """CCXT mock -> 정상 반환"""
        kis = AsyncMock()  # KIS client present but crypto uses CCXT
        fetcher = SpotPriceFetcher(kis_client=kis)
        mock_ticker = {
            "last": 45000.0,
            "high": 46000.0,
            "low": 44000.0,
            "open": 44500.0,
            "baseVolume": 1234,
        }
        with patch.object(SpotPriceFetcher, "_get_ccxt_ticker", return_value=mock_ticker):
            result = await fetcher.fetch_spot_price("BTC-USD")
        assert result is not None
        assert result["price"] == 45000.0
        assert result["is_delayed"] is False

    async def test_crypto_ccxt_exception(self):
        """CCXT 예외 -> None 반환"""
        kis = AsyncMock()
        fetcher = SpotPriceFetcher(kis_client=kis)
        with patch.object(SpotPriceFetcher, "_get_ccxt_ticker", side_effect=Exception("exchange down")):
            result = await fetcher.fetch_spot_price("BTC-USD")
        assert result is None


class TestFallback:
    """KIS 미설정 시 yfinance fallback 테스트"""

    async def test_kis_unavailable_fallback(self):
        """KIS None -> yfinance fallback, is_delayed=True"""
        fetcher = SpotPriceFetcher(kis_client=None)
        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 150.0
        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = await fetcher.fetch_spot_price("AAPL")
        assert result is not None
        assert result["is_delayed"] is True
        assert result["price"] == 150.0

    async def test_fallback_high_low_equals_price(self):
        """fallback시 high=low=price (0이 아님, 거짓 스톱로스 방지)"""
        fetcher = SpotPriceFetcher(kis_client=None)
        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 200.0
        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = await fetcher.fetch_spot_price("SPY")
        assert result["high"] == 200.0
        assert result["low"] == 200.0
        assert result["high"] != 0
        assert result["low"] != 0

    async def test_single_symbol_failure_skip(self):
        """개별 예외 -> None 반환, 예외 전파 없음"""
        kis = AsyncMock()
        kis.get_overseas_price.side_effect = Exception("network error")
        fetcher = SpotPriceFetcher(kis_client=kis)
        result = await fetcher.fetch_spot_price("INVALID")
        assert result is None  # No exception propagated

    async def test_kis_api_timeout(self):
        """asyncio.TimeoutError -> None 반환"""
        kis = AsyncMock()
        kis.get_overseas_price.side_effect = asyncio.TimeoutError()
        fetcher = SpotPriceFetcher(kis_client=kis)
        result = await fetcher.fetch_spot_price("AAPL")
        assert result is None
