"""
터틀 트레이딩 지표 계산 모듈
- Wilder's ATR (N값)
- Donchian Channel
"""

import pandas as pd
import numpy as np
from enum import Enum


class ATRMethod(Enum):
    WILDER = "wilder"
    EMA = "ema"


def calculate_true_range(df: pd.DataFrame) -> pd.Series:
    """True Range 계산"""
    high = df['high']
    low = df['low']
    prev_close = df['close'].shift(1)

    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(prev_close - low)

    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def calculate_n(
    df: pd.DataFrame,
    period: int = 20,
    method: ATRMethod = ATRMethod.WILDER
) -> pd.Series:
    """
    N (ATR) 계산 - Wilder's Smoothing Method

    Wilder's: ATR = PDN + (TR - PDN) / period
    """
    tr = calculate_true_range(df)

    if method == ATRMethod.WILDER:
        alpha = 1.0 / period
        n = tr.ewm(alpha=alpha, adjust=False).mean()
    else:
        n = tr.ewm(span=period, adjust=False).mean()

    n.name = 'N'
    return n


def calculate_donchian_channel(
    df: pd.DataFrame,
    entry_period: int = 55,
    exit_period: int = 20
) -> pd.DataFrame:
    """Donchian Channel 계산"""
    result = pd.DataFrame(index=df.index)

    result['dc_high_55'] = df['high'].shift(1).rolling(window=entry_period).max()
    result['dc_low_55'] = df['low'].shift(1).rolling(window=entry_period).min()
    result['dc_high_20'] = df['high'].shift(1).rolling(window=exit_period).max()
    result['dc_low_20'] = df['low'].shift(1).rolling(window=exit_period).min()
    result['dc_high_10'] = df['high'].shift(1).rolling(window=10).max()
    result['dc_low_10'] = df['low'].shift(1).rolling(window=10).min()

    return result


def add_turtle_indicators(
    df: pd.DataFrame,
    n_period: int = 20,
    entry_period: int = 55,
    exit_period: int = 20,
    atr_method: ATRMethod = ATRMethod.WILDER
) -> pd.DataFrame:
    """터틀 지표 추가"""
    result = df.copy()
    result['TrueRange'] = calculate_true_range(df)
    result['N'] = calculate_n(df, period=n_period, method=atr_method)

    donchian = calculate_donchian_channel(df, entry_period, exit_period)
    result = pd.concat([result, donchian], axis=1)

    return result


def calculate_unit_size(
    n_value: float,
    account_equity: float,
    dollar_per_point: float = 1.0,
    risk_per_unit: float = 0.01
) -> int:
    """Unit 크기 계산"""
    if n_value <= 0:
        return 0
    return int((account_equity * risk_per_unit) / (n_value * dollar_per_point))
