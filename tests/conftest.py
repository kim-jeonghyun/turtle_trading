"""
Turtle Trading 테스트 공통 Fixtures
"""

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# macOS 기본 Matplotlib 백엔드(macosx)는 headless 환경에서 abort 가능.
# 테스트 안정성을 위해 Agg 백엔드 고정.
os.environ.setdefault("MPLBACKEND", "Agg")


@pytest.fixture
def sample_ohlcv_df():
    """60일 분량의 샘플 OHLCV 데이터"""
    np.random.seed(42)
    dates = pd.date_range(start="2025-01-01", periods=60, freq="B")

    # 시작 가격에서 랜덤 워크
    price = 100.0
    rows = []
    for date in dates:
        change = np.random.normal(0, 2)
        open_price = price
        high = open_price + abs(np.random.normal(1, 0.5))
        low = open_price - abs(np.random.normal(1, 0.5))
        close = open_price + change
        volume = int(np.random.uniform(1000000, 5000000))
        rows.append(
            {
                "date": date,
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            }
        )
        price = close

    return pd.DataFrame(rows)


@pytest.fixture
def trending_up_df():
    """상승 추세 데이터 (시그널 테스트용)"""
    dates = pd.date_range(start="2025-01-01", periods=80, freq="B")
    price = 100.0
    rows = []
    for i, date in enumerate(dates):
        # 지속적인 상승 추세
        daily_return = 0.005 + np.random.normal(0, 0.005)
        open_price = price
        close = price * (1 + daily_return)
        high = max(open_price, close) * (1 + abs(np.random.normal(0.002, 0.001)))
        low = min(open_price, close) * (1 - abs(np.random.normal(0.002, 0.001)))
        volume = int(np.random.uniform(1000000, 5000000))
        rows.append(
            {
                "date": date,
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            }
        )
        price = close

    return pd.DataFrame(rows)


@pytest.fixture
def temp_data_dir():
    """임시 데이터 디렉토리"""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


@pytest.fixture
def sample_position_data():
    """샘플 포지션 데이터"""
    return {
        "position_id": "SPY_1_LONG_20250101_120000",
        "symbol": "SPY",
        "system": 1,
        "direction": "LONG",
        "entry_date": "2025-01-01",
        "entry_price": 100.0,
        "entry_n": 2.5,
        "units": 1,
        "max_units": 4,
        "shares_per_unit": 40,
        "total_shares": 40,
        "stop_loss": 95.0,
        "pyramid_level": 0,
        "exit_period": 10,
        "status": "open",
        "last_update": "2025-01-01T12:00:00",
    }


@pytest.fixture
def make_turtle_df():
    """터틀 지표가 포함된 mock DataFrame 팩토리."""

    def _factory(high=101.0, low=97.0, close=100.0, n=2.0):
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2025-03-01"),
                    "high": 100,
                    "low": 98,
                    "close": 99,
                    "N": n,
                    "dc_high_20": 105,
                    "dc_low_20": 95,
                    "dc_high_55": 110,
                    "dc_low_55": 90,
                    "dc_high_10": 103,
                    "dc_low_10": 97,
                },
                {
                    "date": pd.Timestamp("2025-03-02"),
                    "high": high,
                    "low": low,
                    "close": close,
                    "N": n,
                    "dc_high_20": 105,
                    "dc_low_20": 95,
                    "dc_high_55": 110,
                    "dc_low_55": 90,
                    "dc_high_10": 103,
                    "dc_low_10": 97,
                },
            ]
        )

    return _factory


class PatchManager:
    """unittest.mock 패치 일괄 관리 유틸리티."""

    @staticmethod
    def start_all(patches: dict) -> dict:
        """모든 패치를 시작하고 started mock 딕셔너리를 반환."""
        return {name: p.start() for name, p in patches.items()}

    @staticmethod
    def stop_all(patches: dict):
        """모든 패치를 중지."""
        for p in patches.values():
            p.stop()
