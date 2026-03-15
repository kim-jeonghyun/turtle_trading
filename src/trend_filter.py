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
    blocked_regimes: list[MarketRegime] = field(default_factory=lambda: [MarketRegime.BEAR, MarketRegime.DECLINE])
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
    # KR 섹터: 모두 EWY (한국 시장 프록시)
    AssetGroup.KR_BATTERY: "EWY",
    AssetGroup.KR_BIO: "EWY",
    AssetGroup.KR_FINANCE: "EWY",
    AssetGroup.KR_AUTO: "EWY",
    AssetGroup.KR_CHEMICAL: "EWY",
    AssetGroup.KR_TELECOM: "EWY",
    AssetGroup.KR_CONGLOMERATE: "EWY",
    AssetGroup.KR_PLATFORM: "EWY",
    AssetGroup.KR_INDEX: "EWY",
    # CRYPTO: 매핑 없음 → regime=SIDEWAYS 폴백
}


def resolve_regime_proxy(asset_group: AssetGroup, config_override: Optional[str] = None) -> Optional[str]:
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

    def should_enter(self, regime: MarketRegime, er_value: float) -> TrendFilterResult:
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
                reason=f"{regime.value.upper()} regime blocked",
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
