"""
시장 브레드스(Market Breadth) 지표 모듈.

350종목 OHLCV 데이터 기반으로 시장 전체 건강도를 측정.
- % above MA (20/50/200일)
- New High / New Low 카운트 (52주 = 260 영업일)
- Advance / Decline 카운트
- Composite Breadth Score (0-100)
"""

import logging
from dataclasses import dataclass

import pandas as pd

from src.indicators import calculate_sma

logger = logging.getLogger(__name__)


@dataclass
class BreadthSnapshot:
    """브레드스 지표 스냅샷."""

    pct_above_20ma: float
    pct_above_50ma: float
    pct_above_200ma: float
    new_highs: int
    new_lows: int
    advancing: int
    declining: int
    composite_score: float
    total_symbols: int

    @property
    def nh_nl_ratio(self) -> float:
        """New High / New Low 비율. New Low가 0이면 new_highs 반환."""
        return self.new_highs / max(self.new_lows, 1)

    @property
    def net_advancing(self) -> int:
        return self.advancing - self.declining

    def to_dict(self) -> dict:
        return {
            "pct_above_20ma": round(self.pct_above_20ma, 1),
            "pct_above_50ma": round(self.pct_above_50ma, 1),
            "pct_above_200ma": round(self.pct_above_200ma, 1),
            "new_highs": self.new_highs,
            "new_lows": self.new_lows,
            "nh_nl_ratio": round(self.nh_nl_ratio, 2),
            "advancing": self.advancing,
            "declining": self.declining,
            "net_advancing": self.net_advancing,
            "composite_score": round(self.composite_score, 1),
            "total_symbols": self.total_symbols,
        }


def calculate_pct_above_ma(data: dict[str, pd.DataFrame], period: int = 20) -> float:
    """종목 중 이동평균선 위에 있는 비율(%) 계산."""
    if not data:
        return 0.0

    above = 0
    valid = 0
    for symbol, df in data.items():
        if len(df) < period:
            continue
        sma = calculate_sma(df["close"], period)
        last_close = df["close"].iloc[-1]
        last_sma = sma.iloc[-1]
        if pd.isna(last_sma):
            continue
        valid += 1
        if last_close > last_sma:
            above += 1

    return (above / valid * 100) if valid > 0 else 0.0


def calculate_new_high_low(data: dict[str, pd.DataFrame], period: int = 260) -> tuple[int, int]:
    """N일 신고가/신저가 종목 수."""
    new_highs = 0
    new_lows = 0
    for symbol, df in data.items():
        if len(df) < period + 1:
            continue
        lookback = df.iloc[-(period + 1) : -1]
        today_close = df["close"].iloc[-1]
        if today_close >= lookback["close"].max():
            new_highs += 1
        if today_close <= lookback["close"].min():
            new_lows += 1
    return new_highs, new_lows


def calculate_advance_decline(
    data: dict[str, pd.DataFrame],
) -> tuple[int, int]:
    """오늘 상승/하락 종목 수."""
    advancing = 0
    declining = 0
    for symbol, df in data.items():
        if len(df) < 2:
            continue
        today_close = df["close"].iloc[-1]
        yesterday_close = df["close"].iloc[-2]
        if today_close > yesterday_close:
            advancing += 1
        elif today_close < yesterday_close:
            declining += 1
    return advancing, declining


def calculate_breadth_score(
    data: dict[str, pd.DataFrame],
) -> BreadthSnapshot:
    """종합 브레드스 스코어 계산.

    Components (가중치):
    - % above 200MA: 30%  (장기 건강도)
    - % above 50MA:  25%  (중기 추세)
    - % above 20MA:  20%  (단기 모멘텀)
    - NH/NL 비율:    15%  (브레이크아웃 활력, 52주 기준)
    - AD 비율:       10%  (당일 참여도)
    """
    pct_20 = calculate_pct_above_ma(data, 20)
    pct_50 = calculate_pct_above_ma(data, 50)
    pct_200 = calculate_pct_above_ma(data, 200)
    new_highs, new_lows = calculate_new_high_low(data, period=260)
    advancing, declining = calculate_advance_decline(data)
    total = len(data)

    nh_nl_ratio = new_highs / max(new_lows, 1)
    nh_nl_score = min(nh_nl_ratio / 3.0 * 100, 100.0)

    ad_total = advancing + declining
    ad_score = (advancing / ad_total * 100) if ad_total > 0 else 50.0

    def _scale_pct(pct: float, ceiling: float = 80.0) -> float:
        return min(pct / ceiling * 100, 100.0)

    composite = (
        _scale_pct(pct_200) * 0.30
        + _scale_pct(pct_50) * 0.25
        + _scale_pct(pct_20) * 0.20
        + nh_nl_score * 0.15
        + ad_score * 0.10
    )

    return BreadthSnapshot(
        pct_above_20ma=pct_20,
        pct_above_50ma=pct_50,
        pct_above_200ma=pct_200,
        new_highs=new_highs,
        new_lows=new_lows,
        advancing=advancing,
        declining=declining,
        composite_score=min(composite, 100.0),
        total_symbols=total,
    )
