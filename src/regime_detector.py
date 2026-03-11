"""
시장 레짐 분류 모듈.

Rule-based 레짐 판별:
- BULL: close > SMA200, SMA50 > SMA200, SMA200 기울기 상승 (>1.5%)
- RECOVERY: close > SMA200, SMA50 > SMA200, 기울기 약함 (<=1.5%)
- SIDEWAYS: SMA50과 SMA200 교차 구간 또는 데이터 부족
- DECLINE: close < SMA200, SMA50 < SMA200, 기울기 약함 (>=-1.5%)
- BEAR: close < SMA200, SMA50 < SMA200, SMA200 기울기 하락 (<-1.5%)
"""

import logging
from dataclasses import dataclass

import pandas as pd

from src.indicators import calculate_sma
from src.types import MarketRegime

logger = logging.getLogger(__name__)

# SMA200 기울기 임계값 (20일간 1.5% 변화) — BULL/BEAR vs RECOVERY/DECLINE 구분
_SLOPE_THRESHOLD = 0.015

# SMA50/SMA200 최근 교차 탐지 윈도우 (bars) — SIDEWAYS 전환 구간 감지
_CROSS_LOOKBACK = 15


@dataclass
class RegimeSnapshot:
    """레짐 판별 결과 스냅샷."""

    regime: MarketRegime
    last_close: float
    sma_50: float
    sma_200: float
    slope_200: float

    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "last_close": round(self.last_close, 2),
            "sma_50": round(self.sma_50, 2),
            "sma_200": round(self.sma_200, 2),
            "slope_200": round(self.slope_200, 4),
        }


def _recently_crossed_below(sma_50: pd.Series, sma_200: pd.Series, lookback: int) -> bool:
    """최근 lookback 기간 내 SMA50이 SMA200 위에 있었는지 확인 (하향 교차 탐지)."""
    n = len(sma_50)
    start = max(0, n - 1 - lookback)
    for i in range(n - 1, start, -1):
        if float(sma_50.iloc[i]) > float(sma_200.iloc[i]):
            return True
    return False


def classify_regime(df: pd.DataFrame) -> RegimeSnapshot:
    """DataFrame의 close 기반 레짐 분류."""
    close = df["close"]

    if len(close) < 200:
        logger.debug("레짐 분류: 데이터 부족 (%d행), SIDEWAYS 기본값", len(close))
        last = float(close.iloc[-1]) if len(close) > 0 else 0.0
        return RegimeSnapshot(
            regime=MarketRegime.SIDEWAYS,
            last_close=last,
            sma_50=0.0,
            sma_200=0.0,
            slope_200=0.0,
        )

    sma_50 = calculate_sma(close, 50)
    sma_200 = calculate_sma(close, 200)

    last_close = float(close.iloc[-1])
    last_sma50 = float(sma_50.iloc[-1])
    last_sma200 = float(sma_200.iloc[-1])

    # SMA200의 20일간 기울기
    sma200_20d_ago = float(sma_200.iloc[-20]) if len(sma_200) >= 20 else last_sma200
    slope = (last_sma200 - sma200_20d_ago) / sma200_20d_ago if sma200_20d_ago != 0 else 0.0

    # 분류
    above_200 = last_close > last_sma200
    sma50_above_200 = last_sma50 > last_sma200

    if above_200 and sma50_above_200:
        regime = MarketRegime.BULL if slope > _SLOPE_THRESHOLD else MarketRegime.RECOVERY
    elif not above_200 and not sma50_above_200:
        # SMA50이 최근 SMA200을 하향 돌파한 직후는 SIDEWAYS (전환 구간)
        recently_crossed = _recently_crossed_below(sma_50, sma_200, _CROSS_LOOKBACK)
        if recently_crossed:
            regime = MarketRegime.SIDEWAYS
        else:
            regime = MarketRegime.BEAR if slope < -_SLOPE_THRESHOLD else MarketRegime.DECLINE
    else:
        regime = MarketRegime.SIDEWAYS

    return RegimeSnapshot(
        regime=regime,
        last_close=last_close,
        sma_50=last_sma50,
        sma_200=last_sma200,
        slope_200=slope,
    )
