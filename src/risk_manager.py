"""
포트폴리오 레벨 리스크 관리 모듈
- 단일 종목: 4 Units
- 상관관계 그룹: 6 Units
- 단일 방향: 12 Units
- 전체 N 노출: ≤ 10
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from src.types import AssetGroup, Direction


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


@dataclass
class PortfolioRiskState:
    units_by_symbol: Dict[str, int] = field(default_factory=dict)
    units_by_group: Dict[AssetGroup, int] = field(default_factory=dict)
    long_units: int = 0
    short_units: int = 0
    total_n_exposure: float = 0.0


class PortfolioRiskManager:
    def __init__(self, limits: Optional[RiskLimits] = None, symbol_groups: Optional[Dict[str, AssetGroup]] = None):
        self.limits = limits or RiskLimits()
        self.symbol_groups = symbol_groups or {}
        self.state = PortfolioRiskState()

    def get_group(self, symbol: str) -> AssetGroup:
        return self.symbol_groups.get(symbol, AssetGroup.US_EQUITY)

    def can_add_position(self, symbol: str, units: int, n_value: float, direction: Direction) -> Tuple[bool, str]:
        if n_value < 0:
            return False, f"N값이 음수입니다: {n_value}"
        if units <= 0:
            return False, f"유닛 수가 0 이하입니다: {units}"

        group = self.get_group(symbol)

        # 단일 종목 한도
        current = self.state.units_by_symbol.get(symbol, 0)
        if current + units > self.limits.max_units_per_market:
            return False, f"단일종목 한도 초과: {symbol}"

        # 그룹 한도
        group_units = self.state.units_by_group.get(group, 0)
        if group_units + units > self.limits.max_units_correlated:
            return False, f"그룹 한도 초과: {group.value}"

        # 방향 한도
        if direction == Direction.LONG:
            if self.state.long_units + units > self.limits.max_units_direction:
                return False, "롱 방향 한도 초과"
        else:
            if self.state.short_units + units > self.limits.max_units_direction:
                return False, "숏 방향 한도 초과"

        # N 노출 한도
        new_n_exposure = units  # Curtis Faith: N-노출 = 유닛 수 (ATR 무관)
        if self.state.total_n_exposure + new_n_exposure > self.limits.max_total_n_exposure:
            return False, "전체 N 노출 한도 초과"

        return True, "OK"

    def add_position(self, symbol: str, units: int, n_value: float, direction: Direction):
        if n_value < 0:
            raise ValueError(f"n_value must be non-negative, got {n_value}")
        if units <= 0:
            raise ValueError(f"units must be positive, got {units}")

        group = self.get_group(symbol)

        self.state.units_by_symbol[symbol] = self.state.units_by_symbol.get(symbol, 0) + units
        self.state.units_by_group[group] = self.state.units_by_group.get(group, 0) + units

        if direction == Direction.LONG:
            self.state.long_units += units
        else:
            self.state.short_units += units

        self.state.total_n_exposure += units  # Curtis Faith: N-노출 = 유닛 수 (ATR 무관)

    def remove_position(self, symbol: str, units: int, direction: Direction, n_value: float):
        """포지션 제거 시 리스크 상태 갱신.

        NOTE: n_value는 add_position 시점과 동일한 값을 전달해야 한다.
        불일치 시 total_n_exposure에 누적 오차가 발생할 수 있다.
        """
        if n_value < 0:
            raise ValueError(f"n_value must be non-negative, got {n_value}")
        if units <= 0:
            raise ValueError(f"units must be positive, got {units}")

        group = self.get_group(symbol)

        # 실제 보유 수량으로 제거량 클램핑 (공유 필드 과다 차감 방지)
        current_units = self.state.units_by_symbol.get(symbol, 0)
        actual_units = min(units, current_units)

        self.state.units_by_symbol[symbol] = current_units - actual_units
        self.state.units_by_group[group] = max(0, self.state.units_by_group.get(group, 0) - actual_units)

        if direction == Direction.LONG:
            self.state.long_units = max(0, self.state.long_units - actual_units)
        else:
            self.state.short_units = max(0, self.state.short_units - actual_units)

        # Curtis Faith: N-노출 = 유닛 수 (ATR 무관)
        self.state.total_n_exposure = max(0.0, self.state.total_n_exposure - actual_units)

    def get_risk_summary(self) -> Dict:
        return {
            "total_n_exposure": self.state.total_n_exposure,
            "long_units": self.state.long_units,
            "short_units": self.state.short_units,
            "positions_count": len([u for u in self.state.units_by_symbol.values() if u > 0]),
        }
