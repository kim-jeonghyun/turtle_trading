# Backtester Equity Tracking Fix — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 equity tracking bugs in `src/backtester.py` that cause MDD > 100% and incorrect position sizing.

**Architecture:** Replace `cash + unrealized_pnl` equity formula with direction-aware mark-to-market (`cash + sum(positions_value)`). For LONG: `Q * P_current`. For SHORT (collateral model): `Q * (2*P_entry - P_current)`. Update `current_equity` on every bar for correct position sizing. Fix exit commission leak. Add 5 invariant assertions to prevent regression.

**Tech Stack:** Python 3.12, pytest, pandas, numpy

**Issue:** #216

**Branch:** `bugfix/issue-216-equity-tracking`

**Analysis:** `.omc/scientist/reports/2026-03-13_equity_tracking_bug_analysis.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/backtester.py` | Modify | Fix `_record_equity()`, `_close_position()` |
| `tests/test_backtester.py` | Modify | Add invariant tests, update existing test |
| `tests/conftest.py` | Check | Ensure `trending_up_df` fixture exists |

**No new files created.** All changes are within existing files.

---

## Chunk 1: Invariant Tests (TDD — Red Phase)

### Task 1: Write equity invariant tests

**Files:**
- Modify: `tests/test_backtester.py`

These tests codify the 5 mathematical invariants that any correct backtester must satisfy. They will FAIL against the current buggy code, proving the bugs exist.

- [ ] **Step 1.1: Write `TestEquityInvariants` class with 5 invariant tests**

Add at the end of `tests/test_backtester.py`:

```python
class TestEquityInvariants:
    """에쿼티 추적 불변 조건 (Issue #216)

    모든 정상 백테스터는 다음을 만족해야 한다:
    I1: equity >= 0 (long-only, 무레버리지)
    I2: 0 <= MDD <= 1.0
    I3: 전 포지션 청산 후 equity == cash == initial_capital + realized_pnl
    I4: account.current_equity == equity_curve의 마지막 값
    I5: equity peak는 단조증가
    """

    @staticmethod
    def _make_volatile_data() -> dict[str, pd.DataFrame]:
        """큰 변동이 있는 단일 종목 데이터 (진입→하락→청산 유도)"""
        np.random.seed(42)
        dates = pd.date_range(start="2024-01-01", periods=120, freq="B")
        prices = []
        p = 100.0
        for i in range(120):
            if i < 30:
                p += np.random.normal(0, 0.3)  # 횡보
            elif i < 60:
                p += abs(np.random.normal(1.0, 0.3))  # 상승 (돌파 유도)
            elif i < 90:
                p -= abs(np.random.normal(1.5, 0.5))  # 급락 (스톱로스 유도)
            else:
                p += np.random.normal(0, 0.3)  # 횡보
            p = max(p, 1.0)  # 가격 양수 보장
            prices.append(p)

        df = pd.DataFrame({
            "date": dates,
            "open": prices,
            "high": [p + abs(np.random.normal(0.5, 0.2)) for p in prices],
            "low": [p - abs(np.random.normal(0.5, 0.2)) for p in prices],
            "close": prices,
            "volume": [1_000_000] * 120,
        })
        return {"TEST": df}

    @staticmethod
    def _make_multi_symbol_data() -> dict[str, pd.DataFrame]:
        """3종목 데이터 — 동시 포지션으로 에쿼티 부하 극대화"""
        np.random.seed(99)
        dates = pd.date_range(start="2024-01-01", periods=120, freq="B")
        data = {}
        for sym_idx, sym in enumerate(["AAA", "BBB", "CCC"]):
            base = 50.0 + sym_idx * 20
            prices = []
            p = base
            for i in range(120):
                if i < 30:
                    p += np.random.normal(0, 0.2)
                elif i < 60:
                    p += abs(np.random.normal(0.8, 0.2))
                elif i < 90:
                    p -= abs(np.random.normal(1.2, 0.4))
                else:
                    p += np.random.normal(0, 0.2)
                p = max(p, 1.0)
                prices.append(p)
            df = pd.DataFrame({
                "date": dates,
                "open": prices,
                "high": [p + abs(np.random.normal(0.4, 0.1)) for p in prices],
                "low": [p - abs(np.random.normal(0.4, 0.1)) for p in prices],
                "close": prices,
                "volume": [1_000_000] * 120,
            })
            data[sym] = df
        return data

    def test_i1_equity_non_negative(self):
        """I1: Long-only 무레버리지에서 equity는 항상 >= 0"""
        config = BacktestConfig(
            initial_capital=100_000.0, system=2, use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        assert not result.equity_curve.empty, "equity curve가 비어있음"
        neg = result.equity_curve[result.equity_curve["equity"] < 0]
        assert neg.empty, (
            f"I1 위반: {len(neg)}개 시점에서 음수 equity 발생. "
            f"최솟값: {result.equity_curve['equity'].min():.2f}"
        )

    def test_i2_mdd_bounded(self):
        """I2: 0 <= MDD <= 1.0"""
        config = BacktestConfig(
            initial_capital=100_000.0, system=2, use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        assert 0 <= result.max_drawdown <= 1.0, (
            f"I2 위반: MDD = {result.max_drawdown:.4f} (범위 초과)"
        )

    def test_i3_cash_reconciliation_when_flat(self):
        """I3: 모든 포지션 청산 후 equity == cash == initial + realized_pnl"""
        config = BacktestConfig(
            initial_capital=100_000.0, system=2, use_filter=False,
            commission_pct=0.0,  # 수수료 0으로 순수 cash reconciliation 검증
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        # Hard preconditions: 데이터가 실제 거래를 유발해야 함
        assert len(bt.trades) > 0, "I3 전제조건 불충족: 거래가 발생하지 않음"
        assert len(bt.pyramid_manager.positions) == 0, (
            "I3 전제조건 불충족: 열린 포지션 존재 — 모든 포지션이 청산되어야 함"
        )

        expected = config.initial_capital + bt.account.realized_pnl
        actual_cash = bt.account.cash
        assert abs(actual_cash - expected) < 0.01, (
            f"I3 위반: cash={actual_cash:.2f}, "
            f"expected={expected:.2f} (initial + realized_pnl)"
        )

    def test_i4_current_equity_consistent(self):
        """I4: account.current_equity == equity_curve 마지막 값"""
        config = BacktestConfig(
            initial_capital=100_000.0, system=2, use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        if not result.equity_curve.empty:
            curve_last = result.equity_curve["equity"].iloc[-1]
            assert abs(bt.account.current_equity - curve_last) < 0.01, (
                f"I4 위반: current_equity={bt.account.current_equity:.2f}, "
                f"curve_last={curve_last:.2f}"
            )

    def test_i5_peak_monotonic(self):
        """I5: equity peak는 단조증가"""
        config = BacktestConfig(
            initial_capital=100_000.0, system=2, use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_volatile_data())

        assert not result.equity_curve.empty, "equity curve가 비어있음"
        assert "peak" in result.equity_curve.columns, "peak 컬럼이 없음"
        peaks = result.equity_curve["peak"]
        diffs = peaks.diff().dropna()
        violations = diffs[diffs < -0.001]
        assert violations.empty, (
            f"I5 위반: peak가 {len(violations)}개 시점에서 감소"
        )

    def test_multi_symbol_equity_non_negative(self):
        """I1 확장: 다중 종목에서도 equity >= 0"""
        config = BacktestConfig(
            initial_capital=100_000.0, system=2, use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_multi_symbol_data())

        assert not result.equity_curve.empty
        neg = result.equity_curve[result.equity_curve["equity"] < 0]
        assert neg.empty, (
            f"I1 위반 (다중 종목): {len(neg)}개 시점에서 음수. "
            f"최솟값: {result.equity_curve['equity'].min():.2f}"
        )

    def test_multi_symbol_mdd_bounded(self):
        """I2 확장: 다중 종목에서도 MDD <= 1.0"""
        config = BacktestConfig(
            initial_capital=100_000.0, system=2, use_filter=False,
        )
        bt = TurtleBacktester(config)
        result = bt.run(self._make_multi_symbol_data())

        assert 0 <= result.max_drawdown <= 1.0, (
            f"I2 위반 (다중 종목): MDD = {result.max_drawdown:.4f}"
        )
```

- [ ] **Step 1.2: Run invariant tests to confirm they FAIL**

Run: `pytest tests/test_backtester.py::TestEquityInvariants -v`
Expected: At least I1, I2, I4 should FAIL (proving bugs B1, B2 exist)

- [ ] **Step 1.3: Commit red tests**

```bash
git add tests/test_backtester.py
git commit -m "[#216] test: 에쿼티 불변 조건 테스트 추가 (red phase)

I1: equity >= 0, I2: MDD bounded, I3: cash reconciliation,
I4: current_equity consistency, I5: peak monotonic"
```

---

## Chunk 2: Unit Tests for Specific Bugs

### Task 2: Write targeted bug reproduction tests

**Files:**
- Modify: `tests/test_backtester.py`

These tests target each specific bug with controlled inputs, making the root cause unambiguous.

- [ ] **Step 2.1: Write `TestEquityFormula` — direct `_record_equity` test**

Add after `TestEquityInvariants`:

```python
class TestEquityFormula:
    """B1 수정 검증: _record_equity()가 market value를 사용하는지 확인"""

    def test_equity_at_entry_equals_initial_minus_commission(self):
        """진입 직후 equity = initial_capital - commission (not initial - notional)"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
            commission_pct=0.001,
        )
        bt = TurtleBacktester(config)

        # 수동으로 포지션 오픈: price=100, qty는 calculate_unit_size로 결정
        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)

        position = bt.pyramid_manager.get_position("TEST")
        assert position is not None, "포지션이 생성되지 않음"
        qty = position.total_units

        # _record_equity 호출을 위한 데이터 구성
        mock_data = {
            "TEST": pd.DataFrame({
                "date": [pd.Timestamp("2025-01-01")],
                "close": [100.0],  # 진입가와 동일
            })
        }
        bt._record_equity(pd.Timestamp("2025-01-01"), mock_data)

        recorded_equity = bt.equity_history[-1]["equity"]
        # 정확한 equity = cash + market_value
        # cash = 100000 - qty * 100 * 1.001
        # market_value = qty * 100
        # equity = 100000 - qty * 100 * 0.001 = 100000 - commission
        expected = 100_000.0 - qty * 100.0 * config.commission_pct
        assert abs(recorded_equity - expected) < 1.0, (
            f"진입 직후 equity={recorded_equity:.2f}, expected={expected:.2f}. "
            f"차이={recorded_equity - expected:.2f} (B1 버그 시 ~{qty * 100:.0f} 부족)"
        )

    def test_equity_tracks_price_movement(self):
        """가격 상승 시 equity가 정확히 반영"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            system=2,
            use_filter=False,
            commission_pct=0.0,  # 수수료 제거로 순수 equity 공식 검증
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        position = bt.pyramid_manager.get_position("TEST")
        qty = position.total_units

        # 가격 110으로 상승
        mock_data = {
            "TEST": pd.DataFrame({
                "date": [pd.Timestamp("2025-01-02")],
                "close": [110.0],
            })
        }
        bt._record_equity(pd.Timestamp("2025-01-02"), mock_data)

        recorded = bt.equity_history[-1]["equity"]
        # equity = cash + qty * 110
        # cash = 100000 - qty * 100 (commission=0)
        # equity = 100000 + qty * 10
        expected = 100_000.0 + qty * 10.0
        assert abs(recorded - expected) < 0.01, (
            f"equity={recorded:.2f}, expected={expected:.2f}"
        )


class TestExitCommission:
    """B3 수정 검증: 청산 시 수수료가 cash에서 차감되는지 확인"""

    def test_exit_commission_deducted_from_cash(self):
        """청산 시 cash += qty * price * (1 - commission)"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.001,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        position = bt.pyramid_manager.get_position("TEST")
        qty = position.total_units
        cash_before_close = bt.account.cash

        bt._close_position("TEST", pd.Timestamp("2025-01-10"), 110.0, "EXIT_LONG")

        expected_cash = cash_before_close + qty * 110.0 * (1 - config.commission_pct)
        assert abs(bt.account.cash - expected_cash) < 0.01, (
            f"cash={bt.account.cash:.2f}, expected={expected_cash:.2f}. "
            f"차이={bt.account.cash - expected_cash:.2f} (B3: 청산 수수료 미차감)"
        )


class TestRoundTripCommission:
    """B1+B3 통합 검증: 진입→청산 왕복 수수료가 정확히 차감되는지 확인"""

    def test_round_trip_cash_equals_initial_minus_commissions(self):
        """가격 변동 없이 왕복 시 cash = initial - entry_commission - exit_commission"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.001,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        position = bt.pyramid_manager.get_position("TEST")
        qty = position.total_units

        bt._close_position("TEST", pd.Timestamp("2025-01-10"), 100.0, "EXIT_LONG")

        # 가격 변동 0 → 순수 수수료만 차감
        entry_comm = qty * 100.0 * config.commission_pct
        exit_comm = qty * 100.0 * config.commission_pct
        expected = 100_000.0 - entry_comm - exit_comm
        assert abs(bt.account.cash - expected) < 0.01, (
            f"왕복 수수료 불일치: cash={bt.account.cash:.2f}, expected={expected:.2f}"
        )

    def test_short_round_trip_equity(self):
        """SHORT 왕복: equity가 정확하게 추적되는지 검증"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.0,  # 수수료 제거로 순수 공식 검증
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.SHORT)
        position = bt.pyramid_manager.get_position("TEST")
        assert position is not None, "SHORT 포지션 미생성"
        qty = position.total_units

        # 가격 하락 → 숏 수익
        mock_data = {
            "TEST": pd.DataFrame({
                "date": [pd.Timestamp("2025-01-02")],
                "close": [90.0],
            })
        }
        bt._record_equity(pd.Timestamp("2025-01-02"), mock_data)

        recorded = bt.equity_history[-1]["equity"]
        # cash = 100000 - qty*100, positions_value = qty*(2*100 - 90) = qty*110
        # equity = (100000 - qty*100) + qty*110 = 100000 + qty*10
        expected = 100_000.0 + qty * 10.0
        assert abs(recorded - expected) < 0.01, (
            f"SHORT equity 오류: {recorded:.2f}, expected={expected:.2f}"
        )

        # 가격 상승 → 숏 손실
        mock_data2 = {
            "TEST": pd.DataFrame({
                "date": [pd.Timestamp("2025-01-03")],
                "close": [110.0],
            })
        }
        bt._record_equity(pd.Timestamp("2025-01-03"), mock_data2)

        recorded2 = bt.equity_history[-1]["equity"]
        # positions_value = qty*(2*100 - 110) = qty*90
        # equity = (100000 - qty*100) + qty*90 = 100000 - qty*10
        expected2 = 100_000.0 - qty * 10.0
        assert abs(recorded2 - expected2) < 0.01, (
            f"SHORT equity 오류 (상승): {recorded2:.2f}, expected={expected2:.2f}"
        )


class TestCurrentEquityUpdate:
    """B2 수정 검증: current_equity가 매 바마다 갱신되는지 확인"""

    def test_current_equity_updated_after_record(self):
        """_record_equity() 호출 후 account.current_equity가 갱신"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)

        bt._open_position("TEST", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        qty = bt.pyramid_manager.get_position("TEST").total_units

        mock_data = {
            "TEST": pd.DataFrame({
                "date": [pd.Timestamp("2025-01-02")],
                "close": [90.0],  # 10% 하락
            })
        }
        bt._record_equity(pd.Timestamp("2025-01-02"), mock_data)

        # current_equity = cash + qty * 90
        expected = bt.account.cash + qty * 90.0
        assert abs(bt.account.current_equity - expected) < 0.01, (
            f"current_equity={bt.account.current_equity:.2f}, expected={expected:.2f}. "
            f"B2 버그: initial_capital에서 변경 안 됨"
        )

    def test_position_sizing_uses_updated_equity(self):
        """손실 후 두 번째 포지션이 줄어든 equity로 사이징"""
        config = BacktestConfig(
            initial_capital=100_000.0,
            commission_pct=0.0,
        )
        bt = TurtleBacktester(config)

        # 첫 포지션: equity=100k
        bt._open_position("AAA", pd.Timestamp("2025-01-01"), 100.0, 5.0, Direction.LONG)
        qty1 = bt.pyramid_manager.get_position("AAA").total_units

        # 가격 하락 → equity 갱신
        mock_data = {
            "AAA": pd.DataFrame({
                "date": [pd.Timestamp("2025-01-02")],
                "close": [80.0],
            })
        }
        bt._record_equity(pd.Timestamp("2025-01-02"), mock_data)

        # 두 번째 포지션: 줄어든 equity로 사이징
        bt._open_position("BBB", pd.Timestamp("2025-01-02"), 50.0, 5.0, Direction.LONG)
        pos_bbb = bt.pyramid_manager.get_position("BBB")

        assert pos_bbb is not None, "BBB 포지션이 생성되지 않음 (cash 부족 가능)"
        qty2 = pos_bbb.total_units
        # 줄어든 equity → 더 작은 포지션
        # qty1 = 100000 * 0.01 / 5.0 = 200
        # qty2 = (cash + qty1*80) * 0.01 / 5.0 < 200
        assert qty2 <= qty1, (
            f"B2 버그: 손실 후에도 동일 사이즈 {qty2} >= {qty1}"
        )
```

- [ ] **Step 2.2: Run targeted tests to confirm FAIL**

Run: `pytest tests/test_backtester.py::TestEquityFormula tests/test_backtester.py::TestExitCommission tests/test_backtester.py::TestCurrentEquityUpdate -v`
Expected: FAIL (bugs not yet fixed)

- [ ] **Step 2.3: Commit red tests**

```bash
git add tests/test_backtester.py
git commit -m "[#216] test: B1/B2/B3 개별 버그 재현 테스트 추가 (red phase)"
```

---

## Chunk 3: Fix Implementation (Green Phase)

### Task 3: Fix B1 — `_record_equity()` market value formula

**Files:**
- Modify: `src/backtester.py:321-336`

- [ ] **Step 3.1: Replace `_record_equity()` body**

Replace the entire `_record_equity` method in `src/backtester.py`:

```python
def _record_equity(self, date: datetime, data: Optional[Dict[str, pd.DataFrame]] = None):
    positions_value = 0.0
    for symbol, position in self.pyramid_manager.positions.items():
        if data and symbol in data:
            df_slice = data[symbol][data[symbol]["date"] <= date]
            if not df_slice.empty:
                current_price = df_slice.iloc[-1]["close"]
                qty = position.total_units
                if position.direction == Direction.LONG:
                    positions_value += current_price * qty
                else:
                    # SHORT collateral model: value = cost_basis + unrealized_pnl
                    # = Q*P_entry + Q*(P_entry - P_current) = Q*(2*P_entry - P_current)
                    avg_entry = position.average_entry_price
                    positions_value += qty * (2 * avg_entry - current_price)

    equity = self.account.cash + positions_value
    self.account.current_equity = equity  # Fix B2
    self.equity_history.append({"date": date, "equity": equity, "cash": self.account.cash})
```

Key changes:
- LONG: `positions_value += Q * P_current` (market value)
- SHORT: `positions_value += Q * (2*P_entry - P_current)` (collateral model: entry cost + unrealized P&L)
- Adds `self.account.current_equity = equity` (fixes B2)

**Why direction matters**: At short entry, cash decreases by `Q*P_e*(1+c)` (collateral posted).
The position's "value" is the recoverable amount: `Q*P_e` (collateral) + `Q*(P_e - P_c)` (unrealized gain/loss).
When `P_c` rises, shorts lose money → position value decreases. This is algebraically `Q*(2*P_e - P_c)`.

- [ ] **Step 3.2: Run invariant + formula tests**

Run: `pytest tests/test_backtester.py::TestEquityInvariants tests/test_backtester.py::TestEquityFormula tests/test_backtester.py::TestCurrentEquityUpdate -v`
Expected: I1, I2, I4, I5 + TestEquityFormula + TestCurrentEquityUpdate should PASS

- [ ] **Step 3.3: Commit B1+B2 fix**

```bash
git add src/backtester.py
git commit -m "[#216] fix: _record_equity() mark-to-market 공식 적용 (B1+B2)

- equity = cash + sum(Q * P_current) (기존: cash + unrealized_pnl)
- account.current_equity 매 바 갱신 (기존: initial_capital 고정)"
```

### Task 4: Fix B3 — Exit commission deduction

**Files:**
- Modify: `src/backtester.py:310`

- [ ] **Step 4.1: Fix `_close_position()` cash line**

In `src/backtester.py`, replace line 310:

```python
# Before:
self.account.cash += price * total_quantity
# After:
self.account.cash += price * total_quantity * (1 - self.config.commission_pct)
```

- [ ] **Step 4.2: Run exit commission test**

Run: `pytest tests/test_backtester.py::TestExitCommission -v`
Expected: PASS

- [ ] **Step 4.3: Run I3 cash reconciliation test**

Run: `pytest tests/test_backtester.py::TestEquityInvariants::test_i3_cash_reconciliation_when_flat -v`
Expected: PASS

- [ ] **Step 4.4: Commit B3 fix**

```bash
git add src/backtester.py
git commit -m "[#216] fix: 청산 시 수수료 cash 차감 (B3)

cash += Q * P_exit * (1 - commission) (기존: Q * P_exit)"
```

---

## Chunk 4: Existing Test Compatibility + Update Bug2 Test

### Task 5: Update existing `test_bug2_equity_includes_unrealized`

**Files:**
- Modify: `tests/test_backtester.py:35-56`

The existing test name references "unrealized P&L" which is now replaced by market value. The test logic still holds (equity != cash when positions open), but the name and docstring should reflect the fix.

- [ ] **Step 5.1: Rename and update docstring**

```python
def test_equity_includes_position_market_value(self, trending_up_df):
    """equity curve에 포지션 시가(market value)가 반영되는지 검증 (B1 수정 후)"""
    config = BacktestConfig(
        initial_capital=100000.0,
        risk_percent=0.01,
        system=2,
        use_filter=False,
    )
    bt = TurtleBacktester(config)
    data = {"TEST": trending_up_df.copy()}
    result = bt.run(data)

    assert not result.equity_curve.empty

    if len(result.equity_curve) > 0:
        has_difference = (result.equity_curve["equity"] != result.equity_curve["cash"]).any()
        if result.total_trades > 0 or len(bt.pyramid_manager.positions) > 0:
            assert has_difference, "Equity should include position market value"
```

- [ ] **Step 5.2: Run all existing backtester tests**

Run: `pytest tests/test_backtester.py -v`
Expected: ALL PASS

- [ ] **Step 5.3: Run full test suite**

Run: `pytest -q`
Expected: ALL PASS (1333+ tests)

- [ ] **Step 5.4: Run ruff + mypy**

Run: `ruff check src/backtester.py tests/test_backtester.py && ruff format --check src/backtester.py tests/test_backtester.py && mypy src/backtester.py`
Expected: No errors

- [ ] **Step 5.5: Commit compatibility update**

```bash
git add tests/test_backtester.py
git commit -m "[#216] refactor: test_bug2 → test_equity_includes_position_market_value

기존 테스트 로직 유지, 이름/주석을 B1 수정 후 시맨틱에 맞게 갱신"
```

---

## Chunk 5: Backtest Validation Run

### Task 6: Verify fix with actual backtest scenarios

- [ ] **Step 6.1: Run backtests and verify MDD is sane**

```bash
cd /Users/momo/dev/turtle_trading
python scripts/run_backtest.py 2>&1 | head -30
```

Expected: MDD values between 0% and ~50% (typical turtle trading range), NOT >100%

- [ ] **Step 6.2: Run with --no-risk-limits for comparison**

```bash
python scripts/run_backtest.py --no-risk-limits 2>&1 | head -30
```

Expected: MDD still bounded 0-100%

- [ ] **Step 6.3: Final full test suite**

```bash
pytest -q && ruff check src/ scripts/ tests/ && mypy src/backtester.py
```

Expected: All green

---

## Summary of Changes

| Bug | File | Line | Before | After |
|-----|------|------|--------|-------|
| B1 | `backtester.py` | `_record_equity` | `cash + unrealized_pnl` | `cash + sum(positions_value)` (LONG: `Q*P_c`, SHORT: `Q*(2*P_e-P_c)`) |
| B2 | `backtester.py` | `_record_equity` | (missing) | `account.current_equity = equity` |
| B3 | `backtester.py` | `_close_position` | `cash += Q * P` | `cash += Q * P * (1-c)` |
| B4 | — | — | Auto-resolved by B1 | — |

## Test Coverage Added

| Test Class | Tests | Validates |
|------------|-------|-----------|
| `TestEquityInvariants` | 7 | I1-I5 + multi-symbol variants |
| `TestEquityFormula` | 2 | B1 mark-to-market correctness |
| `TestRoundTripCommission` | 2 | B1+B3 통합 왕복 수수료 + SHORT equity |
| `TestExitCommission` | 1 | B3 exit commission deduction |
| `TestCurrentEquityUpdate` | 2 | B2 equity refresh + sizing impact |
| Updated: `TestBugFixes` | 1 | Renamed to reflect market value |

Total: **14 new tests + 1 updated**

## Known Limitations (Pre-existing, Not Fixed in This PR)

1. **`Trade.pnl` excludes entry commission**: `realized_pnl`은 exit commission만 포함. 진입 수수료는 cash에서만 차감되어 `Trade.pnl`이 수익률을 약간 과대 평가함. I3 invariant은 이 때문에 `commission_pct=0.0`에서만 정확히 성립.
2. **SHORT collateral model**: 실제 공매도(차입 매도 → 대금 수령)가 아닌 담보 모델(진입 시 cash 차감). 기존 백테스터 설계 그대로 유지.
