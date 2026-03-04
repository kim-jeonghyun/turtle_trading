"""
validate_data.py 단위 테스트
- 기존 DataValidator 기능
- OHLCV 논리 일관성 검증
- 날짜 갭 감지
- 가격 이상치 감지
"""

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (scripts/는 패키지가 아니므로 sys.path 필요)
# 기존 test_check_positions.py와 동일한 패턴
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest

from scripts.validate_data import (
    validate_ohlcv_consistency,
    validate_ohlcv_date_gaps,
    validate_ohlcv_outliers,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def valid_ohlcv_df():
    """정상적인 OHLCV DataFrame"""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-02-23", periods=5, freq="B"),
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [102.0, 103.0, 104.0, 105.0, 106.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [101.0, 102.0, 103.0, 104.0, 105.0],
            "volume": [1000000, 1100000, 1200000, 1300000, 1400000],
        }
    )


# ─── OHLCV Consistency ──────────────────────────────────────────────────────


class TestOHLCVConsistency:
    def test_ohlcv_consistency_valid(self, valid_ohlcv_df):
        """정상 데이터 -> 빈 issues"""
        issues = validate_ohlcv_consistency(valid_ohlcv_df, "005930")
        assert issues == []

    def test_ohlcv_high_less_than_low(self):
        """high < low 감지"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-02-23", periods=3, freq="B"),
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 99.0, 104.0],  # 두 번째 행: high(99) < low(100)
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 100.5, 103.0],
                "volume": [1000000, 1100000, 1200000],
            }
        )
        issues = validate_ohlcv_consistency(df, "005930")
        assert len(issues) >= 1
        assert any("high < low" in issue for issue in issues)

    def test_ohlcv_high_less_than_close(self):
        """high < close 감지"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-02-23", periods=3, freq="B"),
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 105.0, 103.0],  # 두 번째 행: close(105) > high(103)
                "volume": [1000000, 1100000, 1200000],
            }
        )
        issues = validate_ohlcv_consistency(df, "005930")
        assert len(issues) >= 1
        assert any("high < close/open" in issue for issue in issues)

    def test_ohlcv_negative_volume(self):
        """음수 거래량 감지"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-02-23", periods=3, freq="B"),
                "open": [100.0, 101.0, 102.0],
                "high": [102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [1000000, -500, 1200000],  # 두 번째 행: 음수 거래량
            }
        )
        issues = validate_ohlcv_consistency(df, "005930")
        assert len(issues) >= 1
        assert any("음수 거래량" in issue for issue in issues)


# ─── Date Gap Detection ──────────────────────────────────────────────────────


class TestOHLCVDateGaps:
    def test_date_gap_normal_weekend(self):
        """주말 갭(2-3일) -> 정상"""
        # 금요일 -> 월요일 = 3일 갭 (정상)
        df = pd.DataFrame(
            {
                "date": [
                    "2026-02-20",  # 금
                    "2026-02-23",  # 월 (3일 갭)
                    "2026-02-24",  # 화
                ],
                "open": [100, 101, 102],
                "high": [102, 103, 104],
                "low": [99, 100, 101],
                "close": [101, 102, 103],
                "volume": [1000000] * 3,
            }
        )
        issues = validate_ohlcv_date_gaps(df, "005930")
        assert issues == []

    def test_date_gap_holiday_extended(self):
        """설 연휴 갭(5일) -> 정상 (6일 이하)"""
        # 금요일 -> 다음주 목요일 = 5일 갭 (공휴일 포함, 정상)
        df = pd.DataFrame(
            {
                "date": [
                    "2026-01-23",  # 금
                    "2026-01-28",  # 수 (5일 갭)
                    "2026-01-29",  # 목
                ],
                "open": [100, 101, 102],
                "high": [102, 103, 104],
                "low": [99, 100, 101],
                "close": [101, 102, 103],
                "volume": [1000000] * 3,
            }
        )
        issues = validate_ohlcv_date_gaps(df, "005930")
        assert issues == []

    def test_date_gap_anomaly(self):
        """7일+ 갭 -> 감지"""
        # 7일 이상 갭 = 이상
        df = pd.DataFrame(
            {
                "date": [
                    "2026-02-16",  # 월
                    "2026-02-24",  # 화 (8일 갭)
                    "2026-02-25",  # 수
                ],
                "open": [100, 101, 102],
                "high": [102, 103, 104],
                "low": [99, 100, 101],
                "close": [101, 102, 103],
                "volume": [1000000] * 3,
            }
        )
        issues = validate_ohlcv_date_gaps(df, "005930")
        assert len(issues) == 1
        assert "8일 갭" in issues[0]

    def test_date_gap_single_row(self):
        """단일 행 -> 갭 없음"""
        df = pd.DataFrame(
            {
                "date": ["2026-02-23"],
                "open": [100],
                "high": [102],
                "low": [99],
                "close": [101],
                "volume": [1000000],
            }
        )
        issues = validate_ohlcv_date_gaps(df, "005930")
        assert issues == []


# ─── Outlier Detection ───────────────────────────────────────────────────────


class TestOHLCVOutliers:
    def test_outlier_normal_move(self):
        """3% 변동 -> 정상"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-02-23", periods=3, freq="B"),
                "open": [100.0, 103.0, 106.0],
                "high": [104.0, 107.0, 110.0],
                "low": [99.0, 102.0, 105.0],
                "close": [103.0, 106.09, 109.0],  # ~3% 변동
                "volume": [1000000] * 3,
            }
        )
        issues = validate_ohlcv_outliers(df, "005930")
        assert issues == []

    def test_outlier_limit_up_30pct(self):
        """정확히 30.0% 변동 -> 정상 (가격제한폭)"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-02-23", periods=2, freq="B"),
                "open": [100.0, 130.0],
                "high": [102.0, 132.0],
                "low": [99.0, 129.0],
                "close": [100.0, 130.0],  # 정확히 30% 상승 (상한가)
                "volume": [1000000, 2000000],
            }
        )
        issues = validate_ohlcv_outliers(df, "005930", threshold=0.31)
        assert issues == []

    def test_outlier_extreme_move(self):
        """35% 변동 -> 감지"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-02-23", periods=2, freq="B"),
                "open": [100.0, 135.0],
                "high": [102.0, 137.0],
                "low": [99.0, 134.0],
                "close": [100.0, 135.0],  # 35% 변동
                "volume": [1000000, 2000000],
            }
        )
        issues = validate_ohlcv_outliers(df, "005930")
        assert len(issues) == 1
        assert "35" in issues[0]

    def test_outlier_zero_previous_close(self):
        """전일 종가 0 -> 스킵 (ZeroDivisionError 방지)"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-02-23", periods=2, freq="B"),
                "open": [0.0, 100.0],
                "high": [0.0, 102.0],
                "low": [0.0, 99.0],
                "close": [0.0, 100.0],
                "volume": [0, 1000000],
            }
        )
        issues = validate_ohlcv_outliers(df, "005930")
        assert issues == []

    def test_outlier_single_row(self):
        """단일 행 -> 이상치 없음"""
        df = pd.DataFrame(
            {
                "date": ["2026-02-23"],
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [1000000],
            }
        )
        issues = validate_ohlcv_outliers(df, "005930")
        assert issues == []
