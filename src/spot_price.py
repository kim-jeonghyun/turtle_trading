"""
장중 실시간 가격 조회 모듈 — KIS API 기반 async 전용.

DataFetcher(sync, 일봉)와 분리하여 기존 코드 오염 방지.
"""

import asyncio
import logging
from typing import Optional, TypedDict

from src.kis_api import KISAPIClient, KISMarket
from src.market_calendar import infer_market

logger = logging.getLogger(__name__)


class SpotData(TypedDict):
    """장중 실시간 가격 데이터."""

    price: float
    high: float
    low: float
    open: float
    volume: int
    is_delayed: bool


class SpotPriceFetcher:
    """장중 실시간 가격 조회. KIS API 기반 async 전용.

    DataFetcher(sync, 일봉)와 분리하여 기존 코드 오염 방지.
    KISAPIClient는 외부에서 async with로 세션 관리.
    """

    def __init__(self, kis_client: Optional[KISAPIClient] = None):
        self._kis = kis_client

    async def fetch_spot_price(self, symbol: str) -> Optional[SpotData]:
        """실시간 현재가 조회.

        Returns:
            {"price": float, "high": float, "low": float,
             "open": float, "volume": int, "is_delayed": bool}
            or None on failure
        """
        try:
            market = infer_market(symbol)

            if self._kis is None:
                return self._fallback_yfinance(symbol)

            if market == "KR":
                return await self._fetch_kr(symbol)
            elif market == "US":
                return await self._fetch_us(symbol)
            elif market == "CRYPTO":
                return await self._fetch_crypto(symbol)
            else:
                logger.warning(f"미지원 마켓: {market} ({symbol})")
                return None

        except asyncio.TimeoutError:
            logger.error(f"가격 조회 타임아웃: {symbol}")
            return None
        except Exception as e:
            logger.error(f"가격 조회 오류: {symbol} - {e}", exc_info=True)
            return None

    async def _fetch_kr(self, symbol: str) -> Optional[SpotData]:
        """KR 종목 KIS API 조회."""
        assert self._kis is not None  # caller checks _kis before dispatch
        raw = symbol.replace(".KS", "").replace(".KQ", "")
        result = await self._kis.get_korea_price(raw)
        if not result:  # {} is falsy
            return None
        return SpotData(
            price=result["price"],
            high=result["high"],
            low=result["low"],
            open=result["open"],
            volume=result.get("volume", 0),
            is_delayed=False,
        )

    async def _fetch_us(self, symbol: str) -> Optional[SpotData]:
        """US 종목 KIS API 조회."""
        assert self._kis is not None  # caller checks _kis before dispatch
        result = await self._kis.get_overseas_price(symbol, KISMarket.USA)
        if not result:
            return None
        return SpotData(
            price=result["price"],
            high=result["high"],
            low=result["low"],
            open=result["open"],
            volume=result.get("volume", 0),
            is_delayed=False,
        )

    async def _fetch_crypto(self, symbol: str) -> Optional[SpotData]:
        """Crypto CCXT ticker 조회 (sync -> async thread)."""
        try:
            ticker = await asyncio.to_thread(self._get_ccxt_ticker, symbol)
            if not ticker:
                return None
            return {
                "price": float(ticker.get("last", 0)),
                "high": float(ticker.get("high", 0)),
                "low": float(ticker.get("low", 0)),
                "open": float(ticker.get("open", 0)),
                "volume": int(ticker.get("baseVolume", 0) or 0),
                "is_delayed": False,
            }
        except Exception as e:
            logger.error(f"CCXT 조회 오류: {symbol} - {e}")
            return None

    @staticmethod
    def _get_ccxt_ticker(symbol: str) -> Optional[dict]:
        """CCXT로 crypto ticker 조회 (sync 호출)."""
        try:
            import ccxt

            exchange = ccxt.binance()
            # symbol convention: BTC-USD -> BTC/USDT
            ccxt_symbol = symbol.replace("-USD", "/USDT")
            return dict(exchange.fetch_ticker(ccxt_symbol))
        except Exception as e:
            logger.error(f"CCXT ticker 실패: {symbol} - {e}")
            return None

    def _fallback_yfinance(self, symbol: str) -> Optional[SpotData]:
        """KIS 미설정 시 yfinance fallback.

        중요: high=low=price로 설정 (0이면 LONG 포지션에서 거짓 스톱로스 발생).
        """
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            price = ticker.fast_info.last_price
            if price is None or price <= 0:
                logger.warning(f"yfinance 가격 없음: {symbol}")
                return None
            return {
                "price": float(price),
                "high": float(price),  # NOT 0 -- 거짓 스톱로스 방지
                "low": float(price),  # NOT 0 -- 거짓 스톱로스 방지
                "open": 0.0,
                "volume": 0,
                "is_delayed": True,
            }
        except Exception as e:
            logger.error(f"yfinance fallback 실패: {symbol} - {e}")
            return None
