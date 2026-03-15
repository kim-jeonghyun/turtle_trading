# Trend Quality Filter Design Spec

**Date**: 2026-03-13
**Status**: Approved (design review + agent council evaluation)
**Scores**: Gemini 88/100, Codex architecture-approved

## 1. Problem Statement

터틀 브레이크아웃 전략이 US 주식에서는 유효하나 (PF 1.54, MDD 30%) 아시아 ETF에서 실패 (PF 0.51, MDD 57%).

**근본 원인**: 아시아 ETF의 "stair-step" 가격 행동 — 상승 편향이 있지만 변동성이 높아 브레이크아웃 후 평균회귀가 2N 스톱을 반복적으로 트리거.

**대표 사례**: VNM (2025년) — 10거래 중 8건 손실, 대부분 stop_loss 청산.

## 2. Solution: Dual Trend Quality Filter

진입 전 두 가지 축으로 트렌드 품질을 검증:

1. **Macro (시장 레짐)**: 기존 `regime_detector.py`의 5단계 레짐으로 BEAR/DECLINE 시장 진입 차단
2. **Micro (종목별 ER)**: Kaufman의 Efficiency Ratio로 노이즈 대비 방향성 측정, 임계값 미달 시 차단

### 2.1 핵심 원칙

- **Entry-Only Block**: SELL(손절/청산)은 절대 차단하지 않음 (Guard Chain 일관성)
- **Default OFF**: `--trend-filter` 플래그로 opt-in (기존 백테스트 결과 보존)
- **Pure Logic**: TrendFilter는 판단만, 알림/로깅은 caller 책임

## 3. Architecture

### 3.1 모듈 구성

```
src/trend_filter.py    (신규) — TrendFilter 클래스
src/indicators.py      (수정) — calculate_efficiency_ratio() 추가
src/backtester.py      (수정) — _check_entry_signal()에 필터 주입
scripts/check_positions.py  (수정) — 라이브 경로에도 동일 필터 적용
```

### 3.2 Live/Backtest 동치성 (Council 피드백 반영)

Codex가 지적한 핵심 아키텍처 이슈: `check_positions.py`와 `backtester.py`는 equivalence 테스트로 묶여있으므로, **반드시 양쪽에 동일 필터를 적용**해야 함.

```
TrendFilter (공유 모듈)
  ├── backtester._check_entry_signal() 에서 호출
  └── check_positions.check_entry_signals() 에서 호출
```

### 3.3 데이터 흐름

```
[OHLCV data]
    │
    ├── indicators.calculate_efficiency_ratio(close, period=20)
    │       → ER 컬럼 (0.0 ~ 1.0)
    │
    ├── regime_detector.classify_regime(index_proxy_df)
    │       → RegimeSnapshot.regime → MarketRegime (BULL/RECOVERY/SIDEWAYS/DECLINE/BEAR)
    │
    └── TrendFilter.should_enter(regime, er_value)
            → TrendFilterResult(allowed, reason, regime, er_value)
                │
                ├── allowed=True  → 기존 브레이크아웃 로직 진행
                └── allowed=False → 진입 스킵 + "Filtered Signal" 로깅
```

## 4. Detailed Design

### 4.1 `src/indicators.py` — ER 함수 추가

```python
def calculate_efficiency_ratio(series: pd.Series, period: int = 20) -> pd.Series:
    """Kaufman Efficiency Ratio: |net_movement| / path_sum.

    0 = 완전한 횡보(choppy), 1 = 직선 추세(straight trend).
    """
    direction = abs(series - series.shift(period))
    volatility = abs(series.diff()).rolling(period).sum()
    return (direction / volatility.replace(0, float("nan"))).fillna(0)
```

### 4.2 `src/trend_filter.py` — 신규 모듈

```python
from dataclasses import dataclass, field
from typing import Optional

from src.types import MarketRegime


@dataclass
class TrendFilterConfig:
    er_period: int = 20
    er_threshold: float = 0.3
    blocked_regimes: list[MarketRegime] = field(
        default_factory=lambda: [MarketRegime.BEAR, MarketRegime.DECLINE]
    )
    sideways_er_boost: float = 0.1  # SIDEWAYS에서 ER 임계값 상향


@dataclass
class TrendFilterResult:
    allowed: bool
    reason: str
    regime: MarketRegime
    er_value: float


class TrendFilter:
    """듀얼 트렌드 품질 필터.

    Macro (시장 레짐) + Micro (종목별 ER) 이중 검증.
    Entry-Only: SELL은 절대 차단하지 않음.
    """

    def __init__(self, config: Optional[TrendFilterConfig] = None):
        self.config = config or TrendFilterConfig()
        self.stats = {"checked": 0, "blocked_regime": 0, "blocked_er": 0, "passed": 0}

    def get_filter_stats(self) -> "FilterStats":
        """stats dict → FilterStats dataclass 변환 (BacktestResult 포함용)."""
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

### 4.3 `src/backtester.py` — 필터 주입

`BacktestConfig`에 추가:
```python
use_trend_quality_filter: bool = False  # 기존 use_filter(System1 profit filter)와 구별
er_threshold: float = 0.3
regime_proxy_symbol: Optional[str] = None  # None이면 _resolve_regime_proxy()로 자산군별 기본값
```

`_check_entry_signal()` 내부, 브레이크아웃 판정 직전:
```python
if self.trend_filter:
    snapshot = self._get_regime_snapshot(row)  # classify_regime() → RegimeSnapshot
    regime = snapshot.regime                   # RegimeSnapshot → MarketRegime 추출
    er_value = row.get("er", 0.0)
    result = self.trend_filter.should_enter(regime, er_value)
    if not result.allowed:
        self._log_filtered_signal(symbol, row, result)  # Council 피드백: 로깅
        return None
```

### 4.4 `scripts/check_positions.py` — 라이브 경로 동치

`check_entry_signals()` 내부에 동일 패턴 적용:
```python
if trend_filter:
    result = trend_filter.should_enter(regime, er_value)
    if not result.allowed:
        logger.info(f"[TrendFilter] {symbol} 진입 차단: {result.reason}")
        continue
```

### 4.5 CLI 인터페이스

`scripts/run_backtest.py`:
```
--trend-filter      트렌드 품질 필터 활성화 (기본: OFF)
--er-threshold 0.3  ER 임계값 오버라이드
--regime-proxy SPY  레짐 판별용 인덱스 프록시 심볼
```

### 4.6 Index Proxy 전략 (Council 피드백 반영)

Gemini가 지적한 "Index Proxy Gap" 해결:

| AssetGroup | 기본 프록시 | 근거 |
|------------|-------------|------|
| US_EQUITY | SPY | S&P 500 대표 |
| US_TECH | SPY | QQQ 대비 SPY가 시장 전체 레짐에 적합 |
| KR_EQUITY | EWY | 한국 시장 ETF (yfinance 조회 가능) |
| ASIA_EQUITY | EEM | 이머징 마켓 대표 |
| CHINA_EQUITY | EEM | 중국 단독 인덱스 대신 EM 대표 사용 |
| EU_EQUITY | VGK | 유럽 시장 |
| COMMODITY | DBC | 원자재 종합 |
| COMMODITY_ENERGY | DBC | 원자재 종합 (에너지 하위) |
| COMMODITY_AGRI | DBC | 원자재 종합 (농산물 하위) |
| BOND | TLT | 미국 장기채 |
| CURRENCY | UUP | 달러 인덱스 ETF |
| REIT | VNQ | 미국 리츠 대표 |
| ALTERNATIVES | SPY | 대안 자산은 광역 시장 폴백 |
| INVERSE | SPY | 기초 시장 레짐 참조 |
| CRYPTO | _(없음)_ | yfinance 미지원 시 regime=SIDEWAYS 폴백 |

`BacktestConfig.regime_proxy_symbol`이 None이면 아래 해석 로직으로 자산군별 기본값 사용:

```python
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

def _resolve_regime_proxy(
    symbol: str, asset_group: AssetGroup, config_override: Optional[str]
) -> Optional[str]:
    """레짐 프록시 심볼 해석. config > 자산군 기본값 > None(SIDEWAYS 폴백)."""
    if config_override:
        return config_override
    return DEFAULT_REGIME_PROXIES.get(asset_group)
```

## 5. Filter Statistics & Logging (Council 피드백)

### 5.1 백테스트 결과에 포함

```python
@dataclass
class FilterStats:
    total_checked: int = 0
    blocked_by_regime: int = 0
    blocked_by_er: int = 0
    passed: int = 0
    block_rate: float = 0.0  # blocked / checked
```

`BacktestResult`에 `filter_stats: Optional[FilterStats]` 추가.
`run_backtest.py` 결과 출력 시 필터 통계 표시.

### 5.2 Filtered Signal 로깅

차단된 시그널을 별도 로그로 기록하여 "왜 거래하지 않았는가?" 디버깅 지원:
```
[TrendFilter] VNM 진입 차단: ER 0.18 < 0.30 (regime=SIDEWAYS, threshold=0.40)
```

### 5.3 ER 값 거래 로그 저장

`Trade` dataclass에 `er_at_entry: Optional[float]` 추가.
`Position` dataclass (`src/position_tracker.py`)에도 `er_at_entry: Optional[float]` 추가 — 라이브 포지션에서도 ER 추적.
백테스트 CSV 및 포지션 기록에 ER 값 포함 → 임계값 민감도 분석 가능.

## 6. Testing Strategy

### 6.1 Unit Tests (`tests/test_trend_filter.py`)

- `TrendFilter.should_enter()` 각 레짐별 동작
- ER 임계값 경계값 (0.2999 → blocked, 0.3001 → passed; float 정밀도 고려)
- SIDEWAYS boost 적용 확인
- stats 카운터 정확성

### 6.2 Indicator Tests (`tests/test_indicators.py` 확장)

- `calculate_efficiency_ratio()` 직선 데이터 → ER ≈ 1.0
- choppy 데이터 → ER < 0.3
- 빈 시리즈 / NaN 처리

### 6.3 Integration Tests

- 백테스터 + 필터: 동일 데이터에서 필터 ON/OFF 비교
- Live equivalence: `tests/test_backtester_live_equivalence.py` **기존 파일 확장** — trend filter 시나리오 추가하여 backtester와 check_positions 양쪽의 필터 판정 동치성 검증

### 6.4 Validation Backtests

필터 효과 검증 (구현 후):
```bash
# 필터 없이
python scripts/run_backtest.py --symbols EWJ EWT VNM EEM INDA EWA --period 5y --system 1

# 필터 적용
python scripts/run_backtest.py --symbols EWJ EWT VNM EEM INDA EWA --period 5y --system 1 --trend-filter

# US 주식 성과 유지 확인
python scripts/run_backtest.py --symbols SPY QQQ AAPL NVDA --period 5y --system 1 --trend-filter
```

**성공 기준:**
- 아시아 ETF: PF 개선 (0.51 → 0.8+) 또는 손실 거래 50%+ 감소
- US 주식: PF 유지 (±5% 이내)
- 전체 MDD 감소

## 7. Risks & Mitigations

| 리스크 | 심각도 | 완화 방안 |
|--------|--------|-----------|
| 기회비용 (volatile 시작 구간 놓침) | MEDIUM | ER threshold 자산군별 튜닝 가능 |
| 오버피팅 (threshold 최적화) | HIGH | 기본값 0.3 고정, walk-forward 검증 (WFO: IS 3년/OOS 1년, 4-fold rolling) |
| Live/Backtest divergence | HIGH | 공유 TrendFilter 모듈 + equivalence 테스트 |
| Index Proxy 데이터 부재 | LOW | 프록시 없으면 regime=SIDEWAYS 기본값 |
| Proxy fetch 실패 (라이브) | MEDIUM | data_fetcher timeout/exception → RegimeSnapshot(SIDEWAYS) 폴백 + 경고 로그 |

## 8. Scope & Non-Goals

**In Scope:**
- `src/trend_filter.py` 신규 모듈
- `src/indicators.py`에 ER 함수 추가
- `src/backtester.py` 필터 주입
- `scripts/check_positions.py` 라이브 경로 동치
- `scripts/run_backtest.py` CLI 플래그
- Unit + integration 테스트

**Out of Scope:**
- ER-Exit (진입 후 ER 하락 시 조기 청산) — 별도 이슈로 검토
- 자산군별 ER threshold 자동 최적화
- screener.py 통합 (향후 확장 가능)
- Dashboard UI 연동

## 9. Dependencies

- 기존 모듈: `regime_detector.py`, `market_breadth.py`, `indicators.py`, `types.py` (MarketRegime)
- 외부 라이브러리: 추가 없음 (pandas만 사용)
