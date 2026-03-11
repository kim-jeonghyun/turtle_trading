import pandas as pd

from src.regime_detector import RegimeSnapshot, classify_regime
from src.types import MarketRegime


def _make_trending_up(n: int = 250) -> pd.DataFrame:
    """강한 상승 추세 데이터 (close > SMA200, SMA50 > SMA200, 기울기 상승)."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100 + i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "open": closes,
            "volume": [1000] * n,
        }
    )


def _make_trending_down(n: int = 250) -> pd.DataFrame:
    """강한 하락 추세 데이터."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [200 - i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "open": closes,
            "volume": [1000] * n,
        }
    )


def _make_recovery(n: int = 250) -> pd.DataFrame:
    """회복 추세: close > SMA200, SMA50 > SMA200, but SMA200 기울기 < 1.5%."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [150 - i * 0.05 for i in range(200)]
    closes += [closes[-1] + i * 0.5 for i in range(1, 51)]
    return pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "open": closes,
            "volume": [1000] * n,
        }
    )


def _make_decline(n: int = 250) -> pd.DataFrame:
    """약한 하락: close < SMA200, SMA50 < SMA200, but SMA200 기울기 > -1.5%."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100 + i * 0.05 for i in range(200)]
    closes += [closes[-1] - i * 0.5 for i in range(1, 51)]
    return pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "open": closes,
            "volume": [1000] * n,
        }
    )


def _make_crossing(n: int = 250) -> pd.DataFrame:
    """SMA50 > SMA200 이지만 close < SMA200인 교차 데이터 → SIDEWAYS."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100 + i * 0.3 for i in range(200)]
    closes += [closes[-1] - i * 1.5 for i in range(1, 51)]
    return pd.DataFrame(
        {
            "date": dates,
            "close": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "open": closes,
            "volume": [1000] * n,
        }
    )


class TestClassifyRegime:
    def test_bull_regime(self):
        df = _make_trending_up()
        result = classify_regime(df)
        assert result.regime == MarketRegime.BULL

    def test_bear_regime(self):
        df = _make_trending_down()
        result = classify_regime(df)
        assert result.regime == MarketRegime.BEAR

    def test_recovery_regime(self):
        df = _make_recovery()
        result = classify_regime(df)
        assert result.regime == MarketRegime.RECOVERY

    def test_decline_regime(self):
        df = _make_decline()
        result = classify_regime(df)
        assert result.regime == MarketRegime.DECLINE

    def test_sideways_via_crossing(self):
        """SMA50과 SMA200 교차 구간 → SIDEWAYS."""
        df = _make_crossing()
        result = classify_regime(df)
        assert result.regime == MarketRegime.SIDEWAYS

    def test_insufficient_data_defaults_sideways(self):
        df = _make_trending_up(n=50)
        result = classify_regime(df)
        assert result.regime == MarketRegime.SIDEWAYS

    def test_returns_snapshot(self):
        df = _make_trending_up()
        result = classify_regime(df)
        assert isinstance(result, RegimeSnapshot)
        assert isinstance(result.regime, MarketRegime)
        assert isinstance(result.sma_50, float)
        assert isinstance(result.sma_200, float)

    def test_to_dict(self):
        df = _make_trending_up()
        result = classify_regime(df)
        d = result.to_dict()
        assert "regime" in d
        assert "sma_50" in d
        assert "sma_200" in d
        assert "slope_200" in d


class TestSlopeThresholdBoundary:
    """레짐 slope 임계값(1.5%) 경계 테스트."""

    def test_slope_above_threshold_is_bull(self):
        """SMA200 기울기 > 1.5%이면 BULL (close > SMA200, SMA50 > SMA200)."""
        n = 250
        # 강한 상승: slope가 threshold를 초과하도록 설계
        dates = pd.bdate_range(end="2026-03-10", periods=n)
        closes = [100 + i * 0.5 for i in range(n)]
        df = pd.DataFrame(
            {
                "date": dates,
                "close": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "open": closes,
                "volume": [1000] * n,
            }
        )
        result = classify_regime(df)
        assert result.regime == MarketRegime.BULL
        assert abs(result.slope_200) > 0.015

    def test_slope_below_threshold_is_recovery(self):
        """SMA200 기울기 <= 1.5%이면 RECOVERY (close > SMA200, SMA50 > SMA200)."""
        n = 250
        # 완만한 상승: slope가 threshold 이하가 되도록 설계
        dates = pd.bdate_range(end="2026-03-10", periods=n)
        # 앞부분은 평탄, 마지막 구간만 약간 상승 → SMA200 기울기 낮음
        closes = [100.0] * 200 + [100.0 + i * 0.3 for i in range(50)]
        df = pd.DataFrame(
            {
                "date": dates,
                "close": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "open": closes,
                "volume": [1000] * n,
            }
        )
        result = classify_regime(df)
        # close > SMA200, SMA50 > SMA200, but low slope → RECOVERY
        assert result.regime == MarketRegime.RECOVERY
        assert abs(result.slope_200) <= 0.015

    def test_negative_slope_above_threshold_is_bear(self):
        """SMA200 기울기 < -1.5%이면 BEAR (close < SMA200, SMA50 < SMA200)."""
        n = 250
        dates = pd.bdate_range(end="2026-03-10", periods=n)
        closes = [200 - i * 0.5 for i in range(n)]
        df = pd.DataFrame(
            {
                "date": dates,
                "close": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "open": closes,
                "volume": [1000] * n,
            }
        )
        result = classify_regime(df)
        assert result.regime == MarketRegime.BEAR
        assert result.slope_200 < -0.015
