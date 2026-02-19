"""
멀티마켓 데이터 수집 모듈
- yfinance: 미국/글로벌 주식
- FinanceDataReader: 한국 주식
- ccxt: 암호화폐
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class DataSource(Enum):
    YFINANCE = "yfinance"
    FDR = "fdr"
    CCXT = "ccxt"
    KIS = "kis"


class MarketType(Enum):
    US_STOCK = "us_stock"
    KR_STOCK = "kr_stock"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    BOND = "bond"


def get_market_type(symbol: str) -> MarketType:
    """심볼로 마켓 타입 추론"""
    if "/" in symbol or symbol.endswith("USDT"):
        return MarketType.CRYPTO
    if symbol.isdigit() or symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return MarketType.KR_STOCK
    if symbol in ["GLD", "SLV", "USO", "UNG", "DBA", "DBC"]:
        return MarketType.COMMODITY
    if symbol in ["TLT", "IEF", "SHY", "BND", "AGG", "LQD"]:
        return MarketType.BOND
    return MarketType.US_STOCK


class DataFetcher:
    def __init__(self, default_period: str = "2y"):
        self.default_period = default_period
        self._ccxt_exchange = None

    def _get_ccxt_exchange(self):
        if self._ccxt_exchange is None:
            try:
                import ccxt

                self._ccxt_exchange = ccxt.binance({"enableRateLimit": True})
            except ImportError:
                logger.warning("ccxt not installed")
                return None
        return self._ccxt_exchange

    def fetch_yfinance(
        self, symbol: str, start: Optional[str] = None, end: Optional[str] = None, period: Optional[str] = None
    ) -> pd.DataFrame:
        """yfinance로 데이터 수집"""
        try:
            ticker = yf.Ticker(symbol)
            if period:
                df = ticker.history(period=period)
            else:
                df = ticker.history(start=start, end=end)

            if df.empty:
                logger.warning(f"yfinance 데이터 없음: {symbol}")
                return pd.DataFrame()

            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            df = df.rename(columns={"date": "date"})

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

            return df[["date", "open", "high", "low", "close", "volume"]]

        except Exception as e:
            logger.error(f"yfinance 오류 ({symbol}): {e}")
            return pd.DataFrame()

    def fetch_fdr(self, symbol: str, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        """FinanceDataReader로 한국 주식 데이터 수집"""
        try:
            import FinanceDataReader as fdr

            if start is None:
                start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
            if end is None:
                end = datetime.now().strftime("%Y-%m-%d")

            # 한국 종목 코드 처리
            kr_symbol = symbol.replace(".KS", "").replace(".KQ", "")

            df = fdr.DataReader(kr_symbol, start, end)

            if df.empty:
                logger.warning(f"FDR 데이터 없음: {symbol}")
                return pd.DataFrame()

            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]

            return df[["date", "open", "high", "low", "close", "volume"]]

        except ImportError:
            logger.warning("FinanceDataReader not installed, falling back to yfinance")
            return self.fetch_yfinance(symbol, start, end)
        except Exception as e:
            logger.error(f"FDR 오류 ({symbol}): {e}")
            return pd.DataFrame()

    def fetch_crypto(self, symbol: str, timeframe: str = "1d", limit: int = 500) -> pd.DataFrame:
        """CCXT로 암호화폐 데이터 수집"""
        exchange = self._get_ccxt_exchange()
        if exchange is None:
            logger.warning("ccxt 사용 불가, yfinance로 대체")
            # 암호화폐를 yfinance로 시도 (예: BTC-USD)
            yf_symbol = symbol.replace("/", "-").replace("USDT", "USD")
            return self.fetch_yfinance(yf_symbol, period=self.default_period)

        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.drop("timestamp", axis=1)

            return df[["date", "open", "high", "low", "close", "volume"]]

        except Exception as e:
            logger.error(f"CCXT 오류 ({symbol}): {e}")
            return pd.DataFrame()

    def fetch(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: Optional[str] = None,
        source: Optional[DataSource] = None,
    ) -> pd.DataFrame:
        """통합 데이터 수집 인터페이스"""
        market_type = get_market_type(symbol)

        if source:
            if source == DataSource.YFINANCE:
                return self.fetch_yfinance(symbol, start, end, period)
            elif source == DataSource.FDR:
                return self.fetch_fdr(symbol, start, end)
            elif source == DataSource.CCXT:
                return self.fetch_crypto(symbol)

        # 자동 소스 선택
        if market_type == MarketType.KR_STOCK:
            df = self.fetch_fdr(symbol, start, end)
            if df.empty:
                df = self.fetch_yfinance(symbol, start, end, period)
        elif market_type == MarketType.CRYPTO:
            df = self.fetch_crypto(symbol)
        else:
            df = self.fetch_yfinance(symbol, start, end, period or self.default_period)

        return df

    def fetch_multiple(
        self, symbols: List[str], start: Optional[str] = None, end: Optional[str] = None, period: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        """여러 종목 데이터 수집"""
        results = {}
        for symbol in symbols:
            logger.info(f"데이터 수집: {symbol}")
            df = self.fetch(symbol, start, end, period)
            if not df.empty:
                results[symbol] = df
        return results

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """최신 가격 조회"""
        df = self.fetch(symbol, period="5d")
        if df.empty:
            return None
        return float(df["close"].iloc[-1])

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        """여러 종목 최신 가격 조회"""
        prices = {}
        for symbol in symbols:
            price = self.get_latest_price(symbol)
            if price:
                prices[symbol] = price
        return prices
