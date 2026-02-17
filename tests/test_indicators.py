"""
indicators.py 단위 테스트
- True Range 계산 검증
- Wilder's ATR 검증
- Donchian Channel 검증
- Unit 크기 계산 검증
"""

import pytest
import pandas as pd
import numpy as np
from src.indicators import (
    calculate_true_range,
    calculate_n,
    calculate_donchian_channel,
    add_turtle_indicators,
    calculate_unit_size,
    ATRMethod
)


class TestTrueRange:
    def test_basic_true_range(self):
        """TR = max(H-L, |H-PC|, |PC-L|)"""
        df = pd.DataFrame({
            'high': [110, 115, 112],
            'low': [95, 105, 108],
            'close': [100, 110, 109]
        })
        tr = calculate_true_range(df)

        # Day 0: H-L=15, |H-PC|=nan, |PC-L|=nan -> 15
        assert tr.iloc[0] == 15.0
        # Day 1: H-L=10, |115-100|=15, |100-105|=5 -> 15
        assert tr.iloc[1] == 15.0
        # Day 2: H-L=4, |112-110|=2, |110-108|=2 -> 4
        assert tr.iloc[2] == 4.0

    def test_gap_up_true_range(self):
        """갭 상승 시 TR이 |H-PC| 반영"""
        df = pd.DataFrame({
            'high': [110, 130],
            'low': [100, 120],
            'close': [105, 125]
        })
        tr = calculate_true_range(df)
        # Day 1: H-L=10, |130-105|=25, |105-120|=15 -> 25
        assert tr.iloc[1] == 25.0


class TestWildersATR:
    def test_atr_positive(self, sample_ohlcv_df):
        """ATR은 항상 양수"""
        n = calculate_n(sample_ohlcv_df, period=20)
        assert (n.dropna() > 0).all()

    def test_atr_period(self, sample_ohlcv_df):
        """ATR 기간에 따른 결과 차이"""
        n_short = calculate_n(sample_ohlcv_df, period=10)
        n_long = calculate_n(sample_ohlcv_df, period=20)
        # 둘 다 유효해야 함
        assert not n_short.dropna().empty
        assert not n_long.dropna().empty

    def test_wilder_vs_ema(self, sample_ohlcv_df):
        """Wilder 방식과 EMA 방식이 다른 결과 생성"""
        n_wilder = calculate_n(sample_ohlcv_df, method=ATRMethod.WILDER)
        n_ema = calculate_n(sample_ohlcv_df, method=ATRMethod.EMA)
        # 방법이 다르므로 결과가 달라야 함
        assert not n_wilder.equals(n_ema)


class TestDonchianChannel:
    def test_channel_columns(self, sample_ohlcv_df):
        """Donchian Channel 컬럼 확인"""
        dc = calculate_donchian_channel(sample_ohlcv_df)
        expected_cols = ['dc_high_55', 'dc_low_55', 'dc_high_20', 'dc_low_20', 'dc_high_10', 'dc_low_10']
        for col in expected_cols:
            assert col in dc.columns, f"Missing column: {col}"

    def test_channel_shift(self, sample_ohlcv_df):
        """Donchian Channel이 shift(1) 적용되었는지 확인"""
        dc = calculate_donchian_channel(sample_ohlcv_df, entry_period=20, exit_period=10)
        # 첫 번째 행은 NaN이어야 함 (shift 때문)
        assert pd.isna(dc['dc_high_20'].iloc[0])

    def test_high_greater_than_low(self, sample_ohlcv_df):
        """High 채널 > Low 채널"""
        dc = calculate_donchian_channel(sample_ohlcv_df)
        valid = dc.dropna()
        assert (valid['dc_high_55'] >= valid['dc_low_55']).all()
        assert (valid['dc_high_20'] >= valid['dc_low_20']).all()


class TestCalculateUnitSize:
    def test_basic_unit_calculation(self):
        """기본 유닛 계산: (equity * risk) / (N * dollar_per_point)"""
        # 100,000 * 0.01 / (2.0 * 1.0) = 500
        result = calculate_unit_size(n_value=2.0, account_equity=100000, risk_per_unit=0.01)
        assert result == 500

    def test_zero_n_value(self):
        """N=0일 때 0 반환"""
        result = calculate_unit_size(n_value=0, account_equity=100000)
        assert result == 0

    def test_negative_n_value(self):
        """N<0일 때 0 반환"""
        result = calculate_unit_size(n_value=-1.0, account_equity=100000)
        assert result == 0

    def test_argument_order(self):
        """인자 순서 확인: (n_value, account_equity, ...)"""
        result = calculate_unit_size(
            n_value=5.0,
            account_equity=100000,
            risk_per_unit=0.01
        )
        # 100000 * 0.01 / 5.0 = 200
        assert result == 200


class TestAddTurtleIndicators:
    def test_all_columns_present(self, sample_ohlcv_df):
        """모든 지표 컬럼 존재 확인"""
        result = add_turtle_indicators(sample_ohlcv_df)
        required = ['TrueRange', 'N', 'dc_high_55', 'dc_low_55',
                     'dc_high_20', 'dc_low_20', 'dc_high_10', 'dc_low_10']
        for col in required:
            assert col in result.columns, f"Missing: {col}"

    def test_original_data_preserved(self, sample_ohlcv_df):
        """원본 데이터가 보존되는지 확인"""
        result = add_turtle_indicators(sample_ohlcv_df)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            assert col in result.columns
        pd.testing.assert_series_equal(
            result['close'], sample_ohlcv_df['close'], check_names=False
        )
