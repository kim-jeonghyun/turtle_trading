"""TrendFilter 단위 테스트.

TrendFilterConfig 기본값:
  er_period=20, er_threshold=0.3,
  blocked_regimes=[BEAR, DECLINE],
  sideways_er_boost=0.1
"""

import pytest

from src.trend_filter import FilterStats, TrendFilter, TrendFilterConfig
from src.types import MarketRegime


class TestTrendFilterRegimeBlock:
    """Macro 축: 레짐 기반 차단."""

    def test_bear_regime_blocks_entry(self):
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.BEAR, er_value=0.8)
        assert result.allowed is False
        assert "BEAR" in result.reason
        assert result.regime == MarketRegime.BEAR
        assert result.er_value == 0.8

    def test_decline_regime_blocks_entry(self):
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.DECLINE, er_value=0.8)
        assert result.allowed is False
        assert "DECLINE" in result.reason

    def test_bull_regime_allows_entry(self):
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.BULL, er_value=0.5)
        assert result.allowed is True
        assert result.reason == "passed"

    def test_recovery_regime_allows_entry(self):
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.RECOVERY, er_value=0.5)
        assert result.allowed is True


class TestTrendFilterERBlock:
    """Micro 축: ER 기반 차단."""

    def test_low_er_blocks_entry(self):
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.BULL, er_value=0.2)
        assert result.allowed is False
        assert "ER" in result.reason

    def test_er_just_below_threshold_blocks(self):
        """ER 0.2999 < 0.3 → 차단."""
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.BULL, er_value=0.2999)
        assert result.allowed is False

    def test_er_exactly_at_threshold_passes(self):
        """ER == threshold (0.3) → 통과 (strict < 비교이므로 같으면 통과)."""
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.BULL, er_value=0.3)
        assert result.allowed is True

    def test_er_just_above_threshold_passes(self):
        """ER 0.3001 > 0.3 → 통과."""
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.BULL, er_value=0.3001)
        assert result.allowed is True

    def test_sideways_regime_boosts_threshold(self):
        """SIDEWAYS: threshold = 0.3 + 0.1 = 0.4."""
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.SIDEWAYS, er_value=0.35)
        assert result.allowed is False
        assert "0.40" in result.reason

    def test_sideways_above_boosted_threshold_passes(self):
        """SIDEWAYS: ER 0.45 > 0.4 → 통과."""
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.SIDEWAYS, er_value=0.45)
        assert result.allowed is True


class TestTrendFilterStats:
    """통계 카운터 정확성."""

    def test_stats_accumulate_correctly(self):
        tf = TrendFilter()
        tf.should_enter(MarketRegime.BEAR, 0.8)
        tf.should_enter(MarketRegime.BULL, 0.1)
        tf.should_enter(MarketRegime.BULL, 0.5)
        tf.should_enter(MarketRegime.DECLINE, 0.9)
        tf.should_enter(MarketRegime.SIDEWAYS, 0.35)

        assert tf.stats["checked"] == 5
        assert tf.stats["blocked_regime"] == 2
        assert tf.stats["blocked_er"] == 2
        assert tf.stats["passed"] == 1

    def test_get_filter_stats_returns_dataclass(self):
        tf = TrendFilter()
        tf.should_enter(MarketRegime.BULL, 0.5)
        tf.should_enter(MarketRegime.BEAR, 0.8)

        fs = tf.get_filter_stats()
        assert isinstance(fs, FilterStats)
        assert fs.total_checked == 2
        assert fs.blocked_by_regime == 1
        assert fs.blocked_by_er == 0
        assert fs.passed == 1
        assert fs.block_rate == pytest.approx(0.5)

    def test_empty_stats_no_division_error(self):
        tf = TrendFilter()
        fs = tf.get_filter_stats()
        assert fs.total_checked == 0
        assert fs.block_rate == 0.0


class TestTrendFilterConfig:
    """커스텀 설정."""

    def test_custom_er_threshold(self):
        config = TrendFilterConfig(er_threshold=0.5)
        tf = TrendFilter(config)
        result = tf.should_enter(MarketRegime.BULL, er_value=0.4)
        assert result.allowed is False

    def test_custom_blocked_regimes(self):
        config = TrendFilterConfig(blocked_regimes=[MarketRegime.BEAR])
        tf = TrendFilter(config)
        result = tf.should_enter(MarketRegime.DECLINE, er_value=0.5)
        assert result.allowed is True

    def test_custom_sideways_boost(self):
        config = TrendFilterConfig(sideways_er_boost=0.2)
        tf = TrendFilter(config)
        result = tf.should_enter(MarketRegime.SIDEWAYS, er_value=0.45)
        assert result.allowed is False


class TestTrendFilterResult:
    """TrendFilterResult 필드 검증."""

    def test_result_contains_all_fields(self):
        tf = TrendFilter()
        result = tf.should_enter(MarketRegime.BULL, er_value=0.5)
        assert hasattr(result, "allowed")
        assert hasattr(result, "reason")
        assert hasattr(result, "regime")
        assert hasattr(result, "er_value")


class TestResolveRegimeProxy:
    """resolve_regime_proxy() 및 DEFAULT_REGIME_PROXIES 테스트."""

    def test_us_equity_returns_spy(self):
        from src.trend_filter import resolve_regime_proxy
        from src.types import AssetGroup
        assert resolve_regime_proxy(AssetGroup.US_EQUITY) == "SPY"

    def test_kr_equity_returns_ewy(self):
        from src.trend_filter import resolve_regime_proxy
        from src.types import AssetGroup
        assert resolve_regime_proxy(AssetGroup.KR_EQUITY) == "EWY"

    def test_crypto_returns_none_for_sideways_fallback(self):
        """CRYPTO는 매핑 없음 → None 반환."""
        from src.trend_filter import resolve_regime_proxy
        from src.types import AssetGroup
        assert resolve_regime_proxy(AssetGroup.CRYPTO) is None

    def test_config_override_takes_precedence(self):
        from src.trend_filter import resolve_regime_proxy
        from src.types import AssetGroup
        assert resolve_regime_proxy(AssetGroup.US_EQUITY, config_override="QQQ") == "QQQ"

    def test_all_non_crypto_groups_have_proxy(self):
        """CRYPTO 제외 모든 AssetGroup에 프록시 매핑 존재."""
        from src.trend_filter import DEFAULT_REGIME_PROXIES
        from src.types import AssetGroup
        for group in AssetGroup:
            if group == AssetGroup.CRYPTO:
                assert group not in DEFAULT_REGIME_PROXIES
            else:
                assert group in DEFAULT_REGIME_PROXIES, f"{group} missing from DEFAULT_REGIME_PROXIES"


from src.backtester import Trade


class TestTradeERField:
    def test_trade_has_er_at_entry_field(self):
        from datetime import datetime
        trade = Trade(symbol="SPY", entry_date=datetime(2025, 1, 1), entry_price=100.0)
        assert trade.er_at_entry is None

    def test_trade_er_at_entry_set(self):
        from datetime import datetime
        trade = Trade(symbol="SPY", entry_date=datetime(2025, 1, 1), entry_price=100.0, er_at_entry=0.45)
        assert trade.er_at_entry == 0.45


from src.position_tracker import Position
from src.types import Direction


class TestPositionERRoundTrip:
    def test_position_er_at_entry_to_dict_from_dict(self):
        pos = Position(
            position_id="SPY_1_LONG_20250301_120000",
            symbol="SPY", system=1, direction=Direction.LONG,
            entry_date="2025-03-01", entry_price=100.0, entry_n=2.0,
            units=1, max_units=4, shares_per_unit=40, total_shares=40,
            stop_loss=96.0, pyramid_level=0, exit_period=10,
            status="open", last_update="2025-03-01T12:00:00",
            er_at_entry=0.42,
        )
        d = pos.to_dict()
        assert d["er_at_entry"] == 0.42
        restored = Position.from_dict(d)
        assert restored.er_at_entry == 0.42

    def test_position_er_at_entry_none_roundtrip(self):
        pos = Position(
            position_id="SPY_1_LONG_20250301_120000",
            symbol="SPY", system=1, direction=Direction.LONG,
            entry_date="2025-03-01", entry_price=100.0, entry_n=2.0,
            units=1, max_units=4, shares_per_unit=40, total_shares=40,
            stop_loss=96.0, pyramid_level=0, exit_period=10,
            status="open", last_update="2025-03-01T12:00:00",
        )
        d = pos.to_dict()
        assert d["er_at_entry"] is None
        restored = Position.from_dict(d)
        assert restored.er_at_entry is None
