# Universe Expansion Implementation Plan (v2)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand the Turtle Trading universe from 18 to 42 symbols across 14 asset groups, adding global equity indices, commodities, currencies, REITs, alternatives, and crypto ETFs to improve portfolio diversification per original Turtle Trading principles.

**Architecture:** Configuration-driven expansion. Add 6 new `AssetGroup` enum values for truly uncorrelated asset classes (EU_EQUITY, CHINA_EQUITY, COMMODITY_ENERGY, COMMODITY_AGRI, REIT, ALTERNATIVES). Update `universe.yaml` with 24 new symbols and redesign `correlation_groups.yaml` with 16 fine-grained groups. Update `_GROUP_MAPPING` in `script_helpers.py` and `get_market_type()` in `data_fetcher.py` to bridge new symbols correctly.

**Tech Stack:** Python 3.12, PyYAML, pytest, existing modules (types.py, universe_manager.py, script_helpers.py, risk_manager.py, data_fetcher.py)

**Data-driven decisions:** Liquidity analysis (all 45 candidates pass 100K+ avg daily volume) and 1Y correlation matrix analysis completed in `data/universe_analysis/`. Three high-correlation duplicates removed (FXI r=0.986 w/ MCHI, GLTR r=0.945 w/ SLV, EWG r=0.932 w/ VGK). COPX moved from commodity_metal to commodity_industrial based on COPX-EEM correlation 0.750 (equity-like behavior).

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| v1 | 2026-03-06 | Initial plan |
| v2 | 2026-03-06 | Fix symbol count 39→42. Add Task for `data_fetcher.py:get_market_type()`. Move COPX to own group (commodity_industrial). Merge Task 3+4 (correlation_groups + script_helpers). Add `max_total_n_exposure` design decision. Fix `git add -A`. Add real-config integration test. Add cross-group correlation warnings. |
| v2.1 | 2026-03-06 | Fix correlation group count 15→16 (inverse was miscounted). Clarify D1 commodity breakdown. |
| v2.2 | 2026-03-06 | Add data_store.py/backtester.py to no-changes-needed section. Add cron job safety note. Add fallback-detection test. Fix issue template "15개→16개". |

---

## Change Impact Summary

| File | Change Type | Risk |
|------|------------|------|
| `src/types.py` | Add 6 AssetGroup enum values | Low — additive |
| `config/universe.yaml` | Add 24 symbols in 10 new categories | Low — config only |
| `config/correlation_groups.yaml` | Redesign from 6 to 16 groups | Medium — risk limits affected |
| `src/universe_manager.py` | Add 6 entries to `group_mapping` | Low — additive |
| `src/script_helpers.py` | Add 9 entries to `_GROUP_MAPPING` | Low — additive |
| `src/data_fetcher.py` | Update `get_market_type()` hardcoded lists | Medium — data routing |
| `tests/test_types.py` | Update AssetGroup count assertion | Low |
| `tests/test_universe_manager.py` | Add tests for new groups + real config integration | Low |
| `tests/test_script_helpers.py` | Regression guard auto-passes | None |
| `tests/test_risk_manager.py` | Add multi-group integration test | Low |
| `tests/test_data_fetcher.py` | Add MarketType tests for new symbols | Low |

**No logic changes needed:** `risk_manager.py`, `go_live_check.py`, `auto_trader.py`, `data_store.py` (Parquet cache keyed by symbol string — additive), `backtester.py` (iterates over universe dynamically)

**Cron job safety:** All changes are additive. Existing symbols and their group assignments are unchanged. Running cron jobs (`check_positions.py`, `health_check.py`) will not be affected mid-deploy.

---

## Design Decisions (READ FIRST)

### D1: Symbol count — 42

8 us_equity + 5 kr_equity(+2) + 6 asia_equity + 2 china_equity + 1 eu_equity + 2 commodity_metal + 1 commodity_industrial + 2 commodity_energy + 1 commodity_agri + 3 bond(+2) + 2 currency + 1 reit + 1 alternatives + 2 crypto + 5 inverse = **42**

### D2: us_tech + us_equity share 6-unit limit — KEEP

`us_tech` (AAPL, NVDA, TSLA, MSFT) maps to `AssetGroup.US_EQUITY`, sharing a 6-unit limit with `us_equity` (SPY, QQQ, DIA, IWM). This means 8 symbols compete for 6 units.

**Rationale:** QQQ-SPY correlation is 0.974. AAPL/NVDA/TSLA/MSFT constitute ~40% of QQQ. The high correlation justifies a shared limit — holding 4 units of SPY + 4 units of AAPL would be excessive exposure to the same risk factor. The original Turtle system grouped correlated futures (e.g., multiple grain contracts) under single group limits for the same reason.

**Future consideration:** If individual stock picks diverge from index behavior (e.g., TSLA), consider promoting `us_tech` to `AssetGroup.US_TECH` in a future iteration.

### D3: max_total_n_exposure = 10.0 — KEEP (for now)

With 14 groups, theoretical max units = 14 × 6 = 84, but `max_units_direction` (12) already caps the portfolio at 12 long + 12 short = 24 units max. The N-exposure cap (10.0) provides an additional safety layer.

**Rationale:** N-exposure measures volatility-weighted risk. More symbols doesn't mean more N-exposure — it means more diversification within the same risk budget. The 10.0 cap ensures total portfolio volatility remains bounded regardless of symbol count. This aligns with Curtis Faith's original 1% risk-per-trade discipline.

**Monitoring:** After backtest with expanded universe, revisit if 10.0 proves too restrictive (signals rejected frequently).

### D4: COPX in commodity_industrial (not commodity_metal)

COPX-EEM correlation is 0.750, COPX-SPY is implicitly high. Copper miners behave like equities during risk-on/off cycles, unlike physical precious metals (GLD avg|r|=0.264). Placing COPX in `commodity_metal` with GLD/SLV would understate its equity correlation risk.

**Solution:** New YAML group `commodity_industrial` mapping to `AssetGroup.COMMODITY` (shared limit with GLD/SLV is acceptable since only 3 symbols total).

### D5: EEM cross-group correlation warning

EEM has |r| ≥ 0.75 with: MCHI (0.836), FXI (0.828), VGK (0.803), EWT (0.873), EWA (0.781). As a broad emerging markets ETF, it overlaps with asia_equity, china_equity, and eu_equity holdings.

**Mitigation:** EEM stays in `asia_equity` group (same 6-unit limit as EWJ, EWT, EWA, VNM, INDA). The risk manager's per-group limit prevents over-concentration. Cross-group correlation is a known limitation of the current per-AssetGroup limit system — a future enhancement would be a correlation-matrix-aware risk check.

### D6: BITO/ETHA are crypto ETFs but use yfinance (not ccxt)

`data_fetcher.py:get_market_type()` classifies BITO/ETHA as `US_STOCK` because they are US-listed ETFs. This is **correct** — they are NOT direct crypto (no "/" or "USDT" suffix) and should be fetched via yfinance, not ccxt. `MarketType.CRYPTO` is reserved for direct crypto pairs like BTC-USD.

---

### Task 1: Create GitHub Issue

**Step 1: Create issue**

```bash
gh issue create --title "유니버스 확장: 글로벌 지수/원자재/대체자산 ETF 추가 (18→42 심볼)" \
  --body "$(cat <<'EOF'
## 목표
터틀 트레이딩 원칙에 따라 비상관 자산군 분산을 위해 유니버스를 확장합니다.

## 변경 사항
- 24개 신규 심볼 추가 (아시아 6, 중국 2, 유럽 1, 원자재 5, 채권 2, 통화 2, 리츠 1, 대체전략 1, 크립토 2, 한국 지수 2)
- AssetGroup enum 6개 추가 (EU_EQUITY, CHINA_EQUITY, COMMODITY_ENERGY, COMMODITY_AGRI, REIT, ALTERNATIVES)
- correlation_groups.yaml 16개 그룹으로 재설계
- data_fetcher.py get_market_type() 신규 심볼 추가

## 데이터 근거
- 유동성: 전 후보 100K+ 일평균 거래량 통과
- 상관분석: 3개 중복 제거 (FXI, GLTR, EWG)
- 분석 결과: `data/universe_analysis/`

## 체크리스트
- [ ] AssetGroup enum 확장 + 테스트
- [ ] universe.yaml 42개 심볼
- [ ] correlation_groups.yaml 16개 그룹
- [ ] script_helpers.py _GROUP_MAPPING
- [ ] data_fetcher.py get_market_type()
- [ ] 통합 테스트 (리스크 한도, go_live_check)
- [ ] 전체 회귀 테스트 통과
EOF
)"
```

**Step 2: Create feature branch**

```bash
git checkout -b feature/issue-NNN-universe-expansion
```

---

### Task 2: Add New AssetGroup Enum Values

**Files:**
- Modify: `src/types.py:39-47`
- Modify: `tests/test_types.py:125-145`

**Step 1: Write the failing test**

```python
# In tests/test_types.py, class TestAssetGroup:
def test_asset_group_count(self):
    assert len(list(AssetGroup)) == 14  # was 8

def test_new_asset_groups_exist(self):
    assert AssetGroup("eu_equity") == AssetGroup.EU_EQUITY
    assert AssetGroup("china_equity") == AssetGroup.CHINA_EQUITY
    assert AssetGroup("commodity_energy") == AssetGroup.COMMODITY_ENERGY
    assert AssetGroup("commodity_agri") == AssetGroup.COMMODITY_AGRI
    assert AssetGroup("reit") == AssetGroup.REIT
    assert AssetGroup("alternatives") == AssetGroup.ALTERNATIVES
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_types.py::TestAssetGroup -v`
Expected: FAIL — `AssetGroup` has no member `EU_EQUITY`

**Step 3: Write minimal implementation**

Replace `AssetGroup` in `src/types.py`:

```python
class AssetGroup(SerializableEnum):
    KR_EQUITY = "kr_equity"
    US_EQUITY = "us_equity"
    ASIA_EQUITY = "asia_equity"
    EU_EQUITY = "eu_equity"
    CHINA_EQUITY = "china_equity"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    COMMODITY_ENERGY = "commodity_energy"
    COMMODITY_AGRI = "commodity_agri"
    BOND = "bond"
    INVERSE = "inverse"
    CURRENCY = "currency"
    REIT = "reit"
    ALTERNATIVES = "alternatives"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_types.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/types.py tests/test_types.py
git commit -m "[#NNN] feat: add 6 new AssetGroup enum values for universe expansion"
```

---

### Task 3: Update universe.yaml + universe_manager.py

**Files:**
- Modify: `config/universe.yaml`
- Modify: `src/universe_manager.py:56-65`
- Test: `tests/test_universe_manager.py`

**Step 1: Write the failing test**

Add to `tests/test_universe_manager.py`:

```python
class TestUniverseExpansion:
    """유니버스 확장 검증 (v2: 42 symbols)"""

    def test_total_symbol_count(self):
        um = UniverseManager(yaml_path="config/universe.yaml")
        symbols = um.get_enabled_symbols()
        assert len(symbols) == 42, f"Expected 42 symbols, got {len(symbols)}"

    def test_all_new_symbols_present(self):
        um = UniverseManager(yaml_path="config/universe.yaml")
        symbols = um.get_enabled_symbols()
        new_symbols = [
            # 한국 지수
            "069500.KS", "229200.KS",
            # 아시아/이머징
            "EWJ", "EWT", "EWA", "VNM", "EEM", "INDA",
            # 중국
            "MCHI", "ASHR",
            # 유럽
            "VGK",
            # 원자재
            "SLV", "USO", "UNG", "COPX", "DBA",
            # 채권
            "SHY", "TIP",
            # 통화
            "UUP", "FXY",
            # 리츠/대체/크립토
            "VNQ", "DBMF", "BITO", "ETHA",
        ]
        for sym in new_symbols:
            assert sym in symbols, f"{sym} missing from universe"

    def test_new_group_assignments(self):
        um = UniverseManager(yaml_path="config/universe.yaml")
        mapping = um.get_group_mapping()
        assert mapping["EWJ"] == AssetGroup.ASIA_EQUITY
        assert mapping["VGK"] == AssetGroup.EU_EQUITY
        assert mapping["MCHI"] == AssetGroup.CHINA_EQUITY
        assert mapping["ASHR"] == AssetGroup.CHINA_EQUITY
        assert mapping["USO"] == AssetGroup.COMMODITY_ENERGY
        assert mapping["DBA"] == AssetGroup.COMMODITY_AGRI
        assert mapping["VNQ"] == AssetGroup.REIT
        assert mapping["DBMF"] == AssetGroup.ALTERNATIVES
        assert mapping["BITO"] == AssetGroup.CRYPTO
        assert mapping["ETHA"] == AssetGroup.CRYPTO
        assert mapping["UUP"] == AssetGroup.CURRENCY
        assert mapping["FXY"] == AssetGroup.CURRENCY
        # COPX stays in COMMODITY (via commodity_industrial → COMMODITY mapping)
        assert mapping["COPX"] == AssetGroup.COMMODITY

    def test_existing_symbols_unchanged(self):
        """기존 18개 심볼이 그대로 존재하고 그룹 변경 없음"""
        um = UniverseManager(yaml_path="config/universe.yaml")
        mapping = um.get_group_mapping()
        assert mapping["SPY"] == AssetGroup.US_EQUITY
        assert mapping["005930.KS"] == AssetGroup.KR_EQUITY
        assert mapping["GLD"] == AssetGroup.COMMODITY
        assert mapping["TLT"] == AssetGroup.BOND
        assert mapping["SH"] == AssetGroup.INVERSE

    def test_no_silent_fallback_to_default_group(self):
        """YAML 그룹 오타로 인한 US_EQUITY 기본값 폴백이 없어야 함"""
        um = UniverseManager(yaml_path="config/universe.yaml")
        mapping = um.get_group_mapping()
        # US_EQUITY에 속하는 심볼은 us_equity/us_tech 소속만이어야 함
        expected_us = {"SPY", "QQQ", "DIA", "IWM", "AAPL", "NVDA", "TSLA", "MSFT"}
        actual_us = {s for s, g in mapping.items() if g == AssetGroup.US_EQUITY}
        assert actual_us == expected_us, f"Unexpected US_EQUITY symbols (possible fallback): {actual_us - expected_us}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_universe_manager.py::TestUniverseExpansion -v`
Expected: FAIL — only 18 symbols

**Step 3: Replace universe.yaml**

```yaml
# 거래 유니버스 설정
# 모든 거래 스크립트가 이 파일을 단일 심볼 소스로 사용
# 총 42개 심볼 (2026-03-06 확장, v2)

symbols:
  us_equity:
    - {symbol: SPY, name: "S&P 500 ETF", group: us_equity, short_restricted: false}
    - {symbol: QQQ, name: "Nasdaq 100 ETF", group: us_equity, short_restricted: false}
    - {symbol: DIA, name: "Dow Jones ETF", group: us_equity, short_restricted: false}
    - {symbol: IWM, name: "Russell 2000 ETF", group: us_equity, short_restricted: false}
    - {symbol: AAPL, name: "Apple", group: us_equity, short_restricted: false}
    - {symbol: NVDA, name: "NVIDIA", group: us_equity, short_restricted: false}
    - {symbol: TSLA, name: "Tesla", group: us_equity, short_restricted: false}
    - {symbol: MSFT, name: "Microsoft", group: us_equity, short_restricted: false}
  kr_equity:
    - {symbol: "005930.KS", name: "삼성전자", group: kr_equity, short_restricted: true}
    - {symbol: "000660.KS", name: "SK하이닉스", group: kr_equity, short_restricted: true}
    - {symbol: "035420.KS", name: "NAVER", group: kr_equity, short_restricted: true}
    - {symbol: "069500.KS", name: "KODEX 200", group: kr_equity, short_restricted: true}
    - {symbol: "229200.KS", name: "KODEX 코스닥150", group: kr_equity, short_restricted: true}
  asia_equity:
    - {symbol: EWJ, name: "iShares Japan ETF", group: asia_equity, short_restricted: false}
    - {symbol: EWT, name: "iShares Taiwan ETF", group: asia_equity, short_restricted: false}
    - {symbol: EWA, name: "iShares Australia ETF", group: asia_equity, short_restricted: false}
    - {symbol: VNM, name: "VanEck Vietnam ETF", group: asia_equity, short_restricted: false}
    - {symbol: EEM, name: "iShares Emerging Markets ETF", group: asia_equity, short_restricted: false}
    - {symbol: INDA, name: "iShares MSCI India ETF", group: asia_equity, short_restricted: false}
  china_equity:
    - {symbol: MCHI, name: "iShares MSCI China ETF", group: china_equity, short_restricted: false}
    - {symbol: ASHR, name: "Xtrackers CSI 300 China A-Shares ETF", group: china_equity, short_restricted: false}
  eu_equity:
    - {symbol: VGK, name: "Vanguard FTSE Europe ETF", group: eu_equity, short_restricted: false}
  commodity:
    - {symbol: GLD, name: "Gold ETF", group: commodity, short_restricted: false}
    - {symbol: SLV, name: "iShares Silver Trust", group: commodity, short_restricted: false}
  commodity_industrial:
    - {symbol: COPX, name: "Global X Copper Miners ETF", group: commodity_industrial, short_restricted: false}
  commodity_energy:
    - {symbol: USO, name: "United States Oil Fund", group: commodity_energy, short_restricted: false}
    - {symbol: UNG, name: "United States Natural Gas Fund", group: commodity_energy, short_restricted: false}
  commodity_agri:
    - {symbol: DBA, name: "Invesco DB Agriculture ETF", group: commodity_agri, short_restricted: false}
  bond:
    - {symbol: TLT, name: "Treasury 20+ ETF", group: bond, short_restricted: false}
    - {symbol: SHY, name: "iShares 1-3 Year Treasury ETF", group: bond, short_restricted: false}
    - {symbol: TIP, name: "iShares TIPS Bond ETF", group: bond, short_restricted: false}
  currency:
    - {symbol: UUP, name: "Invesco DB US Dollar Index", group: currency, short_restricted: false}
    - {symbol: FXY, name: "Invesco CurrencyShares Japanese Yen", group: currency, short_restricted: false}
  reit:
    - {symbol: VNQ, name: "Vanguard Real Estate ETF", group: reit, short_restricted: false}
  alternatives:
    - {symbol: DBMF, name: "iMGP DBi Managed Futures Strategy ETF", group: alternatives, short_restricted: false}
  crypto:
    - {symbol: BITO, name: "ProShares Bitcoin Strategy ETF", group: crypto, short_restricted: false}
    - {symbol: ETHA, name: "iShares Ethereum Trust ETF", group: crypto, short_restricted: false}
  inverse:
    - {symbol: SH, name: "S&P 500 Inverse", group: inverse, underlying: SPY, short_restricted: false}
    - {symbol: PSQ, name: "Nasdaq Inverse", group: inverse, underlying: QQQ, short_restricted: false}
    - {symbol: SDS, name: "S&P 500 2x Inverse", group: inverse, underlying: SPY, short_restricted: false}
    - {symbol: SQQQ, name: "Nasdaq 3x Inverse", group: inverse, underlying: QQQ, short_restricted: false}
    - {symbol: SPXU, name: "S&P 500 3x Inverse", group: inverse, underlying: SPY, short_restricted: false}
```

**Step 4: Update universe_manager.py group_mapping**

Replace `group_mapping` dict in `src/universe_manager.py:56-65`:

```python
group_mapping = {
    "us_equity": AssetGroup.US_EQUITY,
    "kr_equity": AssetGroup.KR_EQUITY,
    "asia_equity": AssetGroup.ASIA_EQUITY,
    "eu_equity": AssetGroup.EU_EQUITY,
    "china_equity": AssetGroup.CHINA_EQUITY,
    "crypto": AssetGroup.CRYPTO,
    "commodity": AssetGroup.COMMODITY,
    "commodity_industrial": AssetGroup.COMMODITY,
    "commodity_energy": AssetGroup.COMMODITY_ENERGY,
    "commodity_agri": AssetGroup.COMMODITY_AGRI,
    "bond": AssetGroup.BOND,
    "inverse": AssetGroup.INVERSE,
    "currency": AssetGroup.CURRENCY,
    "reit": AssetGroup.REIT,
    "alternatives": AssetGroup.ALTERNATIVES,
}
```

**Step 5: Run tests**

Run: `pytest tests/test_universe_manager.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add config/universe.yaml src/universe_manager.py tests/test_universe_manager.py
git commit -m "[#NNN] feat: expand universe to 42 symbols across 14 asset groups"
```

---

### Task 4: Redesign correlation_groups.yaml + Update _GROUP_MAPPING

Combined to avoid broken intermediate state where YAML has groups not yet in `_GROUP_MAPPING`.

**Files:**
- Modify: `config/correlation_groups.yaml`
- Modify: `src/script_helpers.py:34-43`
- Test: `tests/test_script_helpers.py` (existing regression guard)

**Step 1: Replace correlation_groups.yaml**

```yaml
# Asset correlation groups for portfolio risk management
# Each symbol maps to a group - grouped assets share the correlated group limit (6 units)
# Redesigned 2026-03-06: 6 → 16 groups for universe expansion (18 → 42 symbols)
#
# Cross-group correlation warnings (|r| >= 0.75, 1Y):
#   EEM ↔ EWT (0.873), MCHI (0.836), VGK (0.803) — broad EM overlaps multiple regions
#   EWA ↔ SPY (0.785), VGK (0.849) — Australia tracks global risk-on
#   COPX ↔ EEM (0.750) — copper miners are equity-like
#   TIP ↔ TLT (0.821) — both are treasuries, different inflation sensitivity

groups:
  us_equity:
    - SPY
    - QQQ
    - DIA
    - IWM
  us_tech:
    - AAPL
    - NVDA
    - TSLA
    - MSFT
  kr_equity:
    - "005930.KS"
    - "000660.KS"
    - "035420.KS"
    - "069500.KS"
    - "229200.KS"
  asia_equity:
    - EWJ
    - EWT
    - EWA
    - VNM
    - EEM
    - INDA
  china_equity:
    - MCHI
    - ASHR
  eu_equity:
    - VGK
  commodity_metal:
    - GLD
    - SLV
  commodity_industrial:
    - COPX
  commodity_energy:
    - USO
    - UNG
  commodity_agri:
    - DBA
  bond:
    - TLT
    - SHY
    - TIP
  currency:
    - UUP
    - FXY
  reit:
    - VNQ
  alternatives:
    - DBMF
  crypto:
    - BITO
    - ETHA
  inverse:
    - SH
    - PSQ
    - SDS
    - SQQQ
    - SPXU
```

**Step 2: Update _GROUP_MAPPING in script_helpers.py**

Replace `_GROUP_MAPPING` in `src/script_helpers.py:34-43`:

```python
_GROUP_MAPPING: dict[str, AssetGroup] = {
    "us_equity": AssetGroup.US_EQUITY,
    "us_etf": AssetGroup.US_EQUITY,
    "us_tech": AssetGroup.US_EQUITY,
    "kr_equity": AssetGroup.KR_EQUITY,
    "asia_equity": AssetGroup.ASIA_EQUITY,
    "china_equity": AssetGroup.CHINA_EQUITY,
    "eu_equity": AssetGroup.EU_EQUITY,
    "crypto": AssetGroup.CRYPTO,
    "commodity": AssetGroup.COMMODITY,
    "commodity_metal": AssetGroup.COMMODITY,
    "commodity_industrial": AssetGroup.COMMODITY,
    "commodity_energy": AssetGroup.COMMODITY_ENERGY,
    "commodity_agri": AssetGroup.COMMODITY_AGRI,
    "bond": AssetGroup.BOND,
    "inverse": AssetGroup.INVERSE,
    "currency": AssetGroup.CURRENCY,
    "reit": AssetGroup.REIT,
    "alternatives": AssetGroup.ALTERNATIVES,
}
```

**Step 3: Run regression tests**

Run: `pytest tests/test_script_helpers.py -v`
Expected: All PASS (including `test_all_yaml_groups_have_explicit_mapping`)

**Step 4: Run go_live_check consistency test**

Run: `pytest tests/test_go_live_check.py -v -k correlation`
Expected: All PASS

**Step 5: Commit**

```bash
git add config/correlation_groups.yaml src/script_helpers.py
git commit -m "[#NNN] feat: redesign correlation groups — 6 to 16 groups for 42-symbol universe"
```

---

### Task 5: Update data_fetcher.py get_market_type()

**Files:**
- Modify: `src/data_fetcher.py:42-45`
- Test: `tests/test_data_fetcher.py`

**Step 1: Write the failing test**

Add to `tests/test_data_fetcher.py`:

```python
from src.data_fetcher import MarketType, get_market_type

class TestGetMarketTypeExpanded:
    """확장 유니버스 심볼의 MarketType 분류 검증"""

    def test_new_commodity_symbols(self):
        assert get_market_type("COPX") == MarketType.COMMODITY
        assert get_market_type("DBA") == MarketType.COMMODITY

    def test_new_bond_symbols(self):
        assert get_market_type("TIP") == MarketType.BOND

    def test_crypto_etfs_are_us_stock(self):
        """BITO/ETHA는 US-listed ETF이므로 US_STOCK (CRYPTO가 아님)"""
        assert get_market_type("BITO") == MarketType.US_STOCK
        assert get_market_type("ETHA") == MarketType.US_STOCK

    def test_currency_etfs_are_us_stock(self):
        """통화 ETF는 US-listed이므로 US_STOCK"""
        assert get_market_type("UUP") == MarketType.US_STOCK
        assert get_market_type("FXY") == MarketType.US_STOCK

    def test_existing_classifications_unchanged(self):
        assert get_market_type("GLD") == MarketType.COMMODITY
        assert get_market_type("TLT") == MarketType.BOND
        assert get_market_type("005930.KS") == MarketType.KR_STOCK
        assert get_market_type("SPY") == MarketType.US_STOCK
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_fetcher.py::TestGetMarketTypeExpanded -v`
Expected: FAIL — `get_market_type("COPX")` returns `US_STOCK`, not `COMMODITY`

**Step 3: Update get_market_type()**

Update `src/data_fetcher.py:42-45`:

```python
if symbol in ["GLD", "SLV", "USO", "UNG", "DBA", "DBC", "COPX"]:
    return MarketType.COMMODITY
if symbol in ["TLT", "IEF", "SHY", "BND", "AGG", "LQD", "TIP"]:
    return MarketType.BOND
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_data_fetcher.py::TestGetMarketTypeExpanded -v`
Expected: All PASS

**Step 5: Run full data_fetcher tests**

Run: `pytest tests/test_data_fetcher.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/data_fetcher.py tests/test_data_fetcher.py
git commit -m "[#NNN] feat: update get_market_type() for expanded universe symbols"
```

---

### Task 6: Add Integration Tests for Expanded Risk Limits

**Files:**
- Modify: `tests/test_risk_manager.py`
- Modify: `tests/test_universe_manager.py`

**Step 1: Write risk manager integration test**

Add to `tests/test_risk_manager.py`:

```python
class TestExpandedUniverseRiskLimits:
    """확장 유니버스의 상관군 한도 검증"""

    def test_independent_groups_have_separate_limits(self):
        """비상관 자산군은 독립적 한도를 가진다"""
        symbol_groups = {
            "SPY": AssetGroup.US_EQUITY,
            "EWJ": AssetGroup.ASIA_EQUITY,
            "MCHI": AssetGroup.CHINA_EQUITY,
            "VGK": AssetGroup.EU_EQUITY,
            "USO": AssetGroup.COMMODITY_ENERGY,
            "DBA": AssetGroup.COMMODITY_AGRI,
            "VNQ": AssetGroup.REIT,
            "DBMF": AssetGroup.ALTERNATIVES,
            "BITO": AssetGroup.CRYPTO,
            "UUP": AssetGroup.CURRENCY,
        }
        rm = PortfolioRiskManager(symbol_groups=symbol_groups)

        for symbol in symbol_groups:
            ok, msg = rm.can_add_position(symbol, 1, 0.5, Direction.LONG)
            assert ok, f"{symbol} should be allowed: {msg}"
            rm.add_position(symbol, 1, 0.5, Direction.LONG)

        assert rm.state.long_units == 10

    def test_correlated_group_limit_enforced(self):
        """같은 상관군 내 종목은 6 unit 한도 공유"""
        symbol_groups = {
            "EWJ": AssetGroup.ASIA_EQUITY,
            "EWT": AssetGroup.ASIA_EQUITY,
            "EWA": AssetGroup.ASIA_EQUITY,
            "VNM": AssetGroup.ASIA_EQUITY,
            "EEM": AssetGroup.ASIA_EQUITY,
            "INDA": AssetGroup.ASIA_EQUITY,
        }
        rm = PortfolioRiskManager(symbol_groups=symbol_groups)

        for sym in list(symbol_groups.keys())[:6]:
            rm.add_position(sym, 1, 0.1, Direction.LONG)

        ok, msg = rm.can_add_position("EWJ", 1, 0.1, Direction.LONG)
        assert not ok
        assert "그룹 한도 초과" in msg

    def test_n_exposure_cap_with_many_groups(self):
        """N-exposure 10.0 캡은 다수 그룹에서도 작동"""
        symbol_groups = {
            "SPY": AssetGroup.US_EQUITY,
            "EWJ": AssetGroup.ASIA_EQUITY,
            "GLD": AssetGroup.COMMODITY,
            "TLT": AssetGroup.BOND,
            "VNQ": AssetGroup.REIT,
        }
        rm = PortfolioRiskManager(symbol_groups=symbol_groups)

        # 5 symbols × 1 unit × n_value=2.5 = 12.5 > 10.0
        for i, sym in enumerate(symbol_groups):
            if i < 4:  # 4 × 2.5 = 10.0 → exactly at limit
                rm.add_position(sym, 1, 2.5, Direction.LONG)

        # 5th would exceed N-exposure
        ok, msg = rm.can_add_position("VNQ", 1, 2.5, Direction.LONG)
        assert not ok
        assert "N 노출 한도 초과" in msg
```

**Step 2: Write real-config integration test**

Add to `tests/test_universe_manager.py`:

```python
class TestRealConfigConsistency:
    """실제 설정 파일 간 일관성 검증"""

    def test_all_universe_symbols_in_correlation_groups(self):
        """universe.yaml의 모든 심볼이 correlation_groups.yaml에 존재"""
        import yaml
        with open("config/universe.yaml") as f:
            universe = yaml.safe_load(f)
        with open("config/correlation_groups.yaml") as f:
            corr = yaml.safe_load(f)

        universe_symbols = set()
        for market_list in universe["symbols"].values():
            for entry in market_list:
                universe_symbols.add(str(entry["symbol"]))

        corr_symbols = set()
        for members in corr["groups"].values():
            corr_symbols.update(str(s) for s in members)

        missing = universe_symbols - corr_symbols
        assert not missing, f"Symbols in universe but not in correlation_groups: {missing}"
```

**Step 3: Run tests**

Run: `pytest tests/test_risk_manager.py::TestExpandedUniverseRiskLimits tests/test_universe_manager.py::TestRealConfigConsistency -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_risk_manager.py tests/test_universe_manager.py
git commit -m "[#NNN] test: add expanded universe risk + config consistency integration tests"
```

---

### Task 7: Full Regression Test Suite

**Step 1: Run full test suite**

Run: `pytest -v --tb=short`
Expected: All 1,097+ tests PASS (plus new tests)

**Step 2: Verify key integration points**

```bash
pytest tests/test_universe_manager.py tests/test_risk_manager.py tests/test_script_helpers.py tests/test_go_live_check.py tests/test_types.py tests/test_data_fetcher.py -v
```

---

### Task 8: Cleanup Temporary Files

**Files:**
- Delete: `scripts/analyze_universe_candidates.py`
- Delete: `check_dom.py`
- Delete: `fetch_chart.py`

**Step 1: Remove files**

```bash
git rm scripts/analyze_universe_candidates.py
rm check_dom.py fetch_chart.py
```

Note: `check_dom.py` and `fetch_chart.py` are untracked (shown in git status), so `rm` not `git rm`.

**Step 2: Commit**

```bash
git add scripts/analyze_universe_candidates.py
git commit -m "[#NNN] chore: remove temporary analysis and chart scripts"
```

---

### Task 9: Create PR

```bash
git push -u origin feature/issue-NNN-universe-expansion
gh pr create --title "[#NNN] feat: expand universe to 42 symbols across 14 asset groups" \
  --body "$(cat <<'EOF'
## Summary
- Expand trading universe from 18 to 42 symbols (+24)
- Add 6 new AssetGroup enum values (EU_EQUITY, CHINA_EQUITY, COMMODITY_ENERGY, COMMODITY_AGRI, REIT, ALTERNATIVES)
- Redesign correlation_groups.yaml from 6 to 16 groups
- Update data_fetcher.py get_market_type() for new commodity/bond symbols
- New asset classes: Asia/EM (6), China (2), Europe (1), Commodities (5), Bonds (2), Currency (2), REIT (1), Alternatives (1), Crypto (2), KR Index (2)

Fixes #NNN

## Data-Driven Decisions
- All 45 candidates passed liquidity check (100K+ avg daily volume)
- 3 duplicates removed via 1Y correlation analysis (FXI, GLTR, EWG)
- COPX moved to commodity_industrial (r=0.750 with EEM, equity-like behavior)
- Analysis artifacts: `data/universe_analysis/`

## Design Decisions
- us_tech + us_equity share 6-unit limit (QQQ-SPY r=0.974)
- max_total_n_exposure kept at 10.0 (volatility budget, not symbol count)
- BITO/ETHA classified as US_STOCK in data_fetcher (US-listed ETFs, not direct crypto)

## Test plan
- [ ] All existing tests pass (1,097+)
- [ ] New AssetGroup enum values serialize correctly
- [ ] UniverseManager loads 42 symbols with correct group assignments
- [ ] Correlation group regression guard passes (16 groups all mapped)
- [ ] Risk limit integration: independent groups, correlated limits, N-exposure cap
- [ ] Real config consistency: all universe symbols in correlation_groups
- [ ] data_fetcher MarketType classification for new symbols
- [ ] go_live_check correlation consistency passes

## Post-merge follow-up
- [ ] Run backtest with expanded universe (separate issue)
- [ ] Monitor max_total_n_exposure utilization
- [ ] Consider us_tech → US_TECH promotion if backtests show benefit

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
