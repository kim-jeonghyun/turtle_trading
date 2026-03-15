# Short-Restricted & N-Exposure 수정 구현 플랜 v2

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KRW 백테스트 신뢰성을 확보하기 위해 (1) short_restricted 미적용 버그를 수정하고 (2) N-노출을 유닛 수 기반으로 수정한다.

**Architecture:** 두 이슈를 순차 구현 (같은 브랜치). #223(short_restricted)은 backtester에 심볼별 공매도 제한 정보를 전달하여 ENTRY_SHORT 차단. #222(N-exposure)는 risk_manager의 N-노출 계산을 `n_value * units` → `units`로 변경하여 통화 무관하게 각 유닛이 정확히 1.0 기여하도록 수정.

**Tech Stack:** Python 3.12, pytest, ruff

**핵심 설계 결정 (v1 → v2 변경점):**

Curtis Faith "Way of the Turtle"에서 N-노출 한도는 **유닛 수 한도**이다. 각 터틀 유닛은 `(equity * risk_percent) / ATR` 주식으로 계산되므로, 1유닛 = 1% 리스크 = 정확히 1.0 N-노출이다. 따라서 `total_n_exposure += n_value * units`가 아닌 `total_n_exposure += units`가 올바르다.

이 접근의 장점:
- **시그니처 변경 없음** — can_add_position/add_position/remove_position 인자 불변
- **호출부 변경 없음** — backtester.py, check_positions.py, 테스트 모두 수정 불필요
- **역호환 보장** — 기본값 변경 없이 내부 계산만 수정
- **3줄 변경** — risk_manager.py 내부에서 `n_value *` 제거만 하면 완료

**Momus v1 리뷰 (62/100) 대응:**

| ID | 심각도 | v1 결함 | v2 해결 |
|----|--------|---------|---------|
| F1 | CRITICAL | `remove_position` 미수정 → N-노출 드리프트 | `units` 기반이므로 `remove_position`도 자동 수정 (line 117) |
| F3 | CRITICAL | `check_positions.py` 호출부 누락 | 시그니처 불변이므로 **수정 불필요** |
| F9 | HIGH | equity=0 기본값이 모든 기존 호출을 차단 | equity 파라미터 불필요, **시그니처 불변** |
| F2 | HIGH | add/can 비대칭 폴백 | 폴백 자체가 불필요 |
| F4 | MEDIUM | test_check_positions.py 10개 호출 깨짐 | 시그니처 불변이므로 **깨지지 않음** |
| F5 | MEDIUM | pages/backtest.py에 symbol_groups 누락 | short_restricted는 Task 3에서 적용 (불가능한 거래 차단). symbol_groups/리스크 한도는 별도 이슈 |
| F6 | MEDIUM | vacuous 테스트 | positive assertion 추가 |
| F7 | LOW | 10 심볼이 그룹 한도 먼저 도달 | 각 심볼에 다른 그룹 할당 |
| F8 | LOW | fixture 미정의 | fixture 정의 추가 |
| F10 | MEDIUM | 두 브랜치 머지 충돌 위험 | **단일 브랜치**로 통합 |
| F11 | MEDIUM | get_risk_summary() 의미 변경 미고려 | 문서화 + 주석 추가 |
| F12 | LOW | 라인 참조 부정확 | 정확한 라인 참조 |

---

## 평가 루브릭 (100점)

| 영역 | 가중치 | 5/5 기준 | 2/5 기준 | 검증 방법 |
|------|--------|---------|---------|-----------|
| 금융공학 정확성 | 30% | N-노출 = 유닛수, short 차단 = screener 동일 패턴 | ATR 누적 유지 또는 short 차단 누락 | 테스트 + Curtis Faith 원서 대조 |
| 리스크 관리 무결성 | 25% | USD 회귀 0건, add/remove 대칭, 호출부 불변 | 기존 테스트 실패 또는 N-노출 드리프트 | pytest 전체 통과 |
| 통계적 타당성 | 15% | 비실현 가능 거래(KRW short) 0건 | short 거래가 결과에 포함 | 백테스트 결과의 short trade 수 검증 |
| 코드 품질/테스트 | 20% | TDD, 엣지케이스, vacuous-pass 방지 | 테스트 없는 코드 변경 | ruff + pytest + 신규 테스트 수 |
| 아키텍처 유지보수성 | 10% | 최소 변경, 시그니처 불변, 인터페이스 안정 | 기존 호출부 대량 수정 | git diff --stat |

---

## Chunk 1: Issue #223 — short_restricted 적용 (bugfix)

**영향 파일:** src 3 + tests 3 + scripts 1 + pages 1

### Task 1: UniverseManager에 short_restricted 심볼 조회 메서드 추가

**Files:**
- Modify: `src/universe_manager.py` — `get_short_restricted_symbols()` 추가
- Test: `tests/test_universe_manager.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_universe_manager.py에 추가
def test_get_short_restricted_symbols(universe_manager):
    """short_restricted=True인 심볼만 반환."""
    restricted = universe_manager.get_short_restricted_symbols()
    assert isinstance(restricted, set)
    assert len(restricted) > 0  # vacuous-pass 방지
    # KRW 종목은 모두 short_restricted
    assert "005930.KS" in restricted  # 삼성전자
    # USD ETF는 short_restricted=False
    assert "SPY" not in restricted
    assert "QQQ" not in restricted
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && python -m pytest tests/test_universe_manager.py -k test_get_short_restricted_symbols -v`
Expected: FAIL — `AttributeError: 'UniverseManager' has no attribute 'get_short_restricted_symbols'`

- [ ] **Step 3: 최소 구현**

```python
# src/universe_manager.py — UniverseManager 클래스에 추가 (get_symbols_by_currency 메서드 뒤)
def get_short_restricted_symbols(self) -> set[str]:
    """short_restricted=True인 심볼 집합 반환."""
    return {asset.symbol for asset in self.assets if asset.short_restricted}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `source .venv/bin/activate && python -m pytest tests/test_universe_manager.py -k test_get_short_restricted_symbols -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/universe_manager.py tests/test_universe_manager.py
git commit -m "[#223] feat: UniverseManager.get_short_restricted_symbols() 추가"
```

### Task 2: TurtleBacktester에 short_restricted 적용

**Files:**
- Modify: `src/backtester.py:78` (생성자에 파라미터 추가)
- Modify: `src/backtester.py:140` (_check_entry_signal에 차단 로직)
- Test: `tests/test_backtester.py`

- [ ] **Step 1: 테스트 fixture 작성 — 숏 시그널 발생 데이터**

```python
# tests/test_backtester.py — fixture 추가
@pytest.fixture
def short_signal_data():
    """숏 브레이크아웃이 발생하는 가격 데이터 생성.

    구조: 60일간 하락 추세로 dc_low_20 이탈 발생.
    """
    import numpy as np
    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    # 처음 40일은 횡보(dc_low_20 형성), 이후 40일은 하락
    prices_flat = [100.0] * 40
    prices_down = [100.0 - i * 1.5 for i in range(40)]
    prices = prices_flat + prices_down

    df = pd.DataFrame({
        "date": dates[:len(prices)],
        "open": prices,
        "high": [p + 2 for p in prices],
        "low": [p - 2 for p in prices],
        "close": prices,
        "volume": [1000000] * len(prices),
    })
    return df
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/test_backtester.py에 추가
class TestShortRestricted:
    """short_restricted 심볼의 ENTRY_SHORT 차단 검증."""

    def test_short_restricted_blocks_short_entry(self, short_signal_data):
        """short_restricted=True인 심볼은 ENTRY_SHORT 생성하지 않음."""
        config = BacktestConfig(initial_capital=100000, system=2)
        bt = TurtleBacktester(
            config,
            short_restricted_symbols={"TEST_KR"},
        )
        result = bt.run({"TEST_KR": short_signal_data})
        short_trades = [t for t in result.trades if t.direction == "SHORT"]
        assert len(short_trades) == 0, "short_restricted 심볼에 숏 거래가 발생함"

    def test_non_restricted_allows_short_entry(self, short_signal_data):
        """short_restricted에 없는 심볼은 ENTRY_SHORT 정상 생성."""
        config = BacktestConfig(initial_capital=100000, system=2)
        bt = TurtleBacktester(
            config,
            short_restricted_symbols={"OTHER_SYMBOL"},  # TEST_US는 제한 대상 아님
        )
        result = bt.run({"TEST_US": short_signal_data})
        short_trades = [t for t in result.trades if t.direction == "SHORT"]
        # 하락 데이터이므로 숏 진입이 발생해야 함
        assert len(short_trades) > 0, "비제한 심볼에서 숏 거래가 발생해야 함"

    def test_default_no_restriction(self):
        """short_restricted_symbols 미전달 시 숏 제한 없음 (역호환)."""
        config = BacktestConfig(initial_capital=100000, system=1)
        bt = TurtleBacktester(config)  # short_restricted_symbols=None
        assert len(bt.short_restricted_symbols) == 0
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `source .venv/bin/activate && python -m pytest tests/test_backtester.py::TestShortRestricted -v`
Expected: FAIL — `TypeError: __init__() got unexpected keyword argument 'short_restricted_symbols'`

- [ ] **Step 4: 구현 — 생성자에 파라미터 추가**

```python
# src/backtester.py:78-83 — __init__ 시그니처 확장
class TurtleBacktester:
    def __init__(
        self,
        config: BacktestConfig,
        symbol_groups: Optional[Dict[str, AssetGroup]] = None,
        currency: str = "USD",
        short_restricted_symbols: Optional[set[str]] = None,
    ):
        self.config = config
        self.currency = currency
        self.short_restricted_symbols: set[str] = short_restricted_symbols or set()
        # ... 나머지 기존 코드 동일 (commission_model, account, 등)
```

- [ ] **Step 5: 구현 — _check_entry_signal에 숏 차단 로직**

```python
# src/backtester.py:140-152 — 숏 진입 블록 수정
# ⚠️ 삽입 위치 중요: line 141 `if row["low"] < prev_row[entry_low]:` 블록 내부,
#    System 1 필터 앞에 삽입. 메서드 상단에 넣으면 LONG도 차단되므로 절대 금지.
        # 숏 진입 신호
        if row["low"] < prev_row[entry_low]:
            # short_restricted 체크 (screener.py:172와 동일 패턴)
            # ← 반드시 이 위치: SHORT 브랜치 내부, LONG 브랜치 아래
            if symbol in self.short_restricted_symbols:
                return None
            if self.config.system == 1 and self.config.use_filter:
                if self.last_trade_profitable.get(symbol, False):
                    if row["low"] >= prev_row.get("dc_low_55", 0):
                        self._record_hypothetical_breakout(
                            symbol,
                            prev_row[entry_low],
                            Direction.SHORT,
                            n_value=float(row.get("N", row.get("atr", 0))),
                        )
                        return None
            return SignalType.ENTRY_SHORT
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `source .venv/bin/activate && python -m pytest tests/test_backtester.py::TestShortRestricted -v`
Expected: PASS

- [ ] **Step 7: 기존 테스트 전체 통과 확인 (역호환)**

Run: `source .venv/bin/activate && python -m pytest tests/test_backtester.py -v`
Expected: ALL PASS (기본값 `set()`이므로 기존 동작 불변)

- [ ] **Step 8: 커밋**

```bash
git add src/backtester.py tests/test_backtester.py
git commit -m "[#223] fix: backtester에 short_restricted 적용 — KRW 숏 진입 차단"
```

### Task 3: 호출부 업데이트

**Files:**
- Modify: `scripts/run_backtest.py:137` — short_restricted_symbols 전달
- Modify: `src/multi_currency_backtester.py:41-63` — short_restricted_symbols 파라미터 추가
- Modify: `pages/backtest.py:51` — 대시보드 경로
- Test: `tests/test_multi_currency_backtester.py`

- [ ] **Step 1: run_backtest.py 업데이트**

```python
# scripts/run_backtest.py:137 부근
# 기존:
#   backtester = TurtleBacktester(config, symbol_groups=symbol_groups)
# 변경:
short_restricted = universe.get_short_restricted_symbols()
backtester = TurtleBacktester(
    config,
    symbol_groups=symbol_groups,
    short_restricted_symbols=short_restricted,
)
```

- [ ] **Step 2: multi_currency_backtester.py 업데이트**

```python
# src/multi_currency_backtester.py:41-63 — __init__ 시그니처 확장
def __init__(
    self,
    usd_config: Optional[BacktestConfig] = None,
    krw_config: Optional[BacktestConfig] = None,
    usd_symbol_groups: Optional[Dict[str, AssetGroup]] = None,
    krw_symbol_groups: Optional[Dict[str, AssetGroup]] = None,
    short_restricted_symbols: Optional[set[str]] = None,
):
    self.usd_backtester: Optional[TurtleBacktester] = None
    self.krw_backtester: Optional[TurtleBacktester] = None

    if usd_config:
        self.usd_backtester = TurtleBacktester(
            usd_config,
            symbol_groups=usd_symbol_groups,
            currency="USD",
            # USD는 short_restricted 없으므로 전달하지 않음
        )

    if krw_config:
        self.krw_backtester = TurtleBacktester(
            krw_config,
            symbol_groups=krw_symbol_groups,
            currency="KRW",
            short_restricted_symbols=short_restricted_symbols,
        )
```

- [ ] **Step 3: run_backtest.py multi-currency 경로 업데이트**

```python
# scripts/run_backtest.py — multi-currency 경로에서도 short_restricted 전달
# MultiCurrencyBacktester 생성 시:
short_restricted = universe.get_short_restricted_symbols()
mcbt = MultiCurrencyBacktester(
    usd_config=usd_config,
    krw_config=krw_config,
    usd_symbol_groups=usd_symbol_groups,
    krw_symbol_groups=krw_symbol_groups,
    short_restricted_symbols=short_restricted,
)
```

- [ ] **Step 4: pages/backtest.py 업데이트**

```python
# pages/backtest.py:51 부근
# 기존: backtester = TurtleBacktester(config)
# 변경:
short_restricted = universe.get_short_restricted_symbols() if universe else set()
backtester = TurtleBacktester(config, short_restricted_symbols=short_restricted)
# NOTE: pages/backtest.py는 symbol_groups를 전달하지 않으므로 risk_manager=None (리스크 한도 미적용).
# 이는 기존 동작과 동일하며, 대시보드에서의 리스크 한도 적용은 별도 이슈로 관리.
```

- [ ] **Step 5: 테스트 추가**

```python
# tests/test_multi_currency_backtester.py에 추가
def test_krw_backtester_receives_short_restricted():
    """KRW backtester가 short_restricted_symbols를 전달받는지 확인."""
    krw_config = BacktestConfig(initial_capital=100_000_000)
    restricted = {"005930.KS", "000660.KS"}
    mcbt = MultiCurrencyBacktester(
        krw_config=krw_config,
        short_restricted_symbols=restricted,
    )
    assert mcbt.krw_backtester is not None
    assert mcbt.krw_backtester.short_restricted_symbols == restricted

def test_usd_backtester_no_short_restriction():
    """USD backtester는 short_restricted 미적용."""
    usd_config = BacktestConfig(initial_capital=100_000)
    mcbt = MultiCurrencyBacktester(
        usd_config=usd_config,
        short_restricted_symbols={"005930.KS"},
    )
    assert mcbt.usd_backtester is not None
    assert len(mcbt.usd_backtester.short_restricted_symbols) == 0
```

- [ ] **Step 6: lint + 전체 테스트**

Run: `source .venv/bin/activate && ruff check src/ scripts/ tests/ && python -m pytest tests/ -q --tb=short`
Expected: ALL PASS

- [ ] **Step 7: 커밋**

```bash
git add scripts/run_backtest.py src/multi_currency_backtester.py pages/backtest.py tests/test_multi_currency_backtester.py
git commit -m "[#223] fix: 모든 호출부에 short_restricted_symbols 전달"
```

---

## Chunk 2: Issue #222 — N-노출을 유닛 수 기반으로 수정

**핵심 변경:** `risk_manager.py`에서 `n_value * units` → `units` (3줄 수정)

**영향 파일:** src 1 + tests 1

**시그니처 변경 없음** — `can_add_position`, `add_position`, `remove_position` 모두 기존 시그니처 유지. `n_value` 파라미터는 유지하되 N-노출 계산에 사용하지 않음 (validation + 로깅/디버깅 용도로 보존).

### Task 4: risk_manager.py N-노출 계산 수정

**Files:**
- Modify: `src/risk_manager.py:68` (can_add_position 내 N-노출 계산)
- Modify: `src/risk_manager.py:90` (add_position 내 N-노출 누적)
- Modify: `src/risk_manager.py:117` (remove_position 내 N-노출 차감)
- Test: `tests/test_risk_manager.py`

- [ ] **Step 1: 실패 테스트 작성 — N-노출 = 유닛 수**

```python
# tests/test_risk_manager.py에 추가
class TestNExposureUnitBased:
    """N-노출이 유닛 수 기반으로 계산되는지 검증.

    Curtis Faith: N-노출 한도 = 유닛 수 한도.
    각 유닛 = 1% 리스크이므로, N-노출 = 유닛 수.
    ATR(n_value) 크기와 무관해야 함.
    """

    def test_krw_single_unit_not_blocked(self):
        """KRW ATR=2500이어도 1유닛 = N-노출 1.0, 한도(10) 내."""
        rm = PortfolioRiskManager(symbol_groups={"005930.KS": AssetGroup.KR_EQUITY})
        allowed, _ = rm.can_add_position(
            "005930.KS", 1, n_value=2500.0, direction=Direction.LONG
        )
        assert allowed, "KRW 1유닛이 N-노출 한도에 차단되면 안 됨"

    def test_usd_single_unit_not_blocked(self):
        """USD ATR=4.5, 1유닛 = N-노출 1.0."""
        rm = PortfolioRiskManager(symbol_groups={"SPY": AssetGroup.US_EQUITY})
        allowed, _ = rm.can_add_position(
            "SPY", 1, n_value=4.5, direction=Direction.LONG
        )
        assert allowed

    def test_n_exposure_equals_unit_count(self):
        """N-노출 = 추가된 유닛 수의 합."""
        rm = PortfolioRiskManager(symbol_groups={
            "A": AssetGroup.US_EQUITY,
            "B": AssetGroup.COMMODITY,
            "C": AssetGroup.BOND,
        })
        rm.add_position("A", 2, n_value=4.5, direction=Direction.LONG)
        rm.add_position("B", 1, n_value=50.0, direction=Direction.LONG)
        rm.add_position("C", 3, n_value=0.5, direction=Direction.SHORT)
        # N-노출 = 2 + 1 + 3 = 6 (ATR 값과 무관)
        summary = rm.get_risk_summary()
        assert summary["total_n_exposure"] == 6.0

    def test_n_exposure_currency_agnostic(self):
        """KRW(ATR=2500)와 USD(ATR=4.5) 각 1유닛 → N-노출 동일하게 1.0씩."""
        rm = PortfolioRiskManager(symbol_groups={
            "005930.KS": AssetGroup.KR_EQUITY,
            "SPY": AssetGroup.US_EQUITY,
        })
        rm.add_position("005930.KS", 1, n_value=2500.0, direction=Direction.LONG)
        rm.add_position("SPY", 1, n_value=4.5, direction=Direction.LONG)
        summary = rm.get_risk_summary()
        assert summary["total_n_exposure"] == 2.0  # 1 + 1, ATR 무관

    def test_blocks_at_max_n_exposure(self):
        """10유닛 초과 시 차단 (max_total_n_exposure=10.0)."""
        groups = {f"SYM{i}": [
            AssetGroup.US_EQUITY, AssetGroup.COMMODITY, AssetGroup.BOND,
            AssetGroup.CURRENCY, AssetGroup.REIT, AssetGroup.ASIA_EQUITY,
            AssetGroup.EU_EQUITY, AssetGroup.CHINA_EQUITY,
            AssetGroup.COMMODITY_ENERGY, AssetGroup.COMMODITY_AGRI,
        ][i] for i in range(10)}
        rm = PortfolioRiskManager(symbol_groups=groups)
        for i in range(10):
            rm.add_position(f"SYM{i}", 1, n_value=100.0, direction=Direction.LONG)
        # 10유닛 → N-노출 10.0, 추가 불가
        allowed, msg = rm.can_add_position(
            "SYM0", 1, n_value=100.0, direction=Direction.LONG
        )
        assert not allowed
        assert "N 노출" in msg

    def test_remove_position_restores_n_exposure(self):
        """remove_position 후 N-노출이 정확히 감소. (F1 대응)"""
        rm = PortfolioRiskManager(symbol_groups={"SPY": AssetGroup.US_EQUITY})
        rm.add_position("SPY", 3, n_value=4.5, direction=Direction.LONG)
        assert rm.get_risk_summary()["total_n_exposure"] == 3.0
        rm.remove_position("SPY", 2, Direction.LONG, n_value=4.5)
        assert rm.get_risk_summary()["total_n_exposure"] == 1.0
        rm.remove_position("SPY", 1, Direction.LONG, n_value=4.5)
        assert rm.get_risk_summary()["total_n_exposure"] == 0.0

    def test_add_remove_symmetry(self):
        """add → remove 왕복 후 N-노출 = 0. (F2 대응)"""
        rm = PortfolioRiskManager(symbol_groups={"SPY": AssetGroup.US_EQUITY})
        rm.add_position("SPY", 4, n_value=4.5, direction=Direction.LONG)
        rm.remove_position("SPY", 4, Direction.LONG, n_value=4.5)
        assert rm.get_risk_summary()["total_n_exposure"] == 0.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && python -m pytest tests/test_risk_manager.py::TestNExposureUnitBased -v`
Expected: FAIL — test_krw_single_unit_not_blocked fails (2500 > 10.0)

- [ ] **Step 3: 구현 — 3줄 수정**

```python
# src/risk_manager.py:68 (can_add_position 내)
# 기존: new_n_exposure = n_value * units
# 변경:
new_n_exposure = units  # Curtis Faith: N-노출 = 유닛 수 (ATR 무관)

# src/risk_manager.py:90 (add_position 내)
# 기존: self.state.total_n_exposure += n_value * units
# 변경:
self.state.total_n_exposure += units

# src/risk_manager.py:117 (remove_position 내)
# 기존: self.state.total_n_exposure = max(0.0, self.state.total_n_exposure - n_value * actual_units)
# 변경:
self.state.total_n_exposure = max(0.0, self.state.total_n_exposure - actual_units)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `source .venv/bin/activate && python -m pytest tests/test_risk_manager.py::TestNExposureUnitBased -v`
Expected: ALL PASS

- [ ] **Step 5: 기존 테스트 확인 및 수정**

Run: `source .venv/bin/activate && python -m pytest tests/test_risk_manager.py -v`

기존 테스트 중 `n_value * units` 기반 assertion이 있으면 `units` 기반으로 업데이트.
예: `assert summary["total_n_exposure"] == 4.5 * 1` → `assert summary["total_n_exposure"] == 1.0`

**주의:** 기존 테스트가 실패하는 경우, N-노출 값 비교 assertion만 수정. 로직 테스트(차단/허용)는 그대로 통과해야 함.

- [ ] **Step 6: 커밋**

```bash
git add src/risk_manager.py tests/test_risk_manager.py
git commit -m "[#222] fix: N-노출을 유닛 수 기반으로 수정 (Curtis Faith 원래 의도)"
```

### Task 5: 기존 N-노출 테스트 업데이트 + check_positions.py/backtester.py 검증

**Files:**
- Verify: `src/backtester.py` — 호출부 변경 불필요 (시그니처 불변)
- Verify: `scripts/check_positions.py` — 호출부 변경 불필요
- Modify: `tests/test_backtester.py` — N-노출 관련 assertion 값 수정 (필요시)
- Modify: `tests/test_check_positions.py` — N-노출 관련 assertion 값 수정 (필요시)

- [ ] **Step 1: 전수 검사 — can_add_position/add_position/remove_position 호출부**

Run:
```bash
source .venv/bin/activate && grep -rn "can_add_position\|add_position\|remove_position" src/ scripts/ --include="*.py" | grep -v "test_\|\.pyc\|docs/"
```

확인 사항: 모든 호출이 기존 시그니처와 동일한지 검증. 시그니처가 불변이므로 코드 변경은 불필요하나, N-노출 값이 변경되므로 로그/출력에서 값의 의미 변경을 인지.

- [ ] **Step 2: 전체 테스트 실행**

Run: `source .venv/bin/activate && python -m pytest tests/ -q --tb=short 2>&1 | tail -20`

실패 테스트가 있으면 N-노출 assertion 값만 수정 (units 기반으로).

- [ ] **Step 3: risk_manager.py에 주석 추가 (F11 대응)**

```python
# src/risk_manager.py — RiskLimits 클래스 docstring에 추가
@dataclass
class RiskLimits:
    """포트폴리오 리스크 한도.

    max_total_n_exposure: 전체 N-노출 한도 (유닛 수 기준).
        Curtis Faith: 각 유닛 = 1% 리스크, N-노출 = 유닛 수.
        예: max_total_n_exposure=10.0 → 최대 10 유닛 보유 가능.
    """
    max_units_per_market: int = 4
    max_units_correlated: int = 6
    max_units_direction: int = 12
    max_total_n_exposure: float = 10.0
```

- [ ] **Step 4: 커밋**

```bash
git add tests/ src/risk_manager.py
git commit -m "[#222] chore: N-노출 유닛 기반 전환에 따른 테스트/문서 업데이트"
```

### Task 6: run_backtest.py N-노출 경고 제거

**Files:**
- Modify: `scripts/run_backtest.py` — PR #221에서 추가한 N-노출 경고 제거

- [ ] **Step 1: 경고 코드 제거**

PR #221에서 `--multi-currency` 모드의 N-노출 경고를 추가했으나, 유닛 기반 수정 후 불필요.

```python
# scripts/run_backtest.py — 아래 블록 제거
# if args.multi_currency and not args.no_risk_limits:
#     logger.warning("--multi-currency 모드에서 리스크 한도(N-노출)는 KRW ATR 스케일 차이로 인해 ...")
```

- [ ] **Step 2: lint + 전체 테스트**

Run: `source .venv/bin/activate && ruff check src/ scripts/ tests/ && python -m pytest tests/ -q --tb=short`
Expected: ALL PASS

- [ ] **Step 3: 커밋**

```bash
git add scripts/run_backtest.py
git commit -m "[#222] chore: N-노출 유닛 기반 수정 완료로 KRW 경고 메시지 제거"
```

---

## 구현 순서 및 의존성

**단일 브랜치:** `bugfix/issue-223-short-restricted-n-exposure` (F10 대응: 머지 충돌 방지)

```
Task 1 (UniverseManager.get_short_restricted_symbols)
  └── Task 2 (Backtester short_restricted 파라미터 + 차단 로직)
        └── Task 3 (호출부: run_backtest, multi_currency, pages/backtest)
              └── Task 4 (risk_manager N-노출 유닛 기반 수정 — 3줄)
                    └── Task 5 (기존 테스트 업데이트 + 전수 검사)
                          └── Task 6 (N-노출 경고 제거)
                                └── PR 생성 (Fixes #223, Fixes #222)
```

## 검증 체크리스트

### PR 머지 전 (통합)
- [ ] ruff check src/ scripts/ tests/ 통과
- [ ] pytest 전체 통과 (기존 + 신규)
- [ ] KRW 심볼(005930.KS 등)의 숏 거래 0건 확인
- [ ] USD 심볼의 숏 거래 기존과 동일
- [ ] screener.py:172와 backtester의 short_restricted 체크 동일 패턴
- [ ] N-노출 = 유닛 수 확인 (ATR 값 무관)
- [ ] add/remove 대칭성 확인 (add → remove 후 N-노출 = 0)
- [ ] `--multi-currency` (리스크 한도 적용) 모드에서 KRW 진입 정상
- [ ] `--no-risk-limits` 모드 기존 동작 불변
- [ ] can_add_position/add_position/remove_position 호출부 전수 grep 검사 완료
- [ ] get_risk_summary() 반환값의 total_n_exposure 의미 변경 문서화

## 위험 및 완화

| 위험 | 영향 | 완화 |
|------|------|------|
| 기존 N-노출 assertion 실패 | MEDIUM | Task 5에서 값만 수정 (units 기반), 로직 불변 |
| `n_value` 파라미터 혼란 | LOW | n_value는 시그니처에 유지하되 N-노출 계산에 미사용 — 주석 명시 |
| get_risk_summary() 소비자 혼란 | LOW | RiskLimits docstring + 대시보드 라벨 확인 |
| pages/backtest.py symbol_groups 미전달 | LOW | 기존 동작 유지 (risk_manager=None), 별도 이슈로 문서화 |
| short_signal_data fixture 부정확 | MEDIUM | 실제 dc_low 이탈 발생하는 데이터 패턴 검증 필요 |

## 변경 범위 요약

| 파일 | 변경 유형 | 라인 수 (예상) |
|------|-----------|---------------|
| `src/universe_manager.py` | 메서드 추가 | +3 |
| `src/backtester.py` | 파라미터 + 차단 로직 | +5 |
| `src/multi_currency_backtester.py` | 파라미터 전달 | +3 |
| `src/risk_manager.py` | 3줄 수정 + 주석 | +5, -3 |
| `scripts/run_backtest.py` | short_restricted 전달 + 경고 제거 | +4, -4 |
| `pages/backtest.py` | short_restricted 전달 | +2 |
| `tests/test_universe_manager.py` | 테스트 추가 | +8 |
| `tests/test_backtester.py` | fixture + 테스트 3개 | +40 |
| `tests/test_multi_currency_backtester.py` | 테스트 2개 | +15 |
| `tests/test_risk_manager.py` | 테스트 7개 + assertion 수정 | +60, ~-10 |
| **총계** | | **+145, -17** |
