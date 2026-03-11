import pandas as pd
import pytest

from src.market_breadth import (
    BreadthSnapshot,
    calculate_advance_decline,
    calculate_breadth_score,
    calculate_new_high_low,
    calculate_pct_above_ma,
)


def _make_ohlcv(closes: list[float], n_days: int = 270) -> pd.DataFrame:
    """테스트용 OHLCV 생성. close만 의미있고 나머지는 close 기반 파생.

    기본 270일로 52주(260일) NH/NL 계산에 충분한 데이터를 보장.
    """
    dates = pd.bdate_range(end="2026-03-10", periods=n_days)[-len(closes) :]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


class TestPctAboveMA:
    def test_all_above(self):
        data = {
            "A": _make_ohlcv([float(i) for i in range(50, 100)]),
            "B": _make_ohlcv([float(i) for i in range(50, 100)]),
        }
        result = calculate_pct_above_ma(data, period=20)
        assert result == pytest.approx(100.0)

    def test_none_above(self):
        data = {
            "A": _make_ohlcv([float(i) for i in range(100, 50, -1)]),
            "B": _make_ohlcv([float(i) for i in range(100, 50, -1)]),
        }
        result = calculate_pct_above_ma(data, period=20)
        assert result == pytest.approx(0.0)

    def test_mixed(self):
        data = {
            "UP": _make_ohlcv([float(i) for i in range(50, 100)]),
            "DOWN": _make_ohlcv([float(i) for i in range(100, 50, -1)]),
        }
        result = calculate_pct_above_ma(data, period=20)
        assert result == pytest.approx(50.0)

    def test_empty_data(self):
        result = calculate_pct_above_ma({}, period=20)
        assert result == 0.0


class TestNewHighLow:
    def test_new_highs_52week(self):
        """52주(260일) 신고가 검출: 지속 상승 데이터에서 마지막 종가가 260일 신고가."""
        closes = [100.0 + i * 0.5 for i in range(270)]
        data = {"A": _make_ohlcv(closes, n_days=270)}
        highs, lows = calculate_new_high_low(data, period=260)
        assert highs == 1
        assert lows == 0

    def test_new_lows_52week(self):
        """52주(260일) 신저가 검출: 지속 하락 데이터에서 마지막 종가가 260일 신저가."""
        closes = [300.0 - i * 0.5 for i in range(270)]
        data = {"A": _make_ohlcv(closes, n_days=270)}
        highs, lows = calculate_new_high_low(data, period=260)
        assert highs == 0
        assert lows == 1

    def test_insufficient_data_skipped(self):
        """260일 미만 데이터는 NH/NL 계산에서 제외."""
        closes = [100.0 + i for i in range(100)]
        data = {"A": _make_ohlcv(closes, n_days=100)}
        highs, lows = calculate_new_high_low(data, period=260)
        assert highs == 0
        assert lows == 0

    def test_mixed_highs_and_lows(self):
        """상승 종목과 하락 종목이 섞인 경우."""
        up_closes = [100.0 + i * 0.5 for i in range(270)]
        down_closes = [300.0 - i * 0.5 for i in range(270)]
        data = {
            "UP": _make_ohlcv(up_closes, n_days=270),
            "DOWN": _make_ohlcv(down_closes, n_days=270),
        }
        highs, lows = calculate_new_high_low(data, period=260)
        assert highs == 1
        assert lows == 1


class TestAdvanceDecline:
    def test_all_advancing(self):
        closes = [100, 101, 102, 103, 104, 105]
        data = {
            "A": _make_ohlcv(closes),
            "B": _make_ohlcv(closes),
        }
        adv, dec = calculate_advance_decline(data)
        assert adv == 2
        assert dec == 0

    def test_mixed(self):
        data = {
            "UP": _make_ohlcv([100, 101, 102, 103, 104, 105]),
            "DOWN": _make_ohlcv([105, 104, 103, 102, 101, 100]),
        }
        adv, dec = calculate_advance_decline(data)
        assert adv == 1
        assert dec == 1


class TestBreadthScore:
    def test_snapshot_fields(self):
        closes_up = [float(i) for i in range(1, 272)]
        data = {
            "A": _make_ohlcv(closes_up, n_days=271),
            "B": _make_ohlcv(closes_up, n_days=271),
        }
        snapshot = calculate_breadth_score(data)
        assert isinstance(snapshot, BreadthSnapshot)
        assert 0 <= snapshot.composite_score <= 100
        assert snapshot.pct_above_200ma is not None
        assert snapshot.pct_above_50ma is not None
        assert snapshot.pct_above_20ma is not None
        assert snapshot.new_highs >= 0
        assert snapshot.new_lows >= 0

    def test_bullish_score_high(self):
        closes_up = [float(i) for i in range(1, 272)]
        data = {
            "A": _make_ohlcv(closes_up, n_days=271),
            "B": _make_ohlcv(closes_up, n_days=271),
        }
        snapshot = calculate_breadth_score(data)
        assert snapshot.composite_score > 60

    def test_to_dict_keys(self):
        closes_up = [float(i) for i in range(1, 272)]
        data = {"A": _make_ohlcv(closes_up, n_days=271)}
        snapshot = calculate_breadth_score(data)
        d = snapshot.to_dict()
        expected_keys = {
            "pct_above_20ma",
            "pct_above_50ma",
            "pct_above_200ma",
            "new_highs",
            "new_lows",
            "nh_nl_ratio",
            "advancing",
            "declining",
            "net_advancing",
            "composite_score",
            "total_symbols",
        }
        assert set(d.keys()) == expected_keys
