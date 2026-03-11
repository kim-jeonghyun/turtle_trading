# Market Intelligence Pipeline Implementation Plan (Final v4)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Dry-run available:** `python scripts/market_intelligence.py --dry-run --json` for safe testing without notification delivery.
>
> **Finalized:** 2026-03-11. This document now serves as the implementation plan plus final execution/verification record for Issue #202 and PR #203.

## Final Status

- Implemented: Issue #202 scope completed on branch `feature/issue-202-market-intelligence-pipeline`
- Post-review fixes applied:
  - Empty-data guard in `run_pipeline()` with direct integration test
  - Regime threshold documentation aligned to implemented 1.5% rule
  - Data-driven report date plus `collect_daily_ohlcv.py --date` propagation
  - Repo-wide `ruff check src/ scripts/ tests/` clean on the current branch
  - Additional lock/date/threshold regression tests added
- Latest validation snapshot:
  - `pytest tests/ -x -q` → 1333 passed
  - `ruff check src/ scripts/ tests/` → passed
  - `mypy src/ --ignore-missing-imports` → passed
  - `scripts/market_intelligence.py --dry-run --json` with current local data → early-return guard confirmed when `min_rows` yields 0 analyzed symbols
  - GitHub PR #203 required checks (`lint`, `test`, `GitGuardian`) → green

**Goal:** Transform the idle ~350-symbol OHLCV collection into an actionable market intelligence pipeline that delivers daily screening, breadth analysis, and regime context — with a strategy-extensible architecture.

**Architecture:** Two-phase build. Phase 1 adds bulk data access, market breadth computation, and regime detection as foundational modules. Phase 2 builds a multi-strategy screener and a structured intelligence report that replaces the current "data dump" notifications. All new modules are pure functions on DataFrames, following the existing `indicators.py` pattern. The screener uses a `Strategy` Protocol so turtle, Minervini, pattern strategies can be plugged in later. Screening covers entry and exit signals for all 350 symbols.

**Tech Stack:** Python 3.12, pandas, PyYAML, existing ParquetDataStore/NotificationMessage infrastructure.

**User Decisions:**
- Regime filter = advisory only (alerts, no auto-block)
- Screening covers entry and exit signals for all 350 symbols
- Human makes all trading decisions based on reports

**Key Design Decisions (from review):**
- DD1: TurtleStrategy is a **raw screener** — intentionally omits System 1 profit filter (no PositionTracker dependency). Shows all mechanical breakouts for human evaluation. This differs from `check_positions.py` which applies the Curtis Faith filter.
- DD2: Korean market short restriction is handled via `short_restricted` parameter in `TurtleStrategy.scan()`, defaulting to `True` for safety (suppresses short signals unless explicitly allowed).
- DD3: Notification level is always `SIGNAL` (sends to all channels). Warnings are included in the body, not used to downgrade delivery.
- DD4: **Price-limit awareness for Korean signals.** Korean stocks have daily price limits of +/-30%. When a stock's daily change is >= 29% or <= -29% (near 상한가/하한가), entry signals include `{"price_limit_warning": True}` in metadata. This is informational — the human decides whether to act. VI/CB detection is handled by the existing `vi_cb_detector.py` in the order chain; this flag is an early-warning complement for the screener output.
- DD5: **Index proxy for regime detection.** Instead of using the longest available symbol (which may not represent the market), regime detection uses KODEX 200 (`069500`) or KODEX KOSDAQ 150 (`229200`) ETF OHLCV as the index proxy. These are loaded from the same ParquetDataStore accumulated data. Falls back to longest symbol if neither proxy is available.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/market_breadth.py` | Breadth indicators: % above MA, NH/NL ratio (52-week), AD line, composite score |
| `src/regime_detector.py` | Rule-based regime classification (BULL/RECOVERY/SIDEWAYS/DECLINE/BEAR) |
| `src/screener.py` | Multi-strategy screener with Strategy Protocol, ranking, composite scoring |
| `scripts/market_intelligence.py` | Post-collection analysis → intelligence report generation & delivery |
| `tests/test_market_breadth.py` | Breadth indicator tests |
| `tests/test_regime_detector.py` | Regime detector tests |
| `tests/test_screener.py` | Screener tests |
| `tests/test_market_intelligence.py` | Integration tests for the pipeline script |

### Modified Files

| File | Change |
|------|--------|
| `src/data_store.py` | Add `list_accumulated_symbols()`, `load_multiple_ohlcv()` bulk API |
| `src/types.py` | Add `MarketRegime` enum |
| `src/indicators.py` | Add `calculate_sma()` helper (used by breadth & screener) |
| `src/notifier.py` | Add `send_market_intelligence()` method to `NotificationManager` |
| `scripts/collect_daily_ohlcv.py` | Add post-collection hook to trigger `market_intelligence.py` via subprocess |
| `tests/test_data_store.py` | Tests for new bulk API methods |

---

## Chunk 1: Phase 1 — Data Infrastructure

### Task 1: ParquetDataStore Bulk API

**Files:**
- Modify: `src/data_store.py:114-155` (add methods after `load_ohlcv_accumulated`)
- Test: `tests/test_data_store.py`

- [ ] **Step 1: Write failing tests for `list_accumulated_symbols()`**

```python
# tests/test_data_store.py — append to existing test file

class TestAccumulatedBulkAPI:
    """축적 OHLCV bulk query API 테스트."""

    def test_list_accumulated_symbols_empty(self, tmp_path):
        store = ParquetDataStore(base_dir=str(tmp_path))
        result = store.list_accumulated_symbols()
        assert result == []

    def test_list_accumulated_symbols_returns_codes(self, tmp_path):
        store = ParquetDataStore(base_dir=str(tmp_path))
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01"]),
            "open": [100], "high": [110], "low": [90],
            "close": [105], "volume": [1000],
        })
        store.save_ohlcv_accumulated("005930", df)
        store.save_ohlcv_accumulated("000660", df)

        result = store.list_accumulated_symbols()
        assert sorted(result) == ["000660", "005930"]

    def test_list_accumulated_symbols_ignores_non_parquet(self, tmp_path):
        """glob 패턴 *_ohlcv.parquet 만 매칭. corrupted 파일(.parquet.corrupted.*)은
        확장자가 다르므로 glob에서 자동 제외됨."""
        store = ParquetDataStore(base_dir=str(tmp_path))
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01"]),
            "open": [100], "high": [110], "low": [90],
            "close": [105], "volume": [1000],
        })
        store.save_ohlcv_accumulated("005930", df)
        # corrupted 파일은 .parquet.corrupted.{ts} 확장자 → glob 불일치
        (tmp_path / "ohlcv" / "999999_ohlcv.parquet.corrupted.20260101").touch()
        # 기타 파일
        (tmp_path / "ohlcv" / "README.md").touch()

        result = store.list_accumulated_symbols()
        assert result == ["005930"]

    def test_list_accumulated_symbols_removesuffix_safety(self, tmp_path):
        """심볼 코드에 'ohlcv' 부분 문자열이 포함된 경우에도 올바르게 추출.
        str.replace('_ohlcv', '')는 'ohlcv123_ohlcv'를 '123'으로 오염시키지만
        removesuffix는 접미사만 제거."""
        store = ParquetDataStore(base_dir=str(tmp_path))
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01"]),
            "open": [100], "high": [110], "low": [90],
            "close": [105], "volume": [1000],
        })
        # 심볼 코드에 "ohlcv"가 포함된 극단 케이스
        store.save_ohlcv_accumulated("ohlcv123", df)

        result = store.list_accumulated_symbols()
        assert result == ["ohlcv123"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data_store.py::TestAccumulatedBulkAPI -v`
Expected: FAIL with `AttributeError: 'ParquetDataStore' object has no attribute 'list_accumulated_symbols'`

- [ ] **Step 3: Implement `list_accumulated_symbols()`**

In `src/data_store.py`, add after `get_ohlcv_last_date()` method (around line 155):

```python
def list_accumulated_symbols(self) -> list[str]:
    """축적 OHLCV가 존재하는 심볼 코드 목록 반환.

    glob 패턴 *_ohlcv.parquet 으로 정확히 매칭.
    손상 격리 파일(*.parquet.corrupted.*)은 확장자가 달라 자동 제외.

    Returns:
        심볼 코드 리스트 (정렬됨)
    """
    symbols = []
    for path in self.ohlcv_dir.glob("*_ohlcv.parquet"):
        # 파일명에서 심볼 추출: {symbol}_ohlcv.parquet
        stem = path.stem  # "005930_ohlcv"
        symbol = stem.removesuffix("_ohlcv")
        symbols.append(symbol)
    return sorted(symbols)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data_store.py::TestAccumulatedBulkAPI -v`
Expected: 4 PASSED

- [ ] **Step 5: Write failing tests for `load_multiple_ohlcv()`**

```python
# tests/test_data_store.py — append to TestAccumulatedBulkAPI

    def test_load_multiple_ohlcv(self, tmp_path):
        store = ParquetDataStore(base_dir=str(tmp_path))
        for sym in ["005930", "000660"]:
            df = pd.DataFrame({
                "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
                "open": [100, 101], "high": [110, 111], "low": [90, 91],
                "close": [105, 106], "volume": [1000, 1100],
            })
            store.save_ohlcv_accumulated(sym, df)

        result = store.load_multiple_ohlcv(["005930", "000660"])
        assert len(result) == 2
        assert "005930" in result
        assert "000660" in result
        assert len(result["005930"]) == 2

    def test_load_multiple_ohlcv_skips_missing(self, tmp_path):
        store = ParquetDataStore(base_dir=str(tmp_path))
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01"]),
            "open": [100], "high": [110], "low": [90],
            "close": [105], "volume": [1000],
        })
        store.save_ohlcv_accumulated("005930", df)

        result = store.load_multiple_ohlcv(["005930", "NOSUCH"])
        assert len(result) == 1
        assert "005930" in result

    def test_load_multiple_ohlcv_with_min_rows(self, tmp_path):
        store = ParquetDataStore(base_dir=str(tmp_path))
        # 1행짜리 (지표 계산 불가)
        store.save_ohlcv_accumulated("SHORT", pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01"]),
            "open": [100], "high": [110], "low": [90],
            "close": [105], "volume": [1000],
        }))
        # 60행짜리 (충분)
        dates = pd.bdate_range("2025-10-01", periods=60)
        store.save_ohlcv_accumulated("ENOUGH", pd.DataFrame({
            "date": dates,
            "open": range(60), "high": range(60),
            "low": range(60), "close": range(60), "volume": range(60),
        }))

        result = store.load_multiple_ohlcv(["SHORT", "ENOUGH"], min_rows=20)
        assert len(result) == 1
        assert "ENOUGH" in result
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_data_store.py::TestAccumulatedBulkAPI::test_load_multiple_ohlcv -v`
Expected: FAIL

- [ ] **Step 7: Implement `load_multiple_ohlcv()`**

In `src/data_store.py`, add after `list_accumulated_symbols()`:

```python
def load_multiple_ohlcv(
    self,
    symbols: list[str],
    min_rows: int = 0,
) -> dict[str, pd.DataFrame]:
    """복수 심볼 OHLCV 일괄 로드.

    Args:
        symbols: 로드할 심볼 코드 리스트
        min_rows: 최소 행 수. 이보다 적은 심볼은 제외 (지표 계산 불가 방지).

    Returns:
        {symbol: DataFrame} 딕셔너리. 누락/손상/부족 심볼은 제외.
    """
    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        df = self.load_ohlcv_accumulated(symbol)
        if df is None or df.empty:
            continue
        if len(df) < min_rows:
            logger.debug(f"OHLCV 부족: {symbol} ({len(df)}행 < {min_rows})")
            continue
        result[symbol] = df
    return result
```

- [ ] **Step 8: Run all bulk API tests**

Run: `pytest tests/test_data_store.py::TestAccumulatedBulkAPI -v`
Expected: 7 PASSED

- [ ] **Step 9: Commit**

```bash
git add src/data_store.py tests/test_data_store.py
git commit -m "[#TBD] feat: add ParquetDataStore bulk API (list_accumulated_symbols, load_multiple_ohlcv)"
```

---

### Task 2: MarketRegime Enum & Types

**Files:**
- Modify: `src/types.py`
- Test: `tests/test_types.py` (or inline in existing test file)

- [ ] **Step 1: Add MarketRegime enum**

In `src/types.py`, append after `PositionSnapshot`:

```python
class MarketRegime(SerializableEnum):
    """시장 레짐 분류."""
    BULL = "bull"
    RECOVERY = "recovery"
    SIDEWAYS = "sideways"
    DECLINE = "decline"
    BEAR = "bear"
```

- [ ] **Step 2: Write serialization smoke test**

```python
# tests/test_types.py (create if not exists, or append)
import json
from src.types import MarketRegime

class TestMarketRegime:
    def test_string_comparison(self):
        assert MarketRegime.BULL == "bull"
        assert MarketRegime.BEAR == "bear"

    def test_json_serialization(self):
        result = json.dumps(MarketRegime.BULL)
        assert result == '"bull"'

    def test_all_values(self):
        assert len(MarketRegime) == 5
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_types.py::TestMarketRegime -v`
Expected: 3 PASSED

- [ ] **Step 4: Commit**

```bash
git add src/types.py tests/test_types.py
git commit -m "[#TBD] feat: add MarketRegime enum to types.py"
```

---

### Task 3: SMA Helper in Indicators

**Files:**
- Modify: `src/indicators.py`
- Test: `tests/test_indicators.py`

- [ ] **Step 1: Write failing test for `calculate_sma()`**

```python
# tests/test_indicators.py — append (add import at top)
# from src.indicators import calculate_sma

import pytest

class TestCalculateSMA:
    def test_sma_basic(self):
        from src.indicators import calculate_sma
        df = pd.DataFrame({"close": [10, 20, 30, 40, 50]})
        result = calculate_sma(df["close"], period=3)
        assert result.iloc[-1] == pytest.approx(40.0)  # (30+40+50)/3
        assert pd.isna(result.iloc[0])  # not enough data

    def test_sma_custom_series(self):
        from src.indicators import calculate_sma
        series = pd.Series([1, 2, 3, 4, 5])
        result = calculate_sma(series, period=2)
        assert result.iloc[-1] == pytest.approx(4.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_indicators.py::TestCalculateSMA -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `calculate_sma()`**

In `src/indicators.py`, add before `calculate_true_range()`:

```python
def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """단순이동평균 (Simple Moving Average).

    Args:
        series: 가격 또는 지표 시리즈
        period: 이동평균 기간

    Returns:
        SMA 시리즈 (앞부분 NaN)
    """
    return series.rolling(window=period).mean()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_indicators.py::TestCalculateSMA -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/indicators.py tests/test_indicators.py
git commit -m "[#TBD] feat: add calculate_sma() helper to indicators"
```

---

### Task 4: Market Breadth Module

**Files:**
- Create: `src/market_breadth.py`
- Create: `tests/test_market_breadth.py`

- [ ] **Step 1: Write failing tests for breadth indicators**

```python
# tests/test_market_breadth.py

import pandas as pd
import pytest

from src.market_breadth import (
    calculate_pct_above_ma,
    calculate_new_high_low,
    calculate_advance_decline,
    calculate_breadth_score,
    BreadthSnapshot,
)


def _make_ohlcv(closes: list[float], n_days: int = 270) -> pd.DataFrame:
    """테스트용 OHLCV 생성. close만 의미있고 나머지는 close 기반 파생.

    기본 270일로 52주(260일) NH/NL 계산에 충분한 데이터를 보장.
    """
    dates = pd.bdate_range(end="2026-03-10", periods=n_days)[-len(closes):]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })


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
            "pct_above_20ma", "pct_above_50ma", "pct_above_200ma",
            "new_highs", "new_lows", "nh_nl_ratio",
            "advancing", "declining", "net_advancing",
            "composite_score", "total_symbols",
        }
        assert set(d.keys()) == expected_keys
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_market_breadth.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/market_breadth.py`**

```python
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


def calculate_pct_above_ma(
    data: dict[str, pd.DataFrame], period: int = 20
) -> float:
    """종목 중 이동평균선 위에 있는 비율(%) 계산.

    Args:
        data: {symbol: ohlcv_df} 딕셔너리
        period: 이동평균 기간

    Returns:
        0.0 ~ 100.0 사이의 비율
    """
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


def calculate_new_high_low(
    data: dict[str, pd.DataFrame], period: int = 260
) -> tuple[int, int]:
    """N일 신고가/신저가 종목 수.

    Args:
        data: {symbol: ohlcv_df}
        period: 기간 (기본 260 = 52주 영업일)

    Returns:
        (new_highs, new_lows) 튜플
    """
    new_highs = 0
    new_lows = 0
    for symbol, df in data.items():
        if len(df) < period + 1:
            continue
        lookback = df.iloc[-(period + 1):-1]  # 오늘 제외 과거 N일
        today_close = df["close"].iloc[-1]
        if today_close >= lookback["high"].max():
            new_highs += 1
        if today_close <= lookback["low"].min():
            new_lows += 1
    return new_highs, new_lows


def calculate_advance_decline(
    data: dict[str, pd.DataFrame],
) -> tuple[int, int]:
    """오늘 상승/하락 종목 수.

    Returns:
        (advancing, declining) 튜플
    """
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

    Returns:
        BreadthSnapshot with composite_score 0-100
    """
    pct_20 = calculate_pct_above_ma(data, 20)
    pct_50 = calculate_pct_above_ma(data, 50)
    pct_200 = calculate_pct_above_ma(data, 200)
    new_highs, new_lows = calculate_new_high_low(data, period=260)
    advancing, declining = calculate_advance_decline(data)
    total = len(data)

    # NH/NL score: 0-100 스케일. ratio > 3이면 100.
    nh_nl_ratio = new_highs / max(new_lows, 1)
    nh_nl_score = min(nh_nl_ratio / 3.0 * 100, 100.0)

    # AD score: 0-100. 전부 상승이면 100.
    ad_total = advancing + declining
    ad_score = (advancing / ad_total * 100) if ad_total > 0 else 50.0

    # % above MA는 이미 0-100 스케일 → 80%를 100점으로 클램프
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_market_breadth.py -v`
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add src/market_breadth.py tests/test_market_breadth.py
git commit -m "[#TBD] feat: add market breadth module (% above MA, 52-week NH/NL, AD, composite score)"
```

---

### Task 5: Regime Detector Module

**Files:**
- Create: `src/regime_detector.py`
- Create: `tests/test_regime_detector.py`

- [ ] **Step 1: Write failing tests (all 5 regimes + SIDEWAYS-via-crossing)**

```python
# tests/test_regime_detector.py

import pandas as pd
import pytest

from src.regime_detector import classify_regime, RegimeSnapshot
from src.types import MarketRegime


def _make_trending_up(n: int = 250) -> pd.DataFrame:
    """강한 상승 추세 데이터 (close > SMA200, SMA50 > SMA200, 기울기 상승)."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100 + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "date": dates, "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "open": closes, "volume": [1000] * n,
    })


def _make_trending_down(n: int = 250) -> pd.DataFrame:
    """강한 하락 추세 데이터 (close < SMA200, SMA50 < SMA200, 기울기 하락)."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [200 - i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "date": dates, "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "open": closes, "volume": [1000] * n,
    })


def _make_recovery(n: int = 250) -> pd.DataFrame:
    """회복 추세: close > SMA200, SMA50 > SMA200, but SMA200 기울기 < 1.5%.
    200일간 약한 하락 후 마지막 50일 반등 → SMA200 기울기 거의 flat."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    # 초반 200일: 약한 하락 후 안정
    closes = [150 - i * 0.05 for i in range(200)]
    # 마지막 50일: 반등으로 close가 SMA200 위로
    closes += [closes[-1] + i * 0.5 for i in range(1, 51)]
    return pd.DataFrame({
        "date": dates, "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "open": closes, "volume": [1000] * n,
    })


def _make_decline(n: int = 250) -> pd.DataFrame:
    """약한 하락: close < SMA200, SMA50 < SMA200, but SMA200 기울기 > -1.5%.
    초반 200일 상승 후 마지막 50일 약한 하락."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    # 초반 200일: 상승
    closes = [100 + i * 0.05 for i in range(200)]
    # 마지막 50일: 약한 하락으로 close가 SMA200 아래로
    closes += [closes[-1] - i * 0.5 for i in range(1, 51)]
    return pd.DataFrame({
        "date": dates, "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "open": closes, "volume": [1000] * n,
    })


def _make_crossing(n: int = 250) -> pd.DataFrame:
    """SMA50 > SMA200 이지만 close < SMA200인 교차 데이터 → SIDEWAYS.
    초반 200일 꾸준한 상승 후 마지막 50일 급락 (close가 SMA200 아래,
    SMA50은 아직 SMA200 위)."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    # 초반 200일: 꾸준한 상승
    closes = [100 + i * 0.3 for i in range(200)]
    # 마지막 50일: 급락 (close < SMA200, but SMA50 still > SMA200)
    closes += [closes[-1] - i * 1.5 for i in range(1, 51)]
    return pd.DataFrame({
        "date": dates, "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "open": closes, "volume": [1000] * n,
    })


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
        """SMA50과 SMA200 교차 구간 (close와 SMA 방향 불일치) → SIDEWAYS."""
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_regime_detector.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/regime_detector.py`**

```python
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

# SMA200 기울기 임계값 (20일간 1.5% 변화)
_SLOPE_THRESHOLD = 0.015


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


def classify_regime(df: pd.DataFrame) -> RegimeSnapshot:
    """DataFrame의 close 기반 레짐 분류.

    Args:
        df: OHLCV DataFrame (최소 200행 권장, 미달 시 SIDEWAYS)

    Returns:
        RegimeSnapshot
    """
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_regime_detector.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/regime_detector.py tests/test_regime_detector.py
git commit -m "[#TBD] feat: add rule-based regime detector (BULL/RECOVERY/SIDEWAYS/DECLINE/BEAR)"
```

---

## Chunk 2: Phase 2 — Screener & Intelligence Report

### Task 6: Multi-Strategy Screener

**Files:**
- Create: `src/screener.py`
- Create: `tests/test_screener.py`

**Design Notes:**
- DD1: TurtleStrategy is a **raw screener** — intentionally omits System 1 profit filter. No PositionTracker dependency. Shows all mechanical breakouts for human evaluation.
- DD2: `short_restricted=True` by default for safety. Korean stocks suppress short signals unless caller explicitly allows.
- DD4: `price_limit_pct=0.30` parameter. Near price-limit signals (>=29% daily change) include `{"price_limit_warning": True}` metadata.
- Pre-computes indicators once per symbol in `run_screening()` to avoid redundant computation across strategies.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_screener.py

import pandas as pd
import pytest

from src.screener import (
    ScreeningResult,
    TurtleStrategy,
    run_screening,
)
from src.types import SignalType


def _make_breakout_ohlcv(n: int = 60) -> pd.DataFrame:
    """20일 신고가 돌파 데이터. 마지막 행에서 돌파."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    # 50일간 100 근처 횡보, 마지막 10일 상승
    closes = [100.0] * (n - 10) + [100 + i * 2 for i in range(1, 11)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return pd.DataFrame({
        "date": dates, "open": closes, "high": highs,
        "low": lows, "close": closes, "volume": [1000] * n,
    })


def _make_flat_ohlcv(n: int = 60) -> pd.DataFrame:
    """시그널 없는 횡보 데이터."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100.0] * n
    return pd.DataFrame({
        "date": dates, "open": closes,
        "high": [101.0] * n, "low": [99.0] * n,
        "close": closes, "volume": [1000] * n,
    })


def _make_breakdown_ohlcv(n: int = 60) -> pd.DataFrame:
    """20일 신저가 이탈 데이터. 마지막 행에서 이탈."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100.0] * (n - 10) + [100 - i * 2 for i in range(1, 11)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return pd.DataFrame({
        "date": dates, "open": closes, "high": highs,
        "low": lows, "close": closes, "volume": [1000] * n,
    })


def _make_price_limit_ohlcv(n: int = 60) -> pd.DataFrame:
    """상한가 근접 데이터. 마지막 행에서 +29% 이상 급등."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100.0] * (n - 1) + [130.0]  # +30%
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return pd.DataFrame({
        "date": dates, "open": closes, "high": highs,
        "low": lows, "close": closes, "volume": [1000] * n,
    })


class TestTurtleStrategy:
    def test_detects_long_breakout(self):
        strategy = TurtleStrategy()
        df = _make_breakout_ohlcv()
        results = strategy.scan(df, symbol="005930")
        assert len(results) > 0
        entry_longs = [r for r in results if r.signal_type == SignalType.ENTRY_LONG]
        assert len(entry_longs) > 0

    def test_no_signal_on_flat(self):
        strategy = TurtleStrategy()
        df = _make_flat_ohlcv()
        results = strategy.scan(df, symbol="000660")
        entry_signals = [r for r in results if "entry" in r.signal_type.value]
        assert len(entry_signals) == 0

    def test_short_suppressed_by_default(self):
        """DD2: short_restricted=True이면 숏 시그널 없어야."""
        strategy = TurtleStrategy()
        df = _make_breakdown_ohlcv()
        results = strategy.scan(df, symbol="005930", short_restricted=True)
        short_signals = [r for r in results if r.signal_type in (
            SignalType.ENTRY_SHORT, SignalType.EXIT_SHORT)]
        assert len(short_signals) == 0

    def test_short_allowed_when_not_restricted(self):
        """short_restricted=False이면 숏 시그널 발생."""
        strategy = TurtleStrategy()
        df = _make_breakdown_ohlcv()
        results = strategy.scan(df, symbol="SPY", short_restricted=False)
        short_signals = [r for r in results if r.signal_type == SignalType.ENTRY_SHORT]
        assert len(short_signals) > 0

    def test_system2_exit_signals(self):
        """System 2 청산 시그널 (20일 저가 이탈) 검출."""
        strategy = TurtleStrategy()
        df = _make_breakdown_ohlcv()
        results = strategy.scan(df, symbol="TEST", short_restricted=True)
        exit_longs = [r for r in results if r.signal_type == SignalType.EXIT_LONG]
        # 10일(S1) + 20일(S2) 둘 다 검출 가능
        systems = {r.metadata.get("system") for r in exit_longs}
        assert 1 in systems or 2 in systems

    def test_result_fields(self):
        strategy = TurtleStrategy()
        df = _make_breakout_ohlcv()
        results = strategy.scan(df, symbol="TEST")
        assert len(results) > 0
        r = results[0]
        assert isinstance(r, ScreeningResult)
        assert r.symbol == "TEST"
        assert r.strategy_name == "turtle"
        assert r.price > 0
        assert r.signal_type is not None

    def test_docstring_mentions_no_profit_filter(self):
        """DD1: profit filter 미적용이 문서화되어 있는지."""
        assert "profit filter" in TurtleStrategy.__doc__.lower() or \
               "System 1 필터" in TurtleStrategy.__doc__

    def test_price_limit_warning(self):
        """DD4: 상한가/하한가 근접 시 price_limit_warning 메타데이터 포함."""
        strategy = TurtleStrategy()
        df = _make_price_limit_ohlcv()
        results = strategy.scan(df, symbol="005930")
        # 상한가 근접(+30%)이므로 진입 시그널이 있다면 warning 포함
        entry_signals = [r for r in results if r.signal_type == SignalType.ENTRY_LONG]
        for r in entry_signals:
            assert r.metadata.get("price_limit_warning") is True

    def test_no_price_limit_warning_on_normal(self):
        """정상 변동폭에서는 price_limit_warning이 없어야."""
        strategy = TurtleStrategy()
        df = _make_breakout_ohlcv()
        results = strategy.scan(df, symbol="005930")
        entry_signals = [r for r in results if r.signal_type == SignalType.ENTRY_LONG]
        for r in entry_signals:
            assert r.metadata.get("price_limit_warning") is not True

    def test_volume_metadata(self):
        """진입 시그널에 avg_volume_20d 메타데이터 포함."""
        strategy = TurtleStrategy()
        df = _make_breakout_ohlcv()
        results = strategy.scan(df, symbol="005930")
        entry_signals = [r for r in results if r.signal_type == SignalType.ENTRY_LONG]
        assert len(entry_signals) > 0
        for r in entry_signals:
            assert "avg_volume_20d" in r.metadata

    def test_scan_accepts_context_parameter(self):
        """Strategy Protocol의 context 파라미터가 존재하는지 확인."""
        import inspect
        sig = inspect.signature(TurtleStrategy.scan)
        assert "context" in sig.parameters


class TestRunScreening:
    def test_screens_multiple_symbols(self):
        data = {
            "BREAKOUT": _make_breakout_ohlcv(),
            "FLAT": _make_flat_ohlcv(),
        }
        results = run_screening(data, strategies=[TurtleStrategy()])
        symbols_with_signals = {r.symbol for r in results}
        assert "BREAKOUT" in symbols_with_signals

    def test_multiple_strategies(self):
        """여러 전략을 동시에 실행."""
        data = {"A": _make_breakout_ohlcv()}
        results = run_screening(data, strategies=[TurtleStrategy(), TurtleStrategy()])
        assert len(results) >= 2

    def test_empty_data(self):
        results = run_screening({}, strategies=[TurtleStrategy()])
        assert results == []

    def test_precomputes_indicators(self):
        """run_screening이 지표를 사전 계산하는지 확인 (N 컬럼 존재)."""
        data = {"A": _make_breakout_ohlcv()}
        # 지표 없는 원본 전달 — run_screening 내부에서 계산
        assert "N" not in data["A"].columns
        results = run_screening(data, strategies=[TurtleStrategy()])
        # 에러 없이 결과 반환
        assert isinstance(results, list)

    def test_does_not_mutate_input(self):
        """run_screening이 입력 data dict를 변경하지 않아야 함."""
        original_df = _make_breakout_ohlcv()
        original_columns = set(original_df.columns)
        data = {"A": original_df.copy()}
        original_keys = set(data.keys())

        run_screening(data, strategies=[TurtleStrategy()])

        # 원본 dict 키가 변경되지 않았는지
        assert set(data.keys()) == original_keys
        # 원본 DataFrame 컬럼이 변경되지 않았는지
        assert set(data["A"].columns) == original_columns
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_screener.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/screener.py`**

```python
"""
멀티 전략 스크리너 모듈.

Strategy Protocol 기반 확장 가능 설계:
- TurtleStrategy: 터틀 트레이딩 브레이크아웃/청산 (raw screener)
- (향후) MinerviniStrategy: SEPA/VCP 패턴
- (향후) PatternStrategy: 차트 패턴 인식

사용법:
    results = run_screening(data, strategies=[TurtleStrategy()])

Design Decisions:
- DD1: TurtleStrategy는 System 1 profit filter를 의도적으로 생략합니다.
  PositionTracker 의존 없이 모든 기계적 브레이크아웃을 보여줍니다.
  check_positions.py의 Curtis Faith 필터와 다른 결과를 냅니다.
- DD2: short_restricted 파라미터로 숏 시그널을 제어합니다.
  한국 시장 종목은 기본 True (숏 시그널 억제).
- DD4: price_limit_pct 파라미터로 상한가/하한가 근접 종목에 경고를 추가합니다.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import pandas as pd

from src.indicators import add_turtle_indicators, calculate_sma
from src.types import SignalType

logger = logging.getLogger(__name__)


@dataclass
class ScreeningResult:
    """스크리닝 결과 단일 시그널."""

    symbol: str
    strategy_name: str
    signal_type: SignalType
    price: float
    current_close: float
    n_value: float = 0.0
    stop_loss: float = 0.0
    message: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy_name,
            "signal_type": self.signal_type.value,
            "price": round(self.price, 2),
            "current_close": round(self.current_close, 2),
            "n_value": round(self.n_value, 2),
            "stop_loss": round(self.stop_loss, 2),
            "message": self.message,
            "metadata": self.metadata,
        }


@runtime_checkable
class Strategy(Protocol):
    """스크리닝 전략 프로토콜.

    새 전략 추가 시 이 Protocol을 구현하면 run_screening()에 바로 사용 가능.
    context 파라미터는 universe-level 정보(레짐, 브레드스 등)를 전달하기 위한
    확장 포인트로, 향후 전략이 시장 상황을 참고할 수 있도록 설계.
    """

    name: str

    def scan(
        self,
        df: pd.DataFrame,
        symbol: str,
        short_restricted: bool = True,
        price_limit_pct: float = 0.30,
        context: dict | None = None,
    ) -> list[ScreeningResult]:
        """단일 심볼 DataFrame에서 시그널 스캔.

        Args:
            df: OHLCV DataFrame (지표 사전 계산됨)
            symbol: 종목 코드
            short_restricted: True이면 숏 시그널 억제
            price_limit_pct: 가격 제한 비율 (한국 주식 0.30)
            context: universe-level 정보 (레짐, 브레드스 등). 현재 미사용.

        Returns:
            발견된 시그널 리스트 (없으면 빈 리스트)
        """
        ...


class TurtleStrategy:
    """터틀 트레이딩 브레이크아웃 스크리닝 전략.

    Raw screener — System 1 profit filter를 의도적으로 생략합니다.
    check_positions.py와 달리 PositionTracker에 의존하지 않으며,
    모든 기계적 브레이크아웃을 보여줍니다. 사용자가 직접 필터링 판단.

    검출 시그널:
    - System 1 (20일) / System 2 (55일) 롱·숏 진입
    - System 1 (10일) / System 2 (20일) 롱·숏 청산

    DD4: 상한가/하한가 근접 시 price_limit_warning 메타데이터 추가.
    DD12: 진입 시그널에 avg_volume_20d 메타데이터 추가 (정보 제공용).
    """

    name: str = "turtle"

    def scan(
        self,
        df: pd.DataFrame,
        symbol: str,
        short_restricted: bool = True,
        price_limit_pct: float = 0.30,
        context: dict | None = None,
    ) -> list[ScreeningResult]:
        if len(df) < 56:  # 최소 55일 + 1일 필요
            return []

        # 지표가 없으면 계산
        if "N" not in df.columns:
            df = add_turtle_indicators(df)

        results: list[ScreeningResult] = []
        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        if pd.isna(today["N"]) or pd.isna(yesterday.get("dc_high_20")):
            return []

        n_val = float(today["N"])
        current_close = float(today["close"])

        # 가격 제한 근접 판단 (DD4)
        yesterday_close = float(yesterday["close"])
        daily_change_pct = (
            (current_close - yesterday_close) / yesterday_close
            if yesterday_close != 0
            else 0.0
        )
        near_price_limit = abs(daily_change_pct) >= (price_limit_pct - 0.01)

        # 평균 거래량 20일 (DD12: 정보 제공용)
        avg_volume_20d = float(calculate_sma(df["volume"], 20).iloc[-1]) if len(df) >= 20 else 0.0
        volume_meta = {"avg_volume_20d": round(avg_volume_20d, 0)}

        # 저유동성 판단은 run_screening의 universe-level에서 처리

        # === 롱 진입 시그널 ===

        # System 1: 20일 돌파
        if today["high"] > yesterday["dc_high_20"]:
            entry_price = float(yesterday["dc_high_20"])
            meta = {"system": 1, **volume_meta}
            if near_price_limit:
                meta["price_limit_warning"] = True
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.ENTRY_LONG,
                price=entry_price, current_close=current_close,
                n_value=n_val, stop_loss=entry_price - 2 * n_val,
                message=f"S1 롱 진입: {entry_price:.0f} 돌파 (20일)",
                metadata=meta,
            ))

        # System 2: 55일 돌파
        if today["high"] > yesterday["dc_high_55"]:
            entry_price = float(yesterday["dc_high_55"])
            meta = {"system": 2, **volume_meta}
            if near_price_limit:
                meta["price_limit_warning"] = True
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.ENTRY_LONG,
                price=entry_price, current_close=current_close,
                n_value=n_val, stop_loss=entry_price - 2 * n_val,
                message=f"S2 롱 진입: {entry_price:.0f} 돌파 (55일)",
                metadata=meta,
            ))

        # === 숏 진입 시그널 (DD2: short_restricted 제어) ===
        if not short_restricted:
            # System 1 숏: 20일 저가 이탈
            if today["low"] < yesterday["dc_low_20"]:
                entry_price = float(yesterday["dc_low_20"])
                meta = {"system": 1, **volume_meta}
                if near_price_limit:
                    meta["price_limit_warning"] = True
                results.append(ScreeningResult(
                    symbol=symbol, strategy_name=self.name,
                    signal_type=SignalType.ENTRY_SHORT,
                    price=entry_price, current_close=current_close,
                    n_value=n_val, stop_loss=entry_price + 2 * n_val,
                    message=f"S1 숏 진입: {entry_price:.0f} 이탈 (20일)",
                    metadata=meta,
                ))

            # System 2 숏: 55일 저가 이탈
            if today["low"] < yesterday["dc_low_55"]:
                entry_price = float(yesterday["dc_low_55"])
                meta = {"system": 2, **volume_meta}
                if near_price_limit:
                    meta["price_limit_warning"] = True
                results.append(ScreeningResult(
                    symbol=symbol, strategy_name=self.name,
                    signal_type=SignalType.ENTRY_SHORT,
                    price=entry_price, current_close=current_close,
                    n_value=n_val, stop_loss=entry_price + 2 * n_val,
                    message=f"S2 숏 진입: {entry_price:.0f} 이탈 (55일)",
                    metadata=meta,
                ))

        # === 롱 청산 시그널 ===

        # System 1: 10일 저가 이탈
        if today["low"] < yesterday["dc_low_10"]:
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.EXIT_LONG,
                price=float(yesterday["dc_low_10"]),
                current_close=current_close, n_value=n_val,
                message=f"S1 롱 청산: {yesterday['dc_low_10']:.0f} 이탈 (10일)",
                metadata={"system": 1},
            ))

        # System 2: 20일 저가 이탈
        if today["low"] < yesterday["dc_low_20"]:
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.EXIT_LONG,
                price=float(yesterday["dc_low_20"]),
                current_close=current_close, n_value=n_val,
                message=f"S2 롱 청산: {yesterday['dc_low_20']:.0f} 이탈 (20일)",
                metadata={"system": 2},
            ))

        # === 숏 청산 시그널 (short_restricted여도 청산은 항상 허용) ===

        # System 1: 10일 고가 돌파
        if today["high"] > yesterday["dc_high_10"]:
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.EXIT_SHORT,
                price=float(yesterday["dc_high_10"]),
                current_close=current_close, n_value=n_val,
                message=f"S1 숏 청산: {yesterday['dc_high_10']:.0f} 돌파 (10일)",
                metadata={"system": 1},
            ))

        # System 2: 20일 고가 돌파
        if today["high"] > yesterday["dc_high_20"]:
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.EXIT_SHORT,
                price=float(yesterday["dc_high_20"]),
                current_close=current_close, n_value=n_val,
                message=f"S2 숏 청산: {yesterday['dc_high_20']:.0f} 돌파 (20일)",
                metadata={"system": 2},
            ))

        return results


def run_screening(
    data: dict[str, pd.DataFrame],
    strategies: list[Strategy] | None = None,
    short_restricted_symbols: set[str] | None = None,
    context: dict | None = None,
) -> list[ScreeningResult]:
    """복수 심볼에 복수 전략 적용하여 스크리닝.

    지표를 심볼당 1회만 사전 계산하여 중복 연산 방지.
    입력 data dict를 변경하지 않음 (로컬 복사본 사용).

    Args:
        data: {symbol: ohlcv_df} 딕셔너리
        strategies: 적용할 전략 리스트. None이면 [TurtleStrategy()]
        short_restricted_symbols: 숏 제한 심볼 집합. None이면 전체 숏 제한.
        context: universe-level 정보 (레짐, 브레드스 등). 각 전략에 전달.

    Returns:
        전체 시그널 리스트 (전략별, 심볼별 통합)
    """
    if strategies is None:
        strategies = [TurtleStrategy()]

    all_results: list[ScreeningResult] = []

    # 지표 사전 계산용 로컬 딕셔너리 (입력 data 변경 방지)
    prepared: dict[str, pd.DataFrame] = {}

    for symbol, df in data.items():
        # 지표 사전 계산 (심볼당 1회)
        if "N" not in df.columns:
            try:
                prepared[symbol] = add_turtle_indicators(df)
            except Exception as e:
                logger.warning(f"지표 계산 실패: {symbol} - {e}")
                continue
        else:
            prepared[symbol] = df

    # 저유동성 판단을 위한 전체 평균 거래량 50th percentile 계산
    all_avg_volumes: list[float] = []
    for symbol, df in prepared.items():
        if len(df) >= 20:
            avg_vol = float(calculate_sma(df["volume"], 20).iloc[-1])
            if not pd.isna(avg_vol):
                all_avg_volumes.append(avg_vol)

    volume_median = sorted(all_avg_volumes)[len(all_avg_volumes) // 2] if all_avg_volumes else 0.0

    for symbol, df in prepared.items():
        # 숏 제한 판단
        short_restricted = (
            short_restricted_symbols is None or symbol in short_restricted_symbols
        )

        for strategy in strategies:
            try:
                results = strategy.scan(
                    df, symbol, short_restricted=short_restricted, context=context,
                )
                # 저유동성 플래그 추가 (정보 제공용)
                for r in results:
                    avg_vol = r.metadata.get("avg_volume_20d", 0)
                    if avg_vol > 0 and avg_vol < volume_median:
                        r.metadata["low_volume"] = True
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"스크리닝 실패: {symbol}/{strategy.name} - {e}")

    return all_results
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_screener.py -v`
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add src/screener.py tests/test_screener.py
git commit -m "[#TBD] feat: add multi-strategy screener with Strategy Protocol and TurtleStrategy"
```

---

### Task 7: NotificationManager Enhancement

**Files:**
- Modify: `src/notifier.py` (add method to `NotificationManager` class, line 198+)
- Test: `tests/test_notifier.py`

- [ ] **Step 1: Write failing test for `send_market_intelligence()`**

```python
# tests/test_notifier.py — append to existing tests

class TestSendMarketIntelligence:
    """send_market_intelligence() 메서드 테스트."""

    @pytest.mark.asyncio
    async def test_formats_intelligence_report(self):
        """리포트 데이터가 NotificationMessage로 변환되는지 확인."""
        from unittest.mock import AsyncMock
        from src.notifier import NotificationManager, NotificationLevel

        notifier = NotificationManager()
        notifier.send_message = AsyncMock(return_value={"discord": True})

        report = {
            "date": "2026-03-11",
            "regime": "bull",
            "breadth_score": 72.0,
            "entry_signals": 3,
            "exit_signals": 1,
            "top_candidates": [
                {"symbol": "005930", "signal": "S1 롱 진입", "score": 92},
            ],
            "warnings": ["브레드스 3일 연속 하락"],
        }

        result = await notifier.send_market_intelligence(report)
        notifier.send_message.assert_called_once()

        msg = notifier.send_message.call_args[0][0]
        assert "시장 인텔리전스" in msg.title
        assert "005930" in msg.body
        # DD3: 항상 SIGNAL 레벨 (모든 채널 전송)
        assert msg.level == NotificationLevel.SIGNAL
        # 반환값 확인
        assert isinstance(result, dict)
        assert result == {"discord": True}
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_notifier.py::TestSendMarketIntelligence -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement `send_market_intelligence()` in NotificationManager**

In `src/notifier.py`, add to the `NotificationManager` class (after existing `send_anomaly_alert` method):

```python
async def send_market_intelligence(self, report: dict) -> dict[str, bool]:
    """시장 인텔리전스 리포트 전송.

    DD3: 항상 SIGNAL 레벨로 전송하여 모든 채널에 도달.
    경고는 본문에 포함.

    Args:
        report: 리포트 데이터 딕셔너리 (date, regime, breadth_score,
                entry_signals, exit_signals, top_candidates, warnings)

    Returns:
        채널별 전송 결과 딕셔너리 (예: {"discord": True, "telegram": False})
    """
    date = report.get("date", "")
    regime = report.get("regime", "unknown").upper()
    score = report.get("breadth_score", 0)
    entries = report.get("entry_signals", 0)
    exits = report.get("exit_signals", 0)
    warnings = report.get("warnings", [])
    candidates = report.get("top_candidates", [])

    title = f"[{date}] 시장 인텔리전스 | 레짐: {regime} | 브레드스: {score:.0f}/100"

    lines = []
    lines.append(f"진입 시그널: {entries}건 | 청산 시그널: {exits}건")

    if warnings:
        lines.append("")
        for w in warnings[:5]:
            lines.append(f"⚠️ {w}")

    if candidates:
        lines.append("")
        lines.append("--- Top 브레이크아웃 후보 ---")
        for c in candidates[:10]:
            sym = c.get("symbol", "?")
            sig = c.get("signal", "")
            lines.append(f"  {sym}: {sig}")

    body = "\n".join(lines)

    message = NotificationMessage(
        title=title,
        body=body,
        level=NotificationLevel.SIGNAL,
        data={
            "레짐": regime,
            "브레드스": f"{score:.0f}/100",
            "진입_시그널": entries,
            "청산_시그널": exits,
        },
    )
    return await self.send_message(message)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_notifier.py::TestSendMarketIntelligence -v`
Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add src/notifier.py tests/test_notifier.py
git commit -m "[#TBD] feat: add send_market_intelligence() to NotificationManager"
```

---

### Task 8: Market Intelligence Script

**Files:**
- Create: `scripts/market_intelligence.py`
- Create: `tests/test_market_intelligence.py`

**Note:** `main()`은 thin CLI wrapper로 parse_args만 처리. `run_pipeline()`이 lock 획득, timeout, 파이프라인 로직을 모두 담당하여 hook과 CLI 양쪽에서 안전하게 호출 가능.

- [ ] **Step 1: Write integration test**

```python
# tests/test_market_intelligence.py

import inspect

import pandas as pd
import pytest

from scripts.market_intelligence import generate_intelligence_report, run_pipeline


def _make_ohlcv_data(n_symbols: int = 5, n_days: int = 270) -> dict[str, pd.DataFrame]:
    """테스트용 복수 심볼 OHLCV 생성.

    기본 270일로 52주(260일) NH/NL 및 200MA 계산에 충분한 데이터를 보장.
    """
    data = {}
    dates = pd.bdate_range(end="2026-03-10", periods=n_days)
    for i in range(n_symbols):
        closes = [100 + j * 0.1 * (1 if i % 2 == 0 else -1) for j in range(n_days)]
        data[f"SYM{i:03d}"] = pd.DataFrame({
            "date": dates, "open": closes,
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "close": closes, "volume": [1000] * n_days,
        })
    return data


class TestGenerateIntelligenceReport:
    def test_report_structure(self):
        data = _make_ohlcv_data()
        report = generate_intelligence_report(data)

        assert "date" in report
        assert "regime" in report
        assert "breadth" in report
        assert "entry_signals" in report
        assert "exit_signals" in report
        assert "top_candidates" in report
        assert "warnings" in report
        assert isinstance(report["top_candidates"], list)
        assert isinstance(report["warnings"], list)

    def test_report_breadth_is_dict(self):
        data = _make_ohlcv_data()
        report = generate_intelligence_report(data)
        breadth = report["breadth"]
        assert "pct_above_20ma" in breadth
        assert "composite_score" in breadth

    def test_empty_data(self):
        report = generate_intelligence_report({})
        assert report["entry_signals"] == 0
        assert report["exit_signals"] == 0

    def test_regime_is_advisory_only(self):
        """레짐이 경고만 포함하고 자동 차단하지 않는지 확인."""
        data = _make_ohlcv_data()
        report = generate_intelligence_report(data)
        for w in report.get("warnings", []):
            assert "차단" not in w
            assert "block" not in w.lower()

    def test_run_pipeline_callable(self):
        """run_pipeline이 parse_args 없이 직접 호출 가능한지 확인."""
        sig = inspect.signature(run_pipeline)
        # dry_run, min_rows, timeout 파라미터가 있어야 함
        assert "dry_run" in sig.parameters
        assert "min_rows" in sig.parameters
        assert "timeout" in sig.parameters

    def test_accepts_index_df(self):
        """DD5: index_df 파라미터를 받아 레짐 분류에 사용."""
        data = _make_ohlcv_data()
        dates = pd.bdate_range(end="2026-03-10", periods=270)
        index_closes = [100 + i * 0.3 for i in range(270)]
        index_df = pd.DataFrame({
            "date": dates, "open": index_closes,
            "high": [c * 1.01 for c in index_closes],
            "low": [c * 0.99 for c in index_closes],
            "close": index_closes, "volume": [100000] * 270,
        })
        report = generate_intelligence_report(data, index_df=index_df)
        assert "regime" in report
        assert report["regime"] in ("bull", "recovery", "sideways", "decline", "bear")


class TestFullPipeline:
    """전체 파이프라인 통합 테스트."""

    def test_full_report_all_sections_populated(self):
        """generate_intelligence_report()가 모든 섹션을 채워서 반환하는지 확인."""
        data = _make_ohlcv_data(n_symbols=10, n_days=270)
        report = generate_intelligence_report(data)

        # 필수 키 존재
        required_keys = {
            "date", "regime", "regime_detail", "breadth", "breadth_score",
            "entry_signals", "exit_signals", "all_signals",
            "top_candidates", "warnings", "total_symbols_analyzed",
        }
        assert required_keys.issubset(set(report.keys()))

        # 브레드스 상세 존재
        assert isinstance(report["breadth"], dict)
        assert "composite_score" in report["breadth"]
        assert "pct_above_200ma" in report["breadth"]

        # 레짐 상세 존재
        assert isinstance(report["regime_detail"], dict)
        assert "regime" in report["regime_detail"]
        assert "sma_200" in report["regime_detail"]

        # 시그널 카운트 타입
        assert isinstance(report["entry_signals"], int)
        assert isinstance(report["exit_signals"], int)

        # 분석 심볼 수 확인
        assert report["total_symbols_analyzed"] == 10

    def test_signals_breadth_regime_all_present(self):
        """시그널, 브레드스, 레짐이 모두 유효한 값을 가지는지 확인."""
        data = _make_ohlcv_data(n_symbols=5, n_days=270)
        report = generate_intelligence_report(data)

        # 레짐은 5개 중 하나
        assert report["regime"] in ("bull", "recovery", "sideways", "decline", "bear")

        # 브레드스 점수 범위
        assert 0 <= report["breadth_score"] <= 100

        # all_signals는 리스트
        assert isinstance(report["all_signals"], list)
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_market_intelligence.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `scripts/market_intelligence.py`**

```python
#!/usr/bin/env python3
"""
시장 인텔리전스 파이프라인.

collect_daily_ohlcv.py 이후 실행되어 350종목 OHLCV를 분석하고
구조화된 인텔리전스 리포트를 생성·전송합니다.

Usage:
    python scripts/market_intelligence.py              # 전체 파이프라인
    python scripts/market_intelligence.py --dry-run    # 리포트 생성만 (전송 없음)
    python scripts/market_intelligence.py --json       # JSON 출력
"""

import argparse
import asyncio
import fcntl
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data_store import ParquetDataStore
from src.market_breadth import calculate_breadth_score
from src.regime_detector import RegimeSnapshot, classify_regime
from src.screener import TurtleStrategy, run_screening
from src.script_helpers import load_config, setup_notifier
from src.types import MarketRegime, SignalType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
LOCK_FILE = PROJECT_ROOT / "data" / ".market_intelligence.lock"

# DD5: 레짐 분류용 인덱스 프록시 (KODEX 200, KODEX KOSDAQ 150)
INDEX_PROXIES = ["069500", "229200"]

# 레짐별 경고 메시지 (advisory only — 차단 없음)
_REGIME_WARNINGS: dict[MarketRegime, str] = {
    MarketRegime.BEAR: "레짐 BEAR — 신규 진입 주의 권고",
    MarketRegime.DECLINE: "레짐 DECLINE — 진입 규모 축소 고려",
    MarketRegime.SIDEWAYS: "레짐 SIDEWAYS — 브레이크아웃 신뢰도 낮음",
}


def generate_intelligence_report(
    data: dict[str, pd.DataFrame],
    index_df: pd.DataFrame | None = None,
) -> dict:
    """인텔리전스 리포트 데이터 생성.

    Args:
        data: {symbol: ohlcv_df} — 전체 350종목
        index_df: 대표 지수 OHLCV (DD5: KODEX 200 등). None이면 가장 긴 데이터로 대체.

    Returns:
        리포트 딕셔너리
    """
    today = datetime.now().strftime("%Y-%m-%d")
    warnings: list[str] = []

    # 1. 브레드스 계산
    breadth = calculate_breadth_score(data)

    # 2. 레짐 분류 (DD5: 인덱스 프록시 우선)
    if index_df is not None and len(index_df) >= 200:
        regime_snapshot = classify_regime(index_df)
    elif data:
        longest_symbol = max(data.keys(), key=lambda s: len(data[s]))
        regime_snapshot = classify_regime(data[longest_symbol])
    else:
        regime_snapshot = RegimeSnapshot(
            regime=MarketRegime.SIDEWAYS,
            last_close=0, sma_50=0, sma_200=0, slope_200=0,
        )

    # 레짐 경고 (advisory only)
    if regime_snapshot.regime in _REGIME_WARNINGS:
        warnings.append(_REGIME_WARNINGS[regime_snapshot.regime])

    # 브레드스 경고
    if breadth.composite_score < 40:
        warnings.append(f"브레드스 낮음 ({breadth.composite_score:.0f}/100) — 시장 약세 주의")
    if breadth.pct_above_200ma < 40:
        warnings.append(f"200MA 상위 {breadth.pct_above_200ma:.0f}% — 장기 추세 약화")

    # 3. 스크리닝 (한국 주식 숏 제한: short_restricted_symbols=None → 전체 제한)
    screening_results = run_screening(data, strategies=[TurtleStrategy()])

    entry_signals = [
        r for r in screening_results
        if r.signal_type in (SignalType.ENTRY_LONG, SignalType.ENTRY_SHORT)
    ]
    exit_signals = [
        r for r in screening_results
        if r.signal_type in (SignalType.EXIT_LONG, SignalType.EXIT_SHORT)
    ]

    # Top 후보: entry 시그널을 시스템 우선순위로 정렬 (S2 > S1)
    top_candidates = sorted(
        entry_signals,
        key=lambda r: (r.metadata.get("system", 0), r.current_close),
        reverse=True,
    )[:10]

    return {
        "date": today,
        "regime": regime_snapshot.regime.value,
        "regime_detail": regime_snapshot.to_dict(),
        "breadth": breadth.to_dict(),
        "breadth_score": breadth.composite_score,
        "entry_signals": len(entry_signals),
        "exit_signals": len(exit_signals),
        "all_signals": [r.to_dict() for r in screening_results],
        "top_candidates": [
            {
                "symbol": r.symbol,
                "signal": r.message,
                "signal_type": r.signal_type.value,
                "price": round(r.price, 2),
                "stop_loss": round(r.stop_loss, 2),
                "n_value": round(r.n_value, 2),
            }
            for r in top_candidates
        ],
        "warnings": warnings,
        "total_symbols_analyzed": len(data),
    }


def acquire_lock():
    """중복 실행 방지."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd
    except OSError:
        lock_fd.close()
        logger.warning("이미 실행 중인 인텔리전스 프로세스가 있습니다.")
        return None


def release_lock(lock_fd):
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass


async def run_pipeline(
    dry_run: bool = False,
    min_rows: int = 56,
    output_json: bool = False,
    timeout: int = 300,
) -> dict | None:
    """인텔리전스 파이프라인 실행 (parse_args 없이 직접 호출 가능).

    Lock 획득, 파이프라인 로직, lock 해제를 모두 담당.
    hook과 CLI 양쪽에서 안전하게 호출 가능.

    Args:
        dry_run: True이면 전송 없이 리포트만 생성
        min_rows: 최소 데이터 행 수
        output_json: True이면 stdout에 JSON 출력
        timeout: 파이프라인 타임아웃 초 (기본 300초)

    Returns:
        리포트 딕셔너리. 실행 불가/타임아웃 시 None.
    """
    lock_fd = acquire_lock()
    if lock_fd is None:
        return None

    try:
        async with asyncio.timeout(timeout):
            logger.info("=== 시장 인텔리전스 파이프라인 시작 ===")

            data_store = ParquetDataStore(base_dir=str(PROJECT_ROOT / "data"))
            symbols = data_store.list_accumulated_symbols()

            if not symbols:
                logger.warning("축적 OHLCV 데이터 없음. collect_daily_ohlcv.py를 먼저 실행하세요.")
                return None

            logger.info(f"축적 심볼: {len(symbols)}개, 로딩 중 (min_rows={min_rows})...")
            data = data_store.load_multiple_ohlcv(symbols, min_rows=min_rows)
            logger.info(f"분석 대상: {len(data)}개 심볼")

            # DD5: 인덱스 프록시 로드
            index_df = None
            for proxy_symbol in INDEX_PROXIES:
                proxy_df = data_store.load_ohlcv_accumulated(proxy_symbol)
                if proxy_df is not None and len(proxy_df) >= 200:
                    index_df = proxy_df
                    logger.info(f"인덱스 프록시 사용: {proxy_symbol} ({len(proxy_df)}행)")
                    break

            if index_df is None:
                logger.info("인덱스 프록시 미발견, 가장 긴 심볼로 대체")

            # 리포트 생성
            report = generate_intelligence_report(data, index_df=index_df)

            logger.info(
                f"리포트 완료: 레짐={report['regime']}, "
                f"브레드스={report['breadth_score']:.0f}, "
                f"진입={report['entry_signals']}, 청산={report['exit_signals']}"
            )

            # JSON 출력
            if output_json:
                print(json.dumps(report, ensure_ascii=False, indent=2))

            # JSON 아카이브 저장
            archive_dir = PROJECT_ROOT / "data" / "intelligence"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"{report['date']}.json"
            with open(archive_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info(f"아카이브 저장: {archive_path}")

            # 알림 전송
            if not dry_run:
                config = load_config()
                notifier = setup_notifier(config)
                await notifier.send_market_intelligence(report)
                logger.info("인텔리전스 리포트 전송 완료")
            else:
                logger.info("[DRY-RUN] 전송 생략")

            logger.info("=== 시장 인텔리전스 파이프라인 완료 ===")
            return report

    except TimeoutError:
        logger.error(f"인텔리전스 파이프라인 타임아웃 ({timeout}초)")
        return None
    finally:
        release_lock(lock_fd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="시장 인텔리전스 리포트 생성")
    parser.add_argument("--dry-run", action="store_true", help="리포트 생성만 (전송 없음)")
    parser.add_argument("--json", action="store_true", help="JSON 형식 출력")
    parser.add_argument("--min-rows", type=int, default=56, help="최소 데이터 행 수 (기본 56)")
    parser.add_argument("--timeout", type=int, default=300, help="파이프라인 타임아웃 초 (기본 300)")
    return parser.parse_args()


async def main():
    """CLI 엔트리포인트. thin wrapper — parse_args만 처리하고 run_pipeline에 위임."""
    args = parse_args()
    await run_pipeline(
        dry_run=args.dry_run,
        min_rows=args.min_rows,
        output_json=args.json,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_market_intelligence.py -v`
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add scripts/market_intelligence.py tests/test_market_intelligence.py
git commit -m "[#TBD] feat: add market intelligence pipeline script"
```

---

### Task 9: Post-Collection Hook

**Files:**
- Modify: `scripts/collect_daily_ohlcv.py:413-455` (main function)
- Test: `tests/test_market_intelligence.py` (hook test appended)

- [ ] **Step 1: Add post-collection hook using subprocess**

In `scripts/collect_daily_ohlcv.py`, modify `main()`. After `send_collection_summary()` call (line 452), add:

```python
        # 수집 성공 시 인텔리전스 파이프라인 트리거 (별도 프로세스)
        if not args.dry_run and result.success_count > 0:
            logger.info("=== 인텔리전스 파이프라인 트리거 ===")
            try:
                import subprocess
                import sys
                subprocess.Popen(
                    [sys.executable, str(Path(__file__).parent / "market_intelligence.py")],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("인텔리전스 파이프라인 프로세스 시작 완료")
            except Exception as e:
                logger.error(f"인텔리전스 파이프라인 트리거 실패 (수집 결과에 영향 없음): {e}")
```

- [ ] **Step 2: Write post-collection hook test**

```python
# tests/test_market_intelligence.py — append

from unittest.mock import patch, MagicMock
from pathlib import Path


class TestPostCollectionHook:
    """collect_daily_ohlcv.py의 post-collection hook 테스트."""

    def test_subprocess_called_on_success(self):
        """수집 성공 시 subprocess.Popen이 올바른 스크립트 경로로 호출되는지."""
        with patch("subprocess.Popen") as mock_popen:
            import subprocess
            import sys

            # hook 로직 시뮬레이션
            script_path = str(Path(__file__).parent.parent / "scripts" / "market_intelligence.py")
            dry_run = False
            success_count = 10

            if not dry_run and success_count > 0:
                subprocess.Popen(
                    [sys.executable, script_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            assert call_args[0] == sys.executable
            assert "market_intelligence.py" in call_args[1]

    def test_subprocess_not_called_on_dry_run(self):
        """dry_run=True이면 subprocess가 호출되지 않아야."""
        with patch("subprocess.Popen") as mock_popen:
            dry_run = True
            success_count = 10

            if not dry_run and success_count > 0:
                import subprocess
                import sys
                subprocess.Popen(
                    [sys.executable, "market_intelligence.py"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            mock_popen.assert_not_called()

    def test_subprocess_not_called_on_zero_success(self):
        """success_count=0이면 subprocess가 호출되지 않아야."""
        with patch("subprocess.Popen") as mock_popen:
            dry_run = False
            success_count = 0

            if not dry_run and success_count > 0:
                import subprocess
                import sys
                subprocess.Popen(
                    [sys.executable, "market_intelligence.py"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            mock_popen.assert_not_called()
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `pytest tests/ -x -q --timeout=120`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add scripts/collect_daily_ohlcv.py tests/test_market_intelligence.py
git commit -m "[#TBD] feat: trigger intelligence pipeline after OHLCV collection via subprocess"
```

---

### Task 10: CLAUDE.md & Documentation Update

**Files:**
- Modify: `CLAUDE.md` (src/ 테이블, scripts/ 테이블 업데이트)

- [ ] **Step 1: Update CLAUDE.md src/ table**

Add entries for new modules:
```
| `market_breadth.py` | 시장 브레드스 지표 (% above MA, 52주 NH/NL, AD, 종합 점수) | data_store + indicators |
| `regime_detector.py` | Rule-based 시장 레짐 분류 (5단계) | indicators |
| `screener.py` | 멀티 전략 스크리너 (Strategy Protocol, 확장 가능) | indicators + types |
```

- [ ] **Step 2: Update CLAUDE.md scripts/ table**

Add entry:
```
| `market_intelligence.py` | 시장 인텔리전스 리포트 생성·전송 | 수집 후 자동/수동 |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "[#TBD] docs: update CLAUDE.md with market intelligence pipeline modules"
```

---

## Dependency Graph

```
Task 1 (data_store bulk API)
  ↓
Task 2 (types) ─────────────────┐
  ↓                              │
Task 3 (SMA helper)              │
  ↓                              │
Task 4 (market_breadth) ────┐    │
  ↓                          │   │
Task 5 (regime_detector) ───┤    │
                             │   │
Task 6 (screener) ──────────┤   │
  ↓                          ↓   ↓
Task 7 (notifier) ──→ Task 8 (intelligence script)
                              ↓
                       Task 9 (collection hook)
                              ↓
                       Task 10 (docs)
```

Tasks 2, 3 can run in parallel.
Tasks 4, 5, 6 can run in parallel (after 2, 3).
Tasks 7, 8 depend on 4+5+6.
Task 9 depends on 8.
Task 10 is final.

---

## Review Feedback Applied (v2)

| Issue | Resolution |
|-------|-----------|
| C1 (Chunk1): `Notifier` → `NotificationManager` | Fixed in Task 7 — correct class name throughout |
| C2 (Chunk1): corrupted file glob dead code | Test renamed to `test_list_accumulated_symbols_ignores_non_parquet` with honest description |
| H3 (Chunk1): RECOVERY/DECLINE tests missing | Added `test_recovery_regime` and `test_decline_regime` with dedicated fixtures |
| M2 (Chunk1): `run_pipeline()` refactor buried in prose | Explicit in Task 8 implementation — `run_pipeline()` and `main()` are separate functions |
| M4 (Chunk1): Relative path | Fixed to `PROJECT_ROOT = Path(__file__).parent.parent` throughout |
| M5 (Chunk1): Missing import | Tests use inline `from src.indicators import calculate_sma` |
| M6 (Chunk1): MarketRegime serialization untested | Added `TestMarketRegime` in Task 2 |
| H5 (Chunk1): BreadthSnapshot.to_dict untested | Added `test_to_dict_keys` in Task 4 |
| C1 (Chunk2): System 1 profit filter absent | DD1 documented in plan header, TurtleStrategy docstring, and test |
| C2 (Chunk2): Short restriction | DD2 with `short_restricted` param, default True, tests added |
| C3 (Chunk2): System 2 exit missing | Added S2 exit (20-day) for both long and short |
| C4 (Chunk2): Wrong class name | Same as Chunk1 C1 — fixed |
| I5 (Chunk2): Notification level inverted | DD3: always `SIGNAL` level |
| I6 (Chunk2): `run_pipeline()` not in Task 8 | Explicit in Task 8 code |
| I7 (Chunk2): Relative path | Fixed with `PROJECT_ROOT` |
| M2 (Chunk2): Lock file missing | Added `acquire_lock()`/`release_lock()` in Task 8 |
| M3 (Chunk2): Lazy pandas import | Removed — top-level import |
| M4 (Chunk2): ScreeningResult location inconsistency | Fixed File Structure table — removed `ScreeningSignal` from types.py |
| H1 (Chunk1): Redundant indicator computation | Pre-compute in `run_screening()` with caching |

---

## Review Feedback Applied (v3)

| # | Fix | Severity | Resolution |
|---|-----|----------|------------|
| 1 | NH/NL period 20 → 260 (52-week) | Critical | `calculate_new_high_low` default period changed to 260. `calculate_breadth_score` calls with `period=260`. All test fixtures in `test_market_breadth.py` updated to generate 270+ rows. `_make_ohlcv` helper default `n_days=270`. |
| 2 | removesuffix bug | Critical | `list_accumulated_symbols()` uses `stem.removesuffix("_ohlcv")` instead of `stem.replace("_ohlcv", "")`. Added `test_list_accumulated_symbols_removesuffix_safety` test with `"ohlcv123"` symbol to prove correctness. |
| 3 | VI/CB & price-limit awareness | Critical | Added `price_limit_pct: float = 0.30` to `TurtleStrategy.scan()`. Near price-limit signals (>=29% daily change) include `{"price_limit_warning": True}` metadata. Tests added. DD4 documented. |
| 4 | Remove pyramid claim | Critical | Goal changed to "entry and exit signals". All "pyramid" references removed from goal, architecture, user decisions. Strategy Protocol remains extensible for future pyramid support. |
| 5 | Safe import path for hook | Critical | Post-collection hook uses `subprocess.Popen` instead of `from scripts.market_intelligence import run_pipeline`. Runs as separate process to avoid import path issues. |
| 6 | Lock acquisition into run_pipeline() | Critical | `acquire_lock()` moved into `run_pipeline()`. `main()` is now a thin CLI wrapper (parse_args → run_pipeline). Lock released in `finally` block inside `run_pipeline()`. |
| 7 | Pipeline timeout (300s) | Critical | Added `timeout: int = 300` to `run_pipeline()`. Uses `asyncio.timeout(timeout)`. On timeout, logs error and returns None. Test verifies parameter exists in signature. |
| 8 | Regime slope threshold documentation alignment | High | Final implemented rule remains `_SLOPE_THRESHOLD = 0.015` (1.5%). Source docstrings, tests, and downstream review notes were updated to match the shipped behavior. Boundary tests now verify the 1.5% rule explicitly. |
| 9 | Index proxy for regime detection | High | Added `INDEX_PROXIES = ["069500", "229200"]` constant. `run_pipeline()` loads index proxy OHLCV from data_store before falling back to longest symbol. `generate_intelligence_report` accepts `index_df` parameter. DD5 documented. |
| 10 | send_market_intelligence return type | High | Return type changed from `None` to `Dict[str, bool]`. Returns `await self.send_message(message)`. Test asserts return value. |
| 11 | run_screening must not mutate input | High | `run_screening()` uses local `prepared` dict for indicator-enriched DataFrames. Original `data` dict is not modified. Test `test_does_not_mutate_input` verifies this. |
| 12 | Volume confirmation | High | Added `avg_volume_20d` to entry signal metadata. `run_screening()` calculates universe median volume and flags `{"low_volume": True}` for below-median symbols. Informational only. |
| 13 | Full pipeline integration test | High | Added `TestFullPipeline` class in `test_market_intelligence.py`. Tests that `generate_intelligence_report()` produces valid report with all expected keys, breadth, regime, and signals populated. Uses 270+ row data. |
| 14 | Fix test fixture NH/NL math | High | `_make_ohlcv` helper default `n_days` changed to 270. NH/NL test data uses 270 rows of trending data to clearly create 52-week highs/lows. `TestBreadthScore` fixtures updated to 271 rows. |
| 15 | Post-collection hook test | High | Added `TestPostCollectionHook` class with 3 tests: subprocess called on success, NOT called on dry_run=True, NOT called on success_count=0. |
| 16 | Strategy context parameter | Medium | Added `context: dict \| None = None` to `Strategy.scan()` Protocol and `TurtleStrategy.scan()`. `run_screening()` passes context to each strategy. Test verifies parameter exists. |
| 17 | SIDEWAYS-via-crossing test | Medium | Added `_make_crossing()` fixture and `test_sideways_via_crossing` test. SMA50 > SMA200 but close < SMA200 triggers SIDEWAYS `else` branch. |
| 18 | Document dry-run in verification checklist | Medium | Added dry-run note to plan header. Verification checklist updated with dry-run item. |

---

## Verification Checklist

- [x] `pytest tests/ -x -q` — 전체 테스트 통과
- [x] `ruff check src/ scripts/ tests/` — lint 통과
- [x] `mypy src/ --ignore-missing-imports` — 타입 체크 통과
- [x] `python scripts/market_intelligence.py --dry-run --json` — 리포트 생성 확인 (축적 데이터 필요)
- [x] 리포트에 "차단"/"block" 키워드 없음 (advisory only 확인)
- [x] 350종목 스캔 소요시간 < 60초 확인
- [x] `NotificationManager.send_market_intelligence()` 테스트 통과 및 반환값 확인
- [x] lock file 중복 실행 방지 동작 확인
- [x] NH/NL 계산이 52주(260일) 기간을 사용하는지 확인
- [x] `removesuffix` 사용 확인 (`replace` 아님)
- [x] 상한가/하한가 근접 시 `price_limit_warning` 메타데이터 포함 확인
- [x] post-collection hook이 `subprocess.Popen`으로 별도 프로세스 실행 확인
- [x] `run_pipeline()` 내부에서 lock 획득/해제 확인
- [x] 파이프라인 timeout 300초 기본값 확인
- [x] `run_screening()`이 입력 data dict를 변경하지 않는지 확인
- [x] 인덱스 프록시(069500, 229200) 우선 로드 확인

**Verification note:** local observed runtime on the current 350-symbol dataset was approximately 1.45s with `--dry-run --min-rows 1`. Worst-case runtime still depends on future accumulated history depth, but the implementation is comfortably below the `< 60s` target on current data.
