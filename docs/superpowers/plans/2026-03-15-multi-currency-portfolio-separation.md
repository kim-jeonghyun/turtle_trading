# Multi-Currency Portfolio Separation Implementation Plan (v3)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KRW/USD 포트폴리오를 통화별로 완전 분리하여 각 통화 내에서 독립적인 자본관리, 포지션 사이징, 리스크 관리를 수행한다. 통화별 독립 성과 리포트를 출력한다.

**Architecture:** Option B (통화별 분리 포트폴리오) 채택. 각 통화는 독립 `AccountState`, 독립 `PortfolioRiskManager`(동일한 `max_total_n_exposure=10.0` — 통화 내에서 N값 스케일이 동질적이므로), 독립 수수료 모델을 가진다. `MultiCurrencyBacktester`가 데이터를 통화별로 분리하여 독립 `TurtleBacktester`에 전달한다.

**Tech Stack:** Python 3.12, pandas, PyYAML, pytest, FinanceDataReader (KRW data)

**Issue:** #220

**Scope boundary:**
- IN: 통화별 분리 백테스트, KRW 유니버스 확대, 시장별 수수료, 통화별 리포트
- OUT: FX-adjusted 합산 리포트 (후속 이슈), Walk-forward/Monte Carlo (D5), `paper_trader.py` 수수료 전환 (live 경로, 별도 이슈)

---

## Chunk 1: Foundation — Currency Field & Commission Model

### File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `config/universe.yaml` | `currency` 필드 추가 (KRW/USD) |
| Modify | `src/universe_manager.py` | `Asset.currency` 속성 추가, YAML 파싱, `get_symbols_by_currency()` |
| Create | `src/commission.py` | 시장별 수수료 모델 (증권거래세 + 위탁수수료) |
| Modify | `tests/test_universe_manager.py` | currency 관련 테스트 |
| Create | `tests/test_commission.py` | 수수료 모델 단위 테스트 |

### Task 1: universe.yaml에 currency 필드 추가

**Files:**
- Modify: `config/universe.yaml`
- Modify: `src/universe_manager.py:16-26,75-106`
- Test: `tests/test_universe_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_universe_manager.py - 추가
def test_asset_has_currency_field():
    """Asset에 currency 필드가 존재하고, KR 종목은 KRW, US 종목은 USD"""
    um = UniverseManager(yaml_path="config/universe.yaml")
    spy = um.assets["SPY"]
    assert spy.currency == "USD"
    samsung = um.assets["005930.KS"]
    assert samsung.currency == "KRW"

def test_get_symbols_by_currency():
    """통화별 심볼 필터링"""
    um = UniverseManager(yaml_path="config/universe.yaml")
    krw_symbols = um.get_symbols_by_currency("KRW")
    usd_symbols = um.get_symbols_by_currency("USD")
    assert "005930.KS" in krw_symbols
    assert "SPY" in usd_symbols
    assert len(krw_symbols) + len(usd_symbols) == len(um.get_enabled_symbols())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.12 -m pytest tests/test_universe_manager.py -k "currency" -v`
Expected: FAIL with "AttributeError: 'Asset' has no attribute 'currency'"

- [ ] **Step 3: Add currency field to Asset dataclass**

```python
# src/universe_manager.py - Asset dataclass
@dataclass
class Asset:
    symbol: str
    name: str
    country: str
    asset_type: str
    group: AssetGroup
    currency: str = "USD"  # "USD" or "KRW"
    leverage: float = 1.0
    underlying: Optional[str] = None
    enabled: bool = True
    short_restricted: bool = True
```

Note: `currency`는 `group` 다음, `leverage` 앞에 위치.
**CRITICAL (N3 fix):** `_load_defaults()` (lines 122-136)의 8개 `Asset()` 호출 중 2개가 positional arg로
`leverage`와 `underlying`을 전달한다. `currency` 필드 삽입 후 positional 순서가 어긋나므로
**전부 keyword argument로 변환해야 한다:**

```python
# src/universe_manager.py _load_defaults - 전체 8개 엔트리 (ALL must use keyword args)
defaults = [
    Asset("SPY", "S&P 500 ETF", "US", "Index ETF", AssetGroup.US_EQUITY, short_restricted=False),
    Asset("QQQ", "Nasdaq 100 ETF", "US", "Index ETF", AssetGroup.US_EQUITY, short_restricted=False),
    Asset("DIA", "Dow Jones ETF", "US", "Index ETF", AssetGroup.US_EQUITY, short_restricted=False),
    Asset("IWM", "Russell 2000 ETF", "US", "Index ETF", AssetGroup.US_EQUITY, short_restricted=False),
    Asset("GLD", "Gold ETF", "US", "Commodity ETF", AssetGroup.COMMODITY, short_restricted=False),
    Asset("TLT", "Treasury 20+ ETF", "US", "Bond ETF", AssetGroup.BOND, short_restricted=False),
    # These two MUST switch from positional to keyword (leverage/underlying were positional):
    Asset("SH", "S&P 500 Inverse", "US", "Inverse ETF", AssetGroup.INVERSE,
          leverage=-1, underlying="SPY", short_restricted=False),
    Asset("SQQQ", "Nasdaq 3x Inverse", "US", "Inverse ETF", AssetGroup.INVERSE,
          leverage=-3, underlying="QQQ", short_restricted=False),
]
```

Also update `_load_from_csv` (lines 108-120) to set currency from symbol suffix:
```python
# src/universe_manager.py _load_from_csv 내부
currency = "KRW" if (symbol.endswith(".KS") or symbol.endswith(".KQ")) else "USD"
asset = Asset(
    symbol=symbol,
    name=..., country=..., asset_type=...,
    group=AssetGroup.US_EQUITY,
    currency=currency,
    enabled=True,
)
```

- [ ] **Step 4: Update YAML parsing to set currency**

```python
# src/universe_manager.py - _load_from_yaml 내부
# country/currency 결정
if symbol.endswith(".KS") or symbol.endswith(".KQ"):
    country = "KR"
    currency = "KRW"
else:
    country = "US"
    currency = "USD"

asset = Asset(
    symbol=symbol,
    name=item.get("name", symbol),
    country=country,
    asset_type=category,
    group=asset_group,
    currency=currency,
    leverage=leverage,
    underlying=item.get("underlying"),
    enabled=True,
    short_restricted=short_restricted,
)
```

- [ ] **Step 5: Add get_symbols_by_currency method**

```python
# src/universe_manager.py - UniverseManager class
def get_symbols_by_currency(self, currency: str) -> List[str]:
    """통화별 활성 심볼 반환"""
    return [s for s, a in self.assets.items() if a.currency == currency and a.enabled]

def get_currency_map(self) -> Dict[str, str]:
    """심볼 → 통화 매핑 반환"""
    return {s: a.currency for s, a in self.assets.items()}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3.12 -m pytest tests/test_universe_manager.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add config/universe.yaml src/universe_manager.py tests/test_universe_manager.py
git commit -m "[#220] feat: Asset에 currency 필드 추가 및 통화별 필터링"
```

### Task 2: 시장별 수수료 모델 생성

**Files:**
- Create: `src/commission.py`
- Create: `tests/test_commission.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_commission.py
from src.commission import CommissionModel, KRXCommissionModel, USCommissionModel

class TestUSCommissionModel:
    def test_buy_commission(self):
        model = USCommissionModel(commission_rate=0.001)
        cost = model.entry_cost(price=100.0, quantity=10)
        assert cost == 100.0 * 10 * 0.001  # $1.0

    def test_sell_commission(self):
        model = USCommissionModel(commission_rate=0.001)
        cost = model.exit_cost(price=100.0, quantity=10)
        assert cost == 100.0 * 10 * 0.001

    def test_custom_rate(self):
        model = USCommissionModel(commission_rate=0.002)
        assert model.entry_cost(100.0, 10) == 2.0

class TestKRXCommissionModel:
    def test_buy_commission(self):
        """매수: 위탁수수료만"""
        model = KRXCommissionModel(brokerage_rate=0.00015)
        cost = model.entry_cost(price=70000.0, quantity=10)
        assert cost == 70000.0 * 10 * 0.00015

    def test_sell_commission(self):
        """매도: 위탁수수료 + 증권거래세"""
        model = KRXCommissionModel(brokerage_rate=0.00015, transaction_tax_rate=0.0018)
        cost = model.exit_cost(price=70000.0, quantity=10)
        expected = 70000.0 * 10 * (0.00015 + 0.0018)
        assert abs(cost - expected) < 0.01

    def test_sell_has_higher_cost_than_buy(self):
        """매도 비용 > 매수 비용 (거래세 때문)"""
        model = KRXCommissionModel()
        assert model.exit_cost(70000.0, 10) > model.entry_cost(70000.0, 10)

class TestCommissionModelFactory:
    def test_get_us_model(self):
        model = CommissionModel.for_currency("USD")
        assert isinstance(model, USCommissionModel)

    def test_get_kr_model(self):
        model = CommissionModel.for_currency("KRW")
        assert isinstance(model, KRXCommissionModel)

    def test_us_model_with_custom_rate(self):
        """factory에 commission_rate 오버라이드 전달"""
        model = CommissionModel.for_currency("USD", commission_rate=0.002)
        assert isinstance(model, USCommissionModel)
        assert model.entry_cost(100.0, 10) == 2.0

    def test_unknown_currency_defaults_to_us(self):
        model = CommissionModel.for_currency("EUR")
        assert isinstance(model, USCommissionModel)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.12 -m pytest tests/test_commission.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Implement commission models**

```python
# src/commission.py
"""시장별 수수료 모델

US: 단일 수수료율 (매수/매도 동일)
KRX: 매수(위탁수수료) + 매도(위탁수수료 + 증권거래세 0.18%)
"""

from abc import ABC, abstractmethod


class CommissionModel(ABC):
    @abstractmethod
    def entry_cost(self, price: float, quantity: int) -> float:
        """매수 수수료"""
        ...

    @abstractmethod
    def exit_cost(self, price: float, quantity: int) -> float:
        """매도 수수료"""
        ...

    def total_cost(self, entry_price: float, exit_price: float, quantity: int) -> float:
        return self.entry_cost(entry_price, quantity) + self.exit_cost(exit_price, quantity)

    @staticmethod
    def for_currency(currency: str, commission_rate: float = 0.001) -> "CommissionModel":
        """통화에 맞는 수수료 모델 생성.

        Args:
            currency: "USD" or "KRW"
            commission_rate: US 시장 수수료율 오버라이드 (BacktestConfig.commission_pct 전달용)
        """
        if currency == "KRW":
            return KRXCommissionModel()
        return USCommissionModel(commission_rate=commission_rate)


class USCommissionModel(CommissionModel):
    """US 시장: 매수/매도 동일 수수료율"""

    def __init__(self, commission_rate: float = 0.001):
        self.commission_rate = commission_rate

    def entry_cost(self, price: float, quantity: int) -> float:
        return price * quantity * self.commission_rate

    def exit_cost(self, price: float, quantity: int) -> float:
        return price * quantity * self.commission_rate


class KRXCommissionModel(CommissionModel):
    """한국거래소: 매수(위탁수수료) + 매도(위탁수수료 + 증권거래세)

    2026년 기준:
    - 위탁수수료: 약 0.015% (증권사별 상이, 온라인 기준)
    - 증권거래세: 0.18% (KOSPI/KOSDAQ 동일, 2026년)
    """

    def __init__(
        self,
        brokerage_rate: float = 0.00015,
        transaction_tax_rate: float = 0.0018,
    ):
        self.brokerage_rate = brokerage_rate
        self.transaction_tax_rate = transaction_tax_rate

    def entry_cost(self, price: float, quantity: int) -> float:
        return price * quantity * self.brokerage_rate

    def exit_cost(self, price: float, quantity: int) -> float:
        return price * quantity * (self.brokerage_rate + self.transaction_tax_rate)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.12 -m pytest tests/test_commission.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/commission.py tests/test_commission.py
git commit -m "[#220] feat: 시장별 수수료 모델 (US/KRX 증권거래세)"
```

### Task 3: TurtleBacktester에 CommissionModel 통합 (commission_pct 제거)

**Files:**
- Modify: `src/backtester.py:4,17,41-54,77-80,338,370,393`
- Modify: `tests/test_backtester.py`
- NOT modified: `scripts/run_backtest.py` (commission_pct를 BacktestConfig에 전달 → 자동 소비)
- NOT modified: `pages/backtest.py` (currency 기본값 "USD" 사용, UI 다통화는 후속 이슈)

**Important (C2/C3 fix):** `commission_pct`의 모든 직접 참조를 `CommissionModel`로 교체.
기존 `BacktestConfig.commission_pct`는 유지하되, `TurtleBacktester`는 오직 `self.commission_model`만 사용.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtester.py - 추가
from src.commission import KRXCommissionModel, USCommissionModel

class TestCommissionModelIntegration:
    def test_default_config_uses_us_commission(self):
        config = BacktestConfig()
        bt = TurtleBacktester(config)
        assert isinstance(bt.commission_model, USCommissionModel)

    def test_commission_pct_passed_to_model(self):
        """BacktestConfig.commission_pct가 CommissionModel에 전달됨"""
        config = BacktestConfig(commission_pct=0.002)
        bt = TurtleBacktester(config)
        assert bt.commission_model.entry_cost(100.0, 10) == 2.0

    def test_krw_currency_uses_krx_commission(self):
        config = BacktestConfig(initial_capital=100_000_000.0)
        bt = TurtleBacktester(config, currency="KRW")
        assert isinstance(bt.commission_model, KRXCommissionModel)

    def test_krw_commission_ignores_commission_pct(self):
        """KRW 모델은 config.commission_pct를 무시하고 거래세 모델 사용"""
        config = BacktestConfig(commission_pct=0.005)  # ignored for KRW
        bt = TurtleBacktester(config, currency="KRW")
        assert isinstance(bt.commission_model, KRXCommissionModel)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.12 -m pytest tests/test_backtester.py -k "CommissionModel" -v`
Expected: FAIL

- [ ] **Step 3: Update TurtleBacktester.__init__ and commission usage**

```python
# src/backtester.py - imports 추가
from .commission import CommissionModel

# TurtleBacktester.__init__ 변경
def __init__(
    self,
    config: BacktestConfig,
    symbol_groups: Optional[Dict[str, AssetGroup]] = None,
    currency: str = "USD",
):
    self.config = config
    self.currency = currency
    self.account = AccountState(initial_capital=config.initial_capital, currency=currency)
    self.commission_model = CommissionModel.for_currency(
        currency, commission_rate=config.commission_pct
    )
    self.pyramid_manager = PyramidManager(...)
    # ... rest unchanged
```

Replace ALL `self.config.commission_pct` references in backtester:

**_open_position (line ~338):**
```python
# OLD: cost = unit_size * price * (1 + self.config.commission_pct)
# NEW:
commission = self.commission_model.entry_cost(price, unit_size)
cost = unit_size * price + commission
```

**_add_pyramid (line ~370):**
```python
# OLD: cost = unit_size * price * (1 + self.config.commission_pct)
# NEW:
commission = self.commission_model.entry_cost(price, unit_size)
cost = unit_size * price + commission
```

**_close_position (line ~393):**
```python
# OLD: pnl -= price * total_quantity * self.config.commission_pct
# NEW:
pnl -= self.commission_model.exit_cost(price, total_quantity)
```

- [ ] **Step 4: Verify no remaining direct commission_pct usage in backtester**

Run: `grep -n "commission_pct" src/backtester.py`
Expected: Only in `BacktestConfig` field definition, NOT in TurtleBacktester methods.

- [ ] **Step 5: Update run_backtest.py**

`run_backtest.py` line 103 `commission_pct=args.commission` — 이것은 `BacktestConfig`에 전달되므로
`TurtleBacktester`에서 `CommissionModel.for_currency()`로 자동 소비. 변경 불필요.

- [ ] **Step 6: Run full test suite**

Run: `python3.12 -m pytest tests/ -v --tb=short`
Expected: PASS (기존 테스트 backward compat 유지 — commission_pct는 config에 남아있고 model이 소비)

- [ ] **Step 7: Commit**

```bash
git add src/backtester.py tests/test_backtester.py
git commit -m "[#220] refactor: commission_pct → CommissionModel 일원화"
```

---

## Chunk 2: Portfolio Separation — Per-Currency AccountState & Backtester

### File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/position_sizer.py:35` | `AccountState.currency` 필드 |
| Create | `src/multi_currency_backtester.py` | 통화별 백테스터 오케스트레이터 |
| Modify | `tests/test_position_sizer.py` | currency 테스트 |
| Create | `tests/test_multi_currency_backtester.py` | 통합 테스트 |

### Task 4: AccountState에 currency 필드 추가

**Files:**
- Modify: `src/position_sizer.py:35-52`
- Modify: `tests/test_position_sizer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_position_sizer.py - 추가
class TestAccountStateCurrency:
    def test_default_currency_usd(self):
        acc = AccountState(initial_capital=100000.0)
        assert acc.currency == "USD"

    def test_krw_account(self):
        acc = AccountState(initial_capital=100_000_000.0, currency="KRW")
        assert acc.currency == "KRW"
        assert acc.initial_capital == 100_000_000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.12 -m pytest tests/test_position_sizer.py -k "Currency" -v`
Expected: FAIL

- [ ] **Step 3: Add currency field to AccountState**

```python
@dataclass
class AccountState:
    initial_capital: float
    currency: str = "USD"
    current_equity: float = 0.0
    cash: float = 0.0
    positions: Dict[str, LivePosition] = field(default_factory=dict)
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    realized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
```

- [ ] **Step 4: Run tests**

Run: `python3.12 -m pytest tests/test_position_sizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/position_sizer.py tests/test_position_sizer.py
git commit -m "[#220] feat: AccountState에 currency 필드 추가"
```

### Task 5: MultiCurrencyBacktester 오케스트레이터

**Files:**
- Create: `src/multi_currency_backtester.py`
- Create: `tests/test_multi_currency_backtester.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_multi_currency_backtester.py
import pandas as pd
from src.multi_currency_backtester import MultiCurrencyBacktester, MultiCurrencyResult
from src.backtester import BacktestConfig
from src.commission import KRXCommissionModel, USCommissionModel

def _make_ohlcv(prices: list, start_date: str = "2024-01-01") -> pd.DataFrame:
    dates = pd.date_range(start_date, periods=len(prices), freq="B")
    return pd.DataFrame({
        "date": dates,
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": [1000000] * len(prices),
    })

class TestMultiCurrencyBacktester:
    def test_separates_data_by_currency(self):
        """USD/KRW 데이터를 통화별로 분리"""
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
            krw_config=BacktestConfig(initial_capital=100_000_000.0),
        )
        data = {
            "SPY": _make_ohlcv([400 + i for i in range(60)]),
            "005930.KS": _make_ohlcv([70000 + i * 100 for i in range(60)]),
        }
        currency_map = {"SPY": "USD", "005930.KS": "KRW"}
        usd_data, krw_data = mcbt._split_by_currency(data, currency_map)
        assert "SPY" in usd_data
        assert "005930.KS" in krw_data
        assert "SPY" not in krw_data
        assert "005930.KS" not in usd_data

    def test_independent_equity(self):
        """각 통화 포트폴리오가 독립적인 equity를 가짐"""
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
            krw_config=BacktestConfig(initial_capital=100_000_000.0),
        )
        assert mcbt.usd_backtester is not None
        assert mcbt.krw_backtester is not None
        assert mcbt.usd_backtester.account.currency == "USD"
        assert mcbt.krw_backtester.account.currency == "KRW"

    def test_usd_only(self):
        """USD만 설정하면 KRW 백테스터는 None"""
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
        )
        assert mcbt.usd_backtester is not None
        assert mcbt.krw_backtester is None

    def test_result_contains_only_active_currencies(self):
        """설정된 통화만 결과에 포함"""
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
        )
        result = mcbt.run({}, {})
        assert "KRW" not in result.results

    def test_usd_uses_us_commission(self):
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
            krw_config=BacktestConfig(initial_capital=100_000_000.0),
        )
        assert isinstance(mcbt.usd_backtester.commission_model, USCommissionModel)
        assert isinstance(mcbt.krw_backtester.commission_model, KRXCommissionModel)

    def test_n_exposure_independent(self):
        """각 통화 PortfolioRiskManager가 독립 N-exposure (둘 다 max=10.0)"""
        mcbt = MultiCurrencyBacktester(
            usd_config=BacktestConfig(initial_capital=100000.0),
            krw_config=BacktestConfig(initial_capital=100_000_000.0),
            usd_symbol_groups={"SPY": "us_equity"},
            krw_symbol_groups={"005930.KS": "kr_equity"},
        )
        # 독립 RiskManager 인스턴스
        assert mcbt.usd_backtester.risk_manager is not mcbt.krw_backtester.risk_manager
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.12 -m pytest tests/test_multi_currency_backtester.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Implement MultiCurrencyBacktester**

```python
# src/multi_currency_backtester.py
"""다통화 포트폴리오 백테스터 오케스트레이터

각 통화(USD/KRW)에 대해 독립적인 TurtleBacktester를 실행한다.
- 독립 AccountState (통화별 자본)
- 독립 PortfolioRiskManager (동일 한도, 통화 내 동질적 N값)
- 독립 CommissionModel (US: 단일 수수료, KRX: 위탁수수료 + 거래세)
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import pandas as pd

from .backtester import BacktestConfig, BacktestResult, TurtleBacktester
from .types import AssetGroup


@dataclass
class MultiCurrencyResult:
    usd_result: Optional[BacktestResult] = None
    krw_result: Optional[BacktestResult] = None

    @property
    def results(self) -> Dict[str, BacktestResult]:
        out = {}
        if self.usd_result:
            out["USD"] = self.usd_result
        if self.krw_result:
            out["KRW"] = self.krw_result
        return out


class MultiCurrencyBacktester:
    """통화별 분리 백테스터.

    N-exposure 한도: 양쪽 모두 max_total_n_exposure=10.0 사용.
    근거: 통화별로 PortfolioRiskManager가 독립이므로, 각 통화 내에서
    N값 스케일이 동질적 (USD: ATR ~$3-5, KRW: ATR ~1000-3000원).
    """

    def __init__(
        self,
        usd_config: Optional[BacktestConfig] = None,
        krw_config: Optional[BacktestConfig] = None,
        usd_symbol_groups: Optional[Dict[str, AssetGroup]] = None,
        krw_symbol_groups: Optional[Dict[str, AssetGroup]] = None,
    ):
        self.usd_backtester: Optional[TurtleBacktester] = None
        self.krw_backtester: Optional[TurtleBacktester] = None

        if usd_config:
            self.usd_backtester = TurtleBacktester(
                usd_config,
                symbol_groups=usd_symbol_groups,
                currency="USD",
            )

        if krw_config:
            self.krw_backtester = TurtleBacktester(
                krw_config,
                symbol_groups=krw_symbol_groups,
                currency="KRW",
            )

    def _split_by_currency(
        self,
        data: Dict[str, pd.DataFrame],
        currency_map: Dict[str, str],
    ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]:
        """데이터를 USD/KRW로 분리"""
        usd_data = {s: df for s, df in data.items() if currency_map.get(s, "USD") == "USD"}
        krw_data = {s: df for s, df in data.items() if currency_map.get(s) == "KRW"}
        return usd_data, krw_data

    def run(
        self,
        data: Dict[str, pd.DataFrame],
        currency_map: Dict[str, str],
    ) -> MultiCurrencyResult:
        """통화별 독립 백테스트 실행"""
        usd_data, krw_data = self._split_by_currency(data, currency_map)
        result = MultiCurrencyResult()

        if self.usd_backtester and usd_data:
            result.usd_result = self.usd_backtester.run(usd_data)

        if self.krw_backtester and krw_data:
            result.krw_result = self.krw_backtester.run(krw_data)

        return result
```

- [ ] **Step 4: Run tests**

Run: `python3.12 -m pytest tests/test_multi_currency_backtester.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/multi_currency_backtester.py tests/test_multi_currency_backtester.py
git commit -m "[#220] feat: MultiCurrencyBacktester 오케스트레이터"
```

---

## Chunk 3: KRW Universe Expansion & Group Updates

### File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/types.py` | 9개 KR AssetGroup enum 추가 |
| Modify | `config/universe.yaml` | KRW 20종목 확대 |
| Modify | `config/correlation_groups.yaml` | KR 섹터별 상관그룹 |
| Modify | `src/universe_manager.py` | group_mapping에 KR 그룹 추가 |
| Modify | `src/script_helpers.py:34-53` | _GROUP_MAPPING에 KR 그룹 추가 (C4 fix) |
| Modify | `tests/test_universe_manager.py` | 기존 kr_equity 테스트 업데이트 (C5 fix) |

### Task 6: AssetGroup enum 확장 및 매핑 업데이트

**Files:**
- Modify: `src/types.py`
- Modify: `src/universe_manager.py:56-73`
- Modify: `src/script_helpers.py:34-53`
- Modify: `tests/test_universe_manager.py`

- [ ] **Step 1: Write failing test for new groups**

```python
# tests/test_universe_manager.py - 추가
from src.types import AssetGroup

def test_kr_asset_groups_exist():
    """KR 섹터 AssetGroup이 존재"""
    assert hasattr(AssetGroup, "KR_BATTERY")
    assert hasattr(AssetGroup, "KR_BIO")
    assert hasattr(AssetGroup, "KR_FINANCE")
    assert hasattr(AssetGroup, "KR_AUTO")
    assert hasattr(AssetGroup, "KR_CHEMICAL")
    assert hasattr(AssetGroup, "KR_TELECOM")
    assert hasattr(AssetGroup, "KR_CONGLOMERATE")
    assert hasattr(AssetGroup, "KR_PLATFORM")
    assert hasattr(AssetGroup, "KR_INDEX")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.12 -m pytest tests/test_universe_manager.py -k "kr_asset_groups" -v`
Expected: FAIL

- [ ] **Step 3: Add KR AssetGroup enums to types.py**

```python
# src/types.py - AssetGroup class에 추가
KR_BATTERY = "kr_battery"
KR_BIO = "kr_bio"
KR_FINANCE = "kr_finance"
KR_AUTO = "kr_auto"
KR_CHEMICAL = "kr_chemical"
KR_TELECOM = "kr_telecom"
KR_CONGLOMERATE = "kr_conglomerate"
KR_PLATFORM = "kr_platform"
KR_INDEX = "kr_index"
```

- [ ] **Step 4: Update universe_manager.py group_mapping**

```python
# src/universe_manager.py - group_mapping dict에 추가
"kr_battery": AssetGroup.KR_BATTERY,
"kr_bio": AssetGroup.KR_BIO,
"kr_finance": AssetGroup.KR_FINANCE,
"kr_auto": AssetGroup.KR_AUTO,
"kr_chemical": AssetGroup.KR_CHEMICAL,
"kr_telecom": AssetGroup.KR_TELECOM,
"kr_conglomerate": AssetGroup.KR_CONGLOMERATE,
"kr_platform": AssetGroup.KR_PLATFORM,
"kr_index": AssetGroup.KR_INDEX,
```

- [ ] **Step 5: Update script_helpers._GROUP_MAPPING (C4 fix)**

```python
# src/script_helpers.py - _GROUP_MAPPING dict에 추가
"kr_battery": AssetGroup.KR_BATTERY,
"kr_bio": AssetGroup.KR_BIO,
"kr_finance": AssetGroup.KR_FINANCE,
"kr_auto": AssetGroup.KR_AUTO,
"kr_chemical": AssetGroup.KR_CHEMICAL,
"kr_telecom": AssetGroup.KR_TELECOM,
"kr_conglomerate": AssetGroup.KR_CONGLOMERATE,
"kr_platform": AssetGroup.KR_PLATFORM,
"kr_index": AssetGroup.KR_INDEX,
```

- [ ] **Step 6: Run tests**

Run: `python3.12 -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/types.py src/universe_manager.py src/script_helpers.py tests/test_universe_manager.py
git commit -m "[#220] feat: 9개 KR AssetGroup enum 추가 + 매핑 동기화"
```

### Task 7: KRW 유니버스 종목 확대 (5→20종목)

**Files:**
- Modify: `config/universe.yaml`
- Modify: `config/correlation_groups.yaml`
- Modify: `tests/test_universe_manager.py` (C5 fix: 기존 테스트 업데이트)

종목 선정 기준:
- 시가총액 5조원+ (KOSPI) / 1조원+ (KOSDAQ)
- 일평균 거래대금 100억원+
- 10섹터 분산: 반도체, 2차전지, 바이오, 금융, 자동차, 화학, 통신, 지주, 플랫폼, 지수ETF
- 전부 Long-only (`short_restricted: true`)

- [ ] **Step 1: Update universe.yaml — KR 종목 확대**

기존 `kr_equity` 카테고리를 섹터별로 분리:

```yaml
  # 기존 kr_equity를 세분화
  kr_equity:
    - {symbol: "005930.KS", name: "삼성전자", group: kr_equity, short_restricted: true}
    - {symbol: "000660.KS", name: "SK하이닉스", group: kr_equity, short_restricted: true}
  kr_battery:
    - {symbol: "373220.KS", name: "LG에너지솔루션", group: kr_battery, short_restricted: true}
    - {symbol: "006400.KS", name: "삼성SDI", group: kr_battery, short_restricted: true}
  kr_bio:
    - {symbol: "207940.KS", name: "삼성바이오로직스", group: kr_bio, short_restricted: true}
    - {symbol: "068270.KS", name: "셀트리온", group: kr_bio, short_restricted: true}
  kr_finance:
    - {symbol: "105560.KS", name: "KB금융", group: kr_finance, short_restricted: true}
    - {symbol: "055550.KS", name: "신한지주", group: kr_finance, short_restricted: true}
  kr_auto:
    - {symbol: "005380.KS", name: "현대차", group: kr_auto, short_restricted: true}
    - {symbol: "000270.KS", name: "기아", group: kr_auto, short_restricted: true}
  kr_chemical:
    - {symbol: "051910.KS", name: "LG화학", group: kr_chemical, short_restricted: true}
    - {symbol: "010130.KS", name: "고려아연", group: kr_chemical, short_restricted: true}
  kr_telecom:
    - {symbol: "017670.KS", name: "SK텔레콤", group: kr_telecom, short_restricted: true}
    - {symbol: "030200.KS", name: "KT", group: kr_telecom, short_restricted: true}
  kr_conglomerate:
    - {symbol: "034730.KS", name: "SK", group: kr_conglomerate, short_restricted: true}
    - {symbol: "003550.KS", name: "LG", group: kr_conglomerate, short_restricted: true}
  kr_platform:
    - {symbol: "035420.KS", name: "NAVER", group: kr_platform, short_restricted: true}
    - {symbol: "035720.KS", name: "카카오", group: kr_platform, short_restricted: true}
  kr_index:
    - {symbol: "069500.KS", name: "KODEX 200", group: kr_index, short_restricted: true}
    - {symbol: "229200.KS", name: "KODEX 코스닥150", group: kr_index, short_restricted: true}
```

- [ ] **Step 2: Update correlation_groups.yaml**

기존 `kr_equity` 그룹(5종목)을 10개 섹터 그룹으로 분리:

```yaml
  # 기존 kr_equity 5종목 → 2종목으로 축소 (나머지 새 그룹으로 이동)
  kr_equity:
    - "005930.KS"
    - "000660.KS"
  kr_battery:
    - "373220.KS"
    - "006400.KS"
  kr_bio:
    - "207940.KS"
    - "068270.KS"
  kr_finance:
    - "105560.KS"
    - "055550.KS"
  kr_auto:
    - "005380.KS"
    - "000270.KS"
  kr_chemical:
    - "051910.KS"
    - "010130.KS"
  kr_telecom:
    - "017670.KS"
    - "030200.KS"
  kr_conglomerate:
    - "034730.KS"
    - "003550.KS"
  kr_platform:
    - "035420.KS"
    - "035720.KS"
  kr_index:
    - "069500.KS"
    - "229200.KS"
```

- [ ] **Step 3: Update existing tests (C5 + N1 fix)**

**Exact test assertions that break (must update):**

1. `tests/test_universe_manager.py` line 419: class docstring `"""확장된 42개 심볼"""` → `"""확장된 57개 심볼"""`
2. `tests/test_universe_manager.py` line 427-429: `test_total_symbol_count` — `== 42` → `== 57`
3. `tests/test_universe_manager.py` line 431-464: `test_all_new_symbols_present` — 15개 KR 신규 심볼 추가:
   ```python
   new_symbols = [
       # 기존 24개 유지 ...
       # KR 신규 15개 추가 (기존 5개 KR 중 3개는 그룹 이동이지 신규 아님)
       "373220.KS", "006400.KS",   # kr_battery
       "207940.KS", "068270.KS",   # kr_bio
       "105560.KS", "055550.KS",   # kr_finance
       "005380.KS", "000270.KS",   # kr_auto
       "051910.KS", "010130.KS",   # kr_chemical
       "017670.KS", "030200.KS",   # kr_telecom
       "034730.KS", "003550.KS",   # kr_conglomerate
       "035720.KS",                # kr_platform (카카오)
   ]
   ```
4. `tests/test_universe_manager.py` line 466-480: `test_new_group_assignments` — KR 그룹 매핑 추가:
   ```python
   assert mapping["035420.KS"] == AssetGroup.KR_PLATFORM  # 이전: KR_EQUITY
   assert mapping["069500.KS"] == AssetGroup.KR_INDEX      # 이전: KR_EQUITY
   assert mapping["229200.KS"] == AssetGroup.KR_INDEX      # 이전: KR_EQUITY
   assert mapping["373220.KS"] == AssetGroup.KR_BATTERY
   assert mapping["005380.KS"] == AssetGroup.KR_AUTO
   ```
5. `tests/test_universe_manager.py` line 482-489: `test_existing_symbols_unchanged` —
   `005930.KS` remains `KR_EQUITY` (OK), but `035420.KS`는 이제 `KR_PLATFORM`이므로 이 테스트에서 제거하거나 업데이트

**New tests to add:**

```python
def test_krw_universe_has_20_symbols():
    um = self._load()
    krw = um.get_symbols_by_currency("KRW")
    assert len(krw) == 20

def test_kr_sector_groups_exist():
    um = self._load()
    kr_groups = {a.group for a in um.assets.values() if a.currency == "KRW"}
    assert len(kr_groups) >= 5  # 최소 5개 섹터 분산

def test_total_symbol_count():
    """37 US + 20 KR = 57 종목"""
    um = self._load()
    assert len(um.get_enabled_symbols()) == 57
```

- [ ] **Step 4: Run tests**

Run: `python3.12 -m pytest tests/test_universe_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/universe.yaml config/correlation_groups.yaml tests/test_universe_manager.py
git commit -m "[#220] feat: KRW 유니버스 확대 (5→20종목, 10섹터 분산)"
```

---

## Chunk 4: run_backtest.py Integration & Reporting

### Task 8: run_backtest.py에 다통화 모드 추가

**Files:**
- Modify: `scripts/run_backtest.py`
- Modify: `tests/test_run_backtest.py`

- [ ] **Step 1: Add CLI arguments**

```python
# scripts/run_backtest.py - parse_args()
# --symbols를 optional로 변경 (M4 fix)
parser.add_argument("--symbols", nargs="+", required=False, help="백테스트할 티커 심볼")

# 다통화 옵션 추가
parser.add_argument("--multi-currency", action="store_true",
                    help="통화별 분리 백테스트 (KRW/USD 독립 포트폴리오)")
parser.add_argument("--krw-capital", type=float, default=100_000_000.0,
                    help="KRW 포트폴리오 초기 자본 (기본: 1억원)")
parser.add_argument("--usd-capital", type=float, default=100_000.0,
                    help="USD 포트폴리오 초기 자본 (기본: $100,000)")
```

- [ ] **Step 2: Add validation for --symbols requirement**

```python
# main() 함수 내
args = parse_args()
if not args.multi_currency and not args.symbols:
    parser.error("--symbols is required unless --multi-currency is used")
```

- [ ] **Step 3: Implement multi-currency backtest flow**

```python
# scripts/run_backtest.py - main() 함수 내
if args.multi_currency:
    from src.multi_currency_backtester import MultiCurrencyBacktester

    um = UniverseManager(yaml_path=str(Path(__file__).parent.parent / "config" / "universe.yaml"))
    currency_map = um.get_currency_map()

    # 심볼 결정: --symbols 지정 시 해당 심볼만, 아니면 전체 유니버스
    if args.symbols:
        symbols = args.symbols
    else:
        symbols = um.get_enabled_symbols()

    data = fetch_data(symbols, args.period, args.verbose)

    full_mapping = um.get_group_mapping()
    usd_symbols = {s for s in data if currency_map.get(s, "USD") == "USD"}
    krw_symbols = {s for s in data if currency_map.get(s) == "KRW"}

    usd_groups = {s: full_mapping[s] for s in usd_symbols if s in full_mapping} or None
    krw_groups = {s: full_mapping[s] for s in krw_symbols if s in full_mapping} or None

    usd_config = BacktestConfig(
        initial_capital=args.usd_capital,
        risk_percent=args.risk,
        system=args.system,
        use_filter=not args.no_filter,
        commission_pct=args.commission,
    ) if usd_symbols else None

    krw_config = BacktestConfig(
        initial_capital=args.krw_capital,
        risk_percent=args.risk,
        system=args.system,
        use_filter=not args.no_filter,
    ) if krw_symbols else None

    mcbt = MultiCurrencyBacktester(
        usd_config=usd_config,
        krw_config=krw_config,
        usd_symbol_groups=usd_groups if not args.no_risk_limits else None,
        krw_symbol_groups=krw_groups if not args.no_risk_limits else None,
    )
    mc_result = mcbt.run(data, currency_map)
    print_multi_currency_results(mc_result)
else:
    # 기존 단일 통화 로직 (변경 없음)
    ...
```

- [ ] **Step 4: Add multi-currency result printer**

```python
def print_multi_currency_results(mc_result):
    """통화별 백테스트 결과 출력"""
    for currency, result in mc_result.results.items():
        symbol = "₩" if currency == "KRW" else "$"
        print(f"\n{'=' * 60}")
        print(f"[{currency} Portfolio]")
        print(f"{'=' * 60}")
        print(f"  초기 자본:      {symbol}{result.config.initial_capital:,.0f}")
        print(f"  최종 자본:      {symbol}{result.final_equity:,.0f}")
        print(f"  총 수익률:      {result.total_return:.1%}")
        print(f"  CAGR:          {result.cagr:.1%}")
        print(f"  최대 낙폭:      {result.max_drawdown:.1%}")
        print(f"  샤프 비율:      {result.sharpe_ratio:.2f}")
        print(f"  총 거래:        {result.total_trades}")
        print(f"  승률:          {result.win_rate:.1%}")
        print(f"  수익 팩터:      {result.profit_factor:.2f}")
```

- [ ] **Step 5: Write test**

```python
# tests/test_run_backtest.py - 추가
def test_multi_currency_flag_requires_no_symbols(monkeypatch):
    """--multi-currency는 --symbols 없이도 동작"""
    from scripts.run_backtest import parse_args
    monkeypatch.setattr("sys.argv", ["run_backtest.py", "--multi-currency"])
    args = parse_args()
    assert args.multi_currency
    assert args.symbols is None
```

- [ ] **Step 6: Run tests**

Run: `python3.12 -m pytest tests/test_run_backtest.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/run_backtest.py tests/test_run_backtest.py
git commit -m "[#220] feat: run_backtest.py --multi-currency 모드 추가"
```

---

## Chunk 5: Final Verification & Lint

### Task 9: 코드 품질 점검 및 최종 검증

**Files:**
- All modified files

- [ ] **Step 1: Run ruff format**

Run: `python3.12 -m ruff format src/ tests/ scripts/`

- [ ] **Step 2: Run ruff check**

Run: `python3.12 -m ruff check src/ tests/ scripts/`

- [ ] **Step 3: Run full test suite**

Run: `python3.12 -m pytest tests/ -v --tb=short`
Expected: All tests PASS, no regressions

- [ ] **Step 4: Verify grep — no remaining direct commission_pct in backtester methods**

Run: `grep -n "self.config.commission_pct" src/backtester.py`
Expected: No matches (commission_pct only in BacktestConfig definition)

- [ ] **Step 5: Verify all _GROUP_MAPPING entries are in sync**

Run comparison:
```bash
python3.12 -c "
from src.universe_manager import UniverseManager
from src.script_helpers import _GROUP_MAPPING
um = UniverseManager(yaml_path='config/universe.yaml')
yaml_groups = set(a.group.value for a in um.assets.values())
mapping_groups = set(_GROUP_MAPPING.keys())
missing = yaml_groups - mapping_groups
if missing:
    print(f'MISSING in _GROUP_MAPPING: {missing}')
else:
    print('All groups mapped correctly')
"
```

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "[#220] chore: lint/format 정리 및 최종 검증"
```

---

## Rubric Score Assessment

| Dimension | Pre | Post | Target | Notes |
|-----------|-----|------|--------|-------|
| D1: Architecture | 5 | 20 | 17.5 | 통화별 AccountState 분리, CommissionModel, MultiCurrencyBacktester |
| D2: Korean Market | 4 | 16 | 14.0 | 20종목 10섹터, Long-only, 증권거래세+위탁수수료 |
| D3: Backtesting | 6 | 14 | 14.0 | 통화별 독립 실행, 날짜 정렬은 기존 코드가 심볼별 df_slice로 처리 |
| D4: Risk Mgmt | 4 | 17 | 14.0 | 독립 PortfolioRiskManager (동일 10.0 한도), 10그룹 상관군 |
| D5: Statistics | 3 | 5 | 10.5 | ❌ 미달 — Walk-forward, Monte Carlo는 후속 이슈 |
| **Total** | **22** | **72** | **75.0** | D5 미달로 전체 Pass 기준 미충족 — D5는 별도 이슈로 분리 |

**Note:** D5 (Statistical Validity)는 이 PR 범위 밖. Walk-forward, Monte Carlo, Benchmark 비교 등은 후속 이슈 #221(예정)로 분리.

## Dependencies

```
Task 1 (currency field) ──→ Task 4 (AccountState)
Task 2 (commission) ──────→ Task 3 (commission integration)
Task 3 + Task 4 ──→ Task 5 (MultiCurrencyBacktester)
Task 6 (AssetGroup enums) ──→ Task 7 (KRW universe)
Task 5 + Task 7 ──→ Task 8 (run_backtest.py)
All ──→ Task 9 (verification)
```

## Momus v1+v2 Issues Resolution

| ID | Fix | Where |
|----|-----|-------|
| C1 | N-exposure 10.0 유지 (통화별 독립 RM이므로 별도 스케일링 불필요) | Task 5 docstring |
| C2 | `commission_pct` 직접 참조 전부 `CommissionModel`로 교체 | Task 3 Step 3 |
| C3 | `CommissionModel.for_currency(currency, commission_rate=config.commission_pct)` | Task 3 Step 3 |
| C4 | `script_helpers._GROUP_MAPPING`에 9개 KR 그룹 추가 | Task 6 Step 5 |
| C5 | 기존 kr_equity 테스트 업데이트 (NAVER→kr_platform 등) | Task 7 Step 3 |
| M1 | `paper_trader.py`는 live 경로 — 별도 이슈로 분리 (scope boundary) | Plan header |
| M2 | FX-adjusted 합산 리포트 → 후속 이슈 분리 | Plan header |
| M3 | 날짜 정렬: 기존 backtester가 `df[df["date"] <= date]`로 심볼별 처리하므로 KRX 휴일도 자동 스킵 | Task 5 docstring |
| M4 | `--symbols` optional, `--multi-currency`시 전체 유니버스 기본 | Task 8 Step 1-2 |
| M5 | `commission_pct`는 config에만 존재, backtester는 `CommissionModel`만 사용 | Task 3 |
| M6 | `usd_backtester is not None` guard 추가 | Task 5 Step 1 |
| N1 | 기존 테스트 42→57 변경 5개소 명시적 나열 | Task 7 Step 3 |
| N3 | `_load_defaults` 8개 `Asset()` 전부 keyword arg 전환, `_load_from_csv` 수정 | Task 1 Step 3 |
| N4 | `_load_from_csv`에 currency suffix 추론 추가 | Task 1 Step 3 |
| N7 | YAML에 `currency` 필드 제거, 코드 추론으로 통일 | YAML examples |
| N8 | `sys.argv` → `monkeypatch.setattr` 변환 | Task 8 Step 5 |
| N9 | `pages/backtest.py` Task 3에서 제거, USD 기본값 사용 | Task 3 file list |
