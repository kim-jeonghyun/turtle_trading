# Trend Quality Filter Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dual Trend Quality Filter (Macro regime + Micro ER) to block whipsaw entries in non-US ETFs while preserving US equity performance.

**Architecture:** `TrendFilter` is a shared pure-logic module consumed by both `backtester.py` and `check_positions.py` for live/backtest equivalence. ER calculation is added to `indicators.py`. Filter is opt-in via `--trend-filter` CLI flag. Entry-Only: SELL is never blocked.

**Tech Stack:** Python 3.12, pandas, pytest, existing modules (`regime_detector.py`, `indicators.py`, `types.py`)

**Spec:** `docs/superpowers/specs/2026-03-13-trend-quality-filter-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/trend_filter.py` | TrendFilter class, TrendFilterConfig, TrendFilterResult, FilterStats, DEFAULT_REGIME_PROXIES |
| Modify | `src/indicators.py:100` | Add `calculate_efficiency_ratio()` after last function |
| Modify | `src/backtester.py:38-51` | Add `use_trend_quality_filter`, `er_threshold`, `regime_proxy_symbol` to BacktestConfig; `filter_stats` to BacktestResult; `er_at_entry` to Trade |
| Modify | `src/backtester.py:69-112` | Inject TrendFilter into TurtleBacktester.__init__ and _check_entry_signal |
| Modify | `src/backtester.py:141-145` | Add ER column calculation in run() |
| Modify | `src/position_tracker.py:29-71` | Add `er_at_entry: Optional[float]` to Position |
| Modify | `scripts/check_positions.py:129-227` | Inject TrendFilter into check_entry_signals() |
| Modify | `scripts/run_backtest.py:29-56` | Add `--trend-filter`, `--er-threshold`, `--regime-proxy` CLI args |
| Modify | `scripts/run_backtest.py:90-125` | Pass trend filter config to BacktestConfig and print FilterStats |
| Create | `tests/test_trend_filter.py` | TrendFilter unit tests |
| Modify | `tests/test_indicators.py` | Add ER calculation tests |
| Modify | `tests/test_backtester_live_equivalence.py` | Add trend filter equivalence scenarios |

---

## Chunk 1: Core Modules (Indicators + TrendFilter)

### Task 1: Add `calculate_efficiency_ratio()` to indicators.py

**Files:**
- Modify: `src/indicators.py:100` (append after `calculate_unit_size`)
- Test: `tests/test_indicators.py`

- [ ] **Step 1: Write failing tests for ER calculation**

Add to `tests/test_indicators.py`:

```python
import numpy as np
import pandas as pd
import pytest

from src.indicators import calculate_efficiency_ratio


class TestEfficiencyRatio:
    """Kaufman Efficiency Ratio 계산 테스트."""

    def test_straight_uptrend_er_near_one(self):
        """직선 상승 → ER ≈ 1.0."""
        prices = pd.Series([100.0 + i for i in range(25)])
        er = calculate_efficiency_ratio(prices, period=20)
        # 마지막 값 (충분한 데이터 이후)
        assert er.iloc[-1] == pytest.approx(1.0, abs=0.01)

    def test_straight_downtrend_er_near_one(self):
        """직선 하락 → ER ≈ 1.0."""
        prices = pd.Series([200.0 - i for i in range(25)])
        er = calculate_efficiency_ratio(prices, period=20)
        assert er.iloc[-1] == pytest.approx(1.0, abs=0.01)

    def test_choppy_data_er_low(self):
        """지그재그 횡보 → ER < 0.3."""
        # +1, -1 반복 (순이동 ≈ 0)
        prices = pd.Series([100.0 + (i % 2) * 2 - 1 for i in range(25)])
        er = calculate_efficiency_ratio(prices, period=20)
        assert er.iloc[-1] < 0.3

    def test_empty_series_returns_zeros(self):
        """빈 시리즈 → 빈 시리즈."""
        prices = pd.Series([], dtype=float)
        er = calculate_efficiency_ratio(prices, period=20)
        assert len(er) == 0

    def test_short_series_returns_fillna_zero(self):
        """period 미만 데이터 → NaN이 0으로 채워짐."""
        prices = pd.Series([100.0, 101.0, 102.0])
        er = calculate_efficiency_ratio(prices, period=20)
        assert all(er == 0.0)

    def test_zero_volatility_returns_zero(self):
        """일정한 가격 (변동성 0) → ER = 0 (NaN → 0)."""
        prices = pd.Series([100.0] * 25)
        er = calculate_efficiency_ratio(prices, period=20)
        assert er.iloc[-1] == 0.0

    def test_default_period_is_20(self):
        """기본 period=20 확인."""
        prices = pd.Series([100.0 + i for i in range(25)])
        er_default = calculate_efficiency_ratio(prices)
        er_explicit = calculate_efficiency_ratio(prices, period=20)
        pd.testing.assert_series_equal(er_default, er_explicit)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_indicators.py::TestEfficiencyRatio -v`
Expected: FAIL with `ImportError: cannot import name 'calculate_efficiency_ratio'`

- [ ] **Step 3: Implement `calculate_efficiency_ratio()`**

Add at end of `src/indicators.py` (after line 100):

```python
def calculate_efficiency_ratio(series: pd.Series, period: int = 20) -> pd.Series:
    """Kaufman Efficiency Ratio: |net_movement| / path_sum.

    0 = 완전한 횡보(choppy), 1 = 직선 추세(straight trend).

    Args:
        series: 가격 시리즈 (close)
        period: 룩백 기간 (기본 20, S1 lookback과 동일)

    Returns:
        ER 시리즈 (0.0 ~ 1.0, NaN → 0으로 채움)
    """
    direction = abs(series - series.shift(period))
    volatility = abs(series.diff()).rolling(period).sum()
    return (direction / volatility.replace(0, float("nan"))).fillna(0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_indicators.py::TestEfficiencyRatio -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/indicators.py tests/test_indicators.py
git commit -m "[#TBD] feat: add Kaufman Efficiency Ratio to indicators"
```

---

### Task 2: Create `src/trend_filter.py` module

**Files:**
- Create: `src/trend_filter.py`
- Create: `tests/test_trend_filter.py`

- [ ] **Step 1: Write failing tests for TrendFilter**

Create `tests/test_trend_filter.py`:

```python
"""TrendFilter 단위 테스트.

TrendFilterConfig 기본값:
  er_period=20, er_threshold=0.3,
  blocked_regimes=[BEAR, DECLINE],
  sideways_er_boost=0.1
"""

import pytest

from src.trend_filter import TrendFilter, TrendFilterConfig, TrendFilterResult, FilterStats
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
        # 0.35 < 0.4 → 차단
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
        tf.should_enter(MarketRegime.BEAR, 0.8)      # blocked_regime
        tf.should_enter(MarketRegime.BULL, 0.1)       # blocked_er
        tf.should_enter(MarketRegime.BULL, 0.5)       # passed
        tf.should_enter(MarketRegime.DECLINE, 0.9)    # blocked_regime
        tf.should_enter(MarketRegime.SIDEWAYS, 0.35)  # blocked_er (0.35 < 0.40)

        assert tf.stats["checked"] == 5
        assert tf.stats["blocked_regime"] == 2
        assert tf.stats["blocked_er"] == 2
        assert tf.stats["passed"] == 1

    def test_get_filter_stats_returns_dataclass(self):
        tf = TrendFilter()
        tf.should_enter(MarketRegime.BULL, 0.5)       # passed
        tf.should_enter(MarketRegime.BEAR, 0.8)       # blocked_regime

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
        # DECLINE은 차단 목록에서 제외됨
        result = tf.should_enter(MarketRegime.DECLINE, er_value=0.5)
        assert result.allowed is True

    def test_custom_sideways_boost(self):
        config = TrendFilterConfig(sideways_er_boost=0.2)
        tf = TrendFilter(config)
        # threshold = 0.3 + 0.2 = 0.5
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
        """CRYPTO는 매핑 없음 → None 반환 (caller가 SIDEWAYS 폴백)."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trend_filter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.trend_filter'`

- [ ] **Step 3: Create `src/trend_filter.py`**

```python
"""듀얼 트렌드 품질 필터 모듈.

Macro (시장 레짐) + Micro (종목별 ER) 이중 검증으로 진입 품질 관리.
Entry-Only: SELL(손절/청산)은 절대 차단하지 않음.
"""

from dataclasses import dataclass, field
from typing import Optional

from src.types import AssetGroup, MarketRegime


@dataclass
class TrendFilterConfig:
    """트렌드 필터 설정."""

    er_period: int = 20
    er_threshold: float = 0.3
    blocked_regimes: list[MarketRegime] = field(
        default_factory=lambda: [MarketRegime.BEAR, MarketRegime.DECLINE]
    )
    sideways_er_boost: float = 0.1


@dataclass
class TrendFilterResult:
    """필터 판정 결과."""

    allowed: bool
    reason: str
    regime: MarketRegime
    er_value: float


@dataclass
class FilterStats:
    """필터 통계 (BacktestResult 포함용)."""

    total_checked: int = 0
    blocked_by_regime: int = 0
    blocked_by_er: int = 0
    passed: int = 0
    block_rate: float = 0.0


# 자산군별 레짐 프록시 기본 매핑
DEFAULT_REGIME_PROXIES: dict[AssetGroup, str] = {
    AssetGroup.US_EQUITY: "SPY",
    AssetGroup.US_TECH: "SPY",
    AssetGroup.KR_EQUITY: "EWY",
    AssetGroup.ASIA_EQUITY: "EEM",
    AssetGroup.CHINA_EQUITY: "EEM",
    AssetGroup.EU_EQUITY: "VGK",
    AssetGroup.COMMODITY: "DBC",
    AssetGroup.COMMODITY_ENERGY: "DBC",
    AssetGroup.COMMODITY_AGRI: "DBC",
    AssetGroup.BOND: "TLT",
    AssetGroup.CURRENCY: "UUP",
    AssetGroup.REIT: "VNQ",
    AssetGroup.ALTERNATIVES: "SPY",
    AssetGroup.INVERSE: "SPY",
    # CRYPTO: 매핑 없음 → regime=SIDEWAYS 폴백
}


def resolve_regime_proxy(
    asset_group: AssetGroup, config_override: Optional[str] = None
) -> Optional[str]:
    """레짐 프록시 심볼 해석.

    config_override > 자산군 기본값 > None(SIDEWAYS 폴백).
    """
    if config_override:
        return config_override
    return DEFAULT_REGIME_PROXIES.get(asset_group)


class TrendFilter:
    """듀얼 트렌드 품질 필터.

    Macro (시장 레짐) + Micro (종목별 ER) 이중 검증.
    Entry-Only: SELL은 절대 차단하지 않음.
    """

    def __init__(self, config: Optional[TrendFilterConfig] = None):
        self.config = config or TrendFilterConfig()
        self.stats = {"checked": 0, "blocked_regime": 0, "blocked_er": 0, "passed": 0}

    def get_filter_stats(self) -> FilterStats:
        """stats dict → FilterStats dataclass 변환."""
        total = self.stats["checked"]
        blocked = self.stats["blocked_regime"] + self.stats["blocked_er"]
        return FilterStats(
            total_checked=total,
            blocked_by_regime=self.stats["blocked_regime"],
            blocked_by_er=self.stats["blocked_er"],
            passed=self.stats["passed"],
            block_rate=blocked / total if total > 0 else 0.0,
        )

    def should_enter(
        self, regime: MarketRegime, er_value: float
    ) -> TrendFilterResult:
        """진입 허용 여부 판단.

        Args:
            regime: 현재 시장 레짐
            er_value: 종목의 Efficiency Ratio (0.0~1.0)

        Returns:
            TrendFilterResult (allowed, reason, regime, er_value)
        """
        self.stats["checked"] += 1

        # 1) Macro: 레짐 체크
        if regime in self.config.blocked_regimes:
            self.stats["blocked_regime"] += 1
            return TrendFilterResult(
                allowed=False,
                reason=f"{regime.value} regime blocked",
                regime=regime,
                er_value=er_value,
            )

        # 2) Micro: ER 체크 (SIDEWAYS는 임계값 상향)
        threshold = self.config.er_threshold
        if regime == MarketRegime.SIDEWAYS:
            threshold += self.config.sideways_er_boost

        if er_value < threshold:
            self.stats["blocked_er"] += 1
            return TrendFilterResult(
                allowed=False,
                reason=f"ER {er_value:.2f} < {threshold:.2f}",
                regime=regime,
                er_value=er_value,
            )

        self.stats["passed"] += 1
        return TrendFilterResult(
            allowed=True,
            reason="passed",
            regime=regime,
            er_value=er_value,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trend_filter.py -v`
Expected: All 24 tests PASS

- [ ] **Step 5: Run linter**

Run: `ruff check src/trend_filter.py tests/test_trend_filter.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add src/trend_filter.py tests/test_trend_filter.py
git commit -m "[#TBD] feat: add TrendFilter module with dual regime+ER filtering"
```

---

## Chunk 2: Backtester Integration

### Task 3: Add `er_at_entry` to Trade and Position dataclasses

**Files:**
- Modify: `src/backtester.py:24-36` (Trade dataclass)
- Modify: `src/position_tracker.py:68` (Position dataclass, after `entry_reason`)
- Test: existing tests must still pass

- [ ] **Step 1: Write failing test for Trade.er_at_entry**

Add to `tests/test_trend_filter.py` (or a new section):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trend_filter.py::TestTradeERField -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'er_at_entry'`

- [ ] **Step 3: Add `er_at_entry` to Trade dataclass**

In `src/backtester.py`, after line 35 (`entry_reason: str = ""`), add:

```python
    er_at_entry: Optional[float] = None
```

- [ ] **Step 4: Add `er_at_entry` to Position dataclass**

In `src/position_tracker.py`, after line 68 (`entry_reason: Optional[str] = None`), add:

```python
    er_at_entry: Optional[float] = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_trend_filter.py::TestTradeERField tests/test_position_tracker.py -v`
Expected: PASS

- [ ] **Step 6: Verify Position persistence round-trip**

Add to `tests/test_trend_filter.py`:

```python
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
```

Run: `pytest tests/test_trend_filter.py::TestPositionERRoundTrip -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/backtester.py src/position_tracker.py tests/test_trend_filter.py
git commit -m "[#TBD] feat: add er_at_entry field to Trade and Position"
```

---

### Task 4: Add `FilterStats` and trend filter config to BacktestConfig/Result

**Files:**
- Modify: `src/backtester.py:38-66` (BacktestConfig, BacktestResult)

- [ ] **Step 1: Write failing test**

Add to `tests/test_trend_filter.py`:

```python
from src.backtester import BacktestConfig, BacktestResult


class TestBacktestConfigTrendFilter:
    def test_default_trend_filter_off(self):
        config = BacktestConfig()
        assert config.use_trend_quality_filter is False

    def test_trend_filter_config_fields(self):
        config = BacktestConfig(
            use_trend_quality_filter=True,
            er_threshold=0.25,
            regime_proxy_symbol="EWY",
        )
        assert config.use_trend_quality_filter is True
        assert config.er_threshold == 0.25
        assert config.regime_proxy_symbol == "EWY"


class TestBacktestResultFilterStats:
    def test_filter_stats_default_none(self):
        result = BacktestResult(config=BacktestConfig())
        assert result.filter_stats is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trend_filter.py::TestBacktestConfigTrendFilter -v`
Expected: FAIL

- [ ] **Step 3: Add fields to BacktestConfig and BacktestResult**

In `src/backtester.py`, add import at top (line 13 area):
```python
from src.trend_filter import FilterStats
```

In `BacktestConfig` (after line 47 `commission_pct`), add:
```python
    use_trend_quality_filter: bool = False
    er_threshold: float = 0.3
    regime_proxy_symbol: Optional[str] = None
```

In `BacktestResult` (after line 66 `avg_loss`), add:
```python
    filter_stats: Optional[FilterStats] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trend_filter.py::TestBacktestConfigTrendFilter tests/test_trend_filter.py::TestBacktestResultFilterStats -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/backtester.py tests/test_trend_filter.py
git commit -m "[#TBD] feat: add trend filter config to BacktestConfig/Result"
```

---

### Task 5: Integrate TrendFilter into TurtleBacktester

**Files:**
- Modify: `src/backtester.py:69-192` (TurtleBacktester.__init__, run, _check_entry_signal, _open_position, _calculate_results)

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_trend_filter.py`:

```python
import pandas as pd
from datetime import datetime

from src.backtester import BacktestConfig, TurtleBacktester
from src.types import MarketRegime


def _make_test_data(n_days=60):
    """직선 상승 테스트 데이터 생성 (ER ≈ 1.0)."""
    dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
    data = {
        "date": dates,
        "open": [100 + i * 0.5 for i in range(n_days)],
        "high": [101 + i * 0.5 for i in range(n_days)],
        "low": [99 + i * 0.5 for i in range(n_days)],
        "close": [100 + i * 0.5 for i in range(n_days)],
        "volume": [1000000] * n_days,
    }
    return pd.DataFrame(data)


class TestBacktesterTrendFilterIntegration:
    def test_filter_off_by_default(self):
        """use_trend_quality_filter=False → TrendFilter 미생성."""
        config = BacktestConfig()
        bt = TurtleBacktester(config)
        assert bt.trend_filter is None

    def test_filter_on_creates_trend_filter(self):
        """use_trend_quality_filter=True → TrendFilter 생성."""
        config = BacktestConfig(use_trend_quality_filter=True)
        bt = TurtleBacktester(config)
        assert bt.trend_filter is not None

    def test_filter_on_vs_off_trade_count(self):
        """필터 ON 시 거래 수 ≤ 필터 OFF 거래 수."""
        data = {"SPY": _make_test_data()}

        config_off = BacktestConfig(use_trend_quality_filter=False)
        result_off = TurtleBacktester(config_off).run(data.copy())

        config_on = BacktestConfig(use_trend_quality_filter=True)
        result_on = TurtleBacktester(config_on).run(data.copy())

        assert result_on.total_trades <= result_off.total_trades

    def test_filter_stats_populated_when_enabled(self):
        """필터 활성화 시 BacktestResult에 FilterStats 포함."""
        data = {"SPY": _make_test_data()}
        config = BacktestConfig(use_trend_quality_filter=True)
        result = TurtleBacktester(config).run(data)
        assert result.filter_stats is not None
        assert result.filter_stats.total_checked >= 0

    def test_filter_stats_none_when_disabled(self):
        """필터 비활성화 시 FilterStats = None."""
        data = {"SPY": _make_test_data()}
        config = BacktestConfig(use_trend_quality_filter=False)
        result = TurtleBacktester(config).run(data)
        assert result.filter_stats is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_trend_filter.py::TestBacktesterTrendFilterIntegration -v`
Expected: FAIL with `AttributeError: 'TurtleBacktester' object has no attribute 'trend_filter'`

- [ ] **Step 3: Implement TrendFilter integration in TurtleBacktester**

In `src/backtester.py`, add imports (top of file):
```python
from src.trend_filter import TrendFilter, TrendFilterConfig, FilterStats
from src.indicators import calculate_efficiency_ratio
```

> **Known simplification:** 백테스터에서 regime은 SIDEWAYS 기본값 사용. 프록시 인덱스 데이터 페칭은
> 백테스트 성능에 큰 오버헤드이므로, 현재 스코프에서는 ER 필터만 활성 상태.
> Regime 기반 필터링은 라이브 경로에서 `classify_regime()` 연동 시 활성화 예정 (Out of Scope).

In `__init__` (after `self.risk_manager` initialization, ~line 80), add:
```python
        self.trend_filter: Optional[TrendFilter] = None
        if config.use_trend_quality_filter:
            tf_config = TrendFilterConfig(er_threshold=config.er_threshold)
            self.trend_filter = TrendFilter(tf_config)
```

In `run()` method (after `data[symbol] = add_turtle_indicators(df)`, ~line 145), add ER column:
```python
            if self.trend_filter:
                data[symbol]["er"] = calculate_efficiency_ratio(
                    df["close"], period=self.trend_filter.config.er_period
                )
```

In `_check_entry_signal()` (at the start, before breakout check, ~line 92), add:
```python
        if self.trend_filter:
            er_value = row.get("er", 0.0)
            # Regime: SIDEWAYS 기본값 (프록시 데이터 없는 백테스트 단순화)
            regime = MarketRegime.SIDEWAYS
            result = self.trend_filter.should_enter(regime, er_value)
            if not result.allowed:
                logger.debug(f"[TrendFilter] {symbol} 진입 차단: {result.reason}")
                return None
```

In `__init__` (after `self.entry_reasons` line 77), add:
```python
        self._er_at_entry: Dict[str, Optional[float]] = {}
```

In `run()` loop, change `_open_position` call (~line 186) to pass er_value:
```python
                        er_value = row.get("er", None) if self.trend_filter else None
                        self._open_position(symbol, date, row["close"], n_value, direction, er_value)
```

Modify `_open_position` signature (~line 194) to accept er_value:
```python
    def _open_position(self, symbol: str, date: datetime, price: float, n_value: float, direction: Direction, er_value: Optional[float] = None):
```

In `_open_position`, after `self.entry_reasons[symbol] = ...` (~line 216), add:
```python
        self._er_at_entry[symbol] = er_value
```

In `_close_position` (~line 259), add `er_at_entry` to Trade constructor:
```python
        trade = Trade(
            ...
            entry_reason=self.entry_reasons.pop(symbol, ""),
            er_at_entry=self._er_at_entry.pop(symbol, None),
        )
```

In `_calculate_results()` (return 문 전), add:
```python
        filter_stats = self.trend_filter.get_filter_stats() if self.trend_filter else None
```

And add `filter_stats=filter_stats` to the BacktestResult constructor.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_trend_filter.py::TestBacktesterTrendFilterIntegration -v`
Expected: PASS

- [ ] **Step 5: Run all existing backtester tests**

Run: `pytest tests/test_backtester.py tests/test_trend_filter.py -v`
Expected: All PASS (기존 테스트 회귀 없음)

- [ ] **Step 6: Run linter and type checker**

Run: `ruff check src/backtester.py && mypy src/backtester.py --ignore-missing-imports`
Expected: Clean

- [ ] **Step 7: Commit**

```bash
git add src/backtester.py tests/test_trend_filter.py
git commit -m "[#TBD] feat: integrate TrendFilter into TurtleBacktester"
```

---

## Chunk 3: Live Path + CLI + Equivalence

### Task 6: Integrate TrendFilter into check_positions.py

**Files:**
- Modify: `scripts/check_positions.py:19-31` (imports)
- Modify: `scripts/check_positions.py:129-227` (check_entry_signals signature + filter logic)
- Modify: `scripts/check_positions.py:292-625` (_run_checks — instantiate TrendFilter, compute ER, pass to callers)
- Test: `tests/test_backtester_live_equivalence.py`

- [ ] **Step 1: Write failing equivalence test using actual backtester/live adapters**

Add to `tests/test_backtester_live_equivalence.py` (at bottom):

```python
from src.trend_filter import TrendFilter, TrendFilterConfig
from src.indicators import calculate_efficiency_ratio
from src.types import MarketRegime


class TestTrendFilterEquivalence:
    """TrendFilter가 backtester와 live checker 양쪽에서 동일하게 동작하는지 검증.

    양쪽 모두 동일한 TrendFilter 모듈을 사용하므로 구조적 동치성이 보장되지만,
    실제 호출 경로(backtester._check_entry_signal / check_entry_signals)를 통해
    필터가 올바르게 적용되는지 end-to-end 검증한다.
    """

    def _make_df_with_er(self, er_value: float):
        """ER 컬럼이 포함된 2행 DataFrame 생성."""
        n_value = 2.0
        yesterday = {
            "date": pd.Timestamp("2025-03-01"),
            "high": 100.0, "low": 98.0, "close": 99.0, "N": n_value,
            "dc_high_20": DC_HIGH_20, "dc_low_20": DC_LOW_20,
            "dc_high_55": DC_HIGH_55, "dc_low_55": DC_LOW_55,
            "er": er_value,
        }
        today = {
            "date": pd.Timestamp("2025-03-02"),
            "high": ABOVE_20_ONLY, "low": NEUTRAL_LOW,
            "close": (ABOVE_20_ONLY + NEUTRAL_LOW) / 2, "N": n_value,
            "dc_high_20": DC_HIGH_20, "dc_low_20": DC_LOW_20,
            "dc_high_55": DC_HIGH_55, "dc_low_55": DC_LOW_55,
            "er": er_value,
        }
        return pd.DataFrame([yesterday, today])

    def test_low_er_blocks_entry_in_live_path(self):
        """ER < threshold → live checker에서 진입 차단."""
        tf = TrendFilter()
        df = self._make_df_with_er(0.1)  # 매우 낮은 ER
        signals = check_entry_signals(df, SYMBOL, system=1, trend_filter=tf)
        assert len(signals) == 0, "low ER should block entry in live path"

    def test_high_er_allows_entry_in_live_path(self):
        """ER > threshold → live checker에서 진입 허용."""
        tf = TrendFilter()
        df = self._make_df_with_er(0.5)  # 높은 ER
        signals = check_entry_signals(df, SYMBOL, system=1, trend_filter=tf)
        # 20일 돌파 + 손실 이력 → 진입 허용 (ER 통과)
        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) > 0, "high ER should allow entry in live path"

    def test_trend_filter_none_does_not_block(self):
        """trend_filter=None → 기존 동작 유지 (필터 미적용)."""
        df = self._make_df_with_er(0.1)
        signals = check_entry_signals(df, SYMBOL, system=1, trend_filter=None)
        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) > 0, "no filter should not block entry"

    def test_backtester_and_live_agree_on_filter_block(self):
        """동일 ER에서 backtester와 live 모두 차단."""
        low_er = 0.1

        # Backtester path: TrendFilter가 _check_entry_signal에서 차단
        config = BacktestConfig(system=1, use_trend_quality_filter=True)
        bt = TurtleBacktester(config)
        bt.last_trade_profitable[SYMBOL] = False
        prev_row = pd.Series({
            "dc_high_20": DC_HIGH_20, "dc_low_20": DC_LOW_20,
            "dc_high_55": DC_HIGH_55, "dc_low_55": DC_LOW_55,
        })
        row = pd.Series({"high": ABOVE_20_ONLY, "low": NEUTRAL_LOW, "er": low_er})
        bt_signal = bt._check_entry_signal(row, prev_row, SYMBOL)

        # Live path
        tf = TrendFilter()
        df = self._make_df_with_er(low_er)
        live_signals = check_entry_signals(df, SYMBOL, system=1, trend_filter=tf)

        # 양쪽 모두 차단
        assert bt_signal is None, "backtester should block low ER"
        assert len(live_signals) == 0, "live should block low ER"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtester_live_equivalence.py::TestTrendFilterEquivalence -v`
Expected: FAIL — `check_entry_signals` doesn't accept `trend_filter` parameter yet

- [ ] **Step 3: Add TrendFilter to check_entry_signals()**

In `scripts/check_positions.py`, add import (after line 31):
```python
from src.trend_filter import TrendFilter
from src.indicators import calculate_efficiency_ratio
```

Modify `check_entry_signals()` signature (line 129) to accept optional trend_filter:
```python
def check_entry_signals(
    df,
    symbol: str,
    system: int = 1,
    tracker: "PositionTracker | None" = None,
    asset: Optional[Asset] = None,
    trend_filter: Optional["TrendFilter"] = None,
) -> list:
```

Add filter check inside `check_entry_signals()`, after the `_was_last_trade_profitable` function def but before the breakout check (~line 157):
```python
    # Trend Quality Filter: 활성화 시 진입 차단 여부 확인
    if trend_filter:
        er_value = today.get("er", 0.0)
        # Regime: SIDEWAYS 기본값 (프록시 데이터 없는 단순화 — backtester와 동일)
        regime = MarketRegime.SIDEWAYS
        tf_result = trend_filter.should_enter(regime, er_value)
        if not tf_result.allowed:
            logger.info(f"[TrendFilter] {symbol} 진입 차단: {tf_result.reason}")
            return signals  # 빈 리스트 반환
```

Note: `MarketRegime`는 이미 `from src.types import Direction, SignalType` 줄에 추가:
```python
from src.types import Direction, MarketRegime, SignalType
```

- [ ] **Step 4: Update `_run_checks()` to instantiate TrendFilter and pass to callers**

This is the critical caller-side integration. In `_run_checks()` (~line 292):

After `vi_cb_detector = VICBDetector()` (~line 305), add TrendFilter setup:
```python
    # Trend Quality Filter (config YAML의 trend_filter 섹션으로 활성화)
    tf_config_section = config.get("trend_filter", {})
    use_trend_filter = tf_config_section.get("enabled", False)
    trend_filter: Optional[TrendFilter] = None
    if use_trend_filter:
        from src.trend_filter import TrendFilterConfig
        tf_config = TrendFilterConfig(
            er_threshold=tf_config_section.get("er_threshold", 0.3),
        )
        trend_filter = TrendFilter(tf_config)
        logger.info(f"[TrendFilter] 활성화 (ER threshold={tf_config.er_threshold})")
```

> **Config activation:** 라이브 경로에서 필터를 활성화하려면 config YAML에 다음을 추가:
> ```yaml
> trend_filter:
>   enabled: true
>   er_threshold: 0.3  # 선택, 기본값 0.3
> ```
> 기본값은 `enabled: false`로 기존 동작 보존.

In the signal check loop (~line 502), after `df = add_turtle_indicators(df)`, add ER calculation:
```python
                if trend_filter:
                    df["er"] = calculate_efficiency_ratio(df["close"])
```

Update both `check_entry_signals` call sites (~lines 514, 519) to pass `trend_filter`:
```python
                    signals_s1 = check_entry_signals(df, symbol, system=1, tracker=tracker, asset=current_asset, trend_filter=trend_filter)
                ...
                    signals_s2 = check_entry_signals(df, symbol, system=2, tracker=tracker, asset=current_asset, trend_filter=trend_filter)
```

- [ ] **Step 5: Run all equivalence tests**

Run: `pytest tests/test_backtester_live_equivalence.py -v`
Expected: All PASS (기존 시나리오 + 새 TrendFilter 시나리오)

- [ ] **Step 6: Commit**

```bash
git add scripts/check_positions.py tests/test_backtester_live_equivalence.py
git commit -m "[#TBD] feat: integrate TrendFilter into live check_entry_signals and _run_checks"
```

---

### Task 7: Add CLI flags to run_backtest.py

**Files:**
- Modify: `scripts/run_backtest.py:29-56` (parse_args)
- Modify: `scripts/run_backtest.py:90-125` (run_backtest)
- Modify: `scripts/run_backtest.py:128-150` (print_results)

- [ ] **Step 1: Add CLI arguments**

In `parse_args()` (after `--no-risk-limits` line 49), add:

```python
    parser.add_argument("--trend-filter", action="store_true", help="트렌드 품질 필터 활성화 (기본: OFF)")
    parser.add_argument("--er-threshold", type=float, default=0.3, help="ER 임계값 오버라이드")
    parser.add_argument("--regime-proxy", type=str, default=None, help="레짐 판별용 인덱스 프록시 심볼")
```

- [ ] **Step 2: Pass to BacktestConfig**

In `run_backtest()` (BacktestConfig constructor, ~line 92-101), add:

```python
        use_trend_quality_filter=args.trend_filter,
        er_threshold=args.er_threshold,
        regime_proxy_symbol=args.regime_proxy,
```

- [ ] **Step 3: Print FilterStats**

In `print_results()` (after line 150), add:

```python
    if result.filter_stats:
        print(f"\n--- Trend Quality Filter ---")
        print(f"검사 시그널:       {result.filter_stats.total_checked}")
        print(f"레짐 차단:         {result.filter_stats.blocked_by_regime}")
        print(f"ER 차단:           {result.filter_stats.blocked_by_er}")
        print(f"통과:             {result.filter_stats.passed}")
        print(f"차단율:           {result.filter_stats.block_rate * 100:.1f}%")
```

- [ ] **Step 4: Add er_at_entry to CSV export**

In `export_trades_csv()` (~line 202-225), add to trades_data dict:
```python
                "er_at_entry": trade.er_at_entry,
```

- [ ] **Step 5: Test CLI manually**

Run: `python scripts/run_backtest.py --symbols SPY --period 1y --system 1 --trend-filter --verbose 2>&1 | head -30`
Expected: 로그에 `[TrendFilter]` 메시지 또는 필터 통계 출력

- [ ] **Step 6: Commit**

```bash
git add scripts/run_backtest.py
git commit -m "[#TBD] feat: add --trend-filter CLI flags to run_backtest"
```

---

### Task 8: Full regression test

- [ ] **Step 1: Run entire test suite**

Run: `pytest -x -q`
Expected: All 1333+ tests PASS

- [ ] **Step 2: Run linter and type checker**

Run: `ruff check src/ scripts/ tests/ && mypy src/ --ignore-missing-imports`
Expected: Clean

- [ ] **Step 3: Commit any fixes**

If any issues found, fix and commit:
```bash
git commit -m "[#TBD] fix: address lint/type issues from trend filter integration"
```

---

## Chunk 4: Validation

### Task 9: Validation Backtests

**Purpose:** 필터 효과 검증 (성공 기준 달성 여부 확인)

- [ ] **Step 1: Run Asian ETF backtest without filter**

```bash
python scripts/run_backtest.py --symbols EWJ EWT VNM EEM INDA EWA --period 5y --system 1
```

Record: PF, MDD, total_trades, winning_trades

- [ ] **Step 2: Run Asian ETF backtest with filter**

```bash
python scripts/run_backtest.py --symbols EWJ EWT VNM EEM INDA EWA --period 5y --system 1 --trend-filter
```

Record: PF, MDD, total_trades, winning_trades, filter_stats
Compare: PF 개선 (0.51 → 0.8+) 또는 손실 거래 50%+ 감소

- [ ] **Step 3: Run US equity backtest with filter (성과 유지 확인)**

```bash
python scripts/run_backtest.py --symbols SPY QQQ AAPL NVDA --period 5y --system 1 --trend-filter
```

Compare: PF 변화 ±5% 이내

- [ ] **Step 4: Document results**

결과를 PR description에 포함. 성공 기준 미달 시 ER threshold 조정 고려.

- [ ] **Step 5: Final commit and PR**

```bash
git add src/trend_filter.py src/indicators.py src/backtester.py src/position_tracker.py scripts/check_positions.py scripts/run_backtest.py tests/test_trend_filter.py tests/test_indicators.py tests/test_backtester_live_equivalence.py
git commit -m "[#TBD] feat: Trend Quality Filter implementation"
```

Create PR with all changes.
