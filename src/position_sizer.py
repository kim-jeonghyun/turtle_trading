"""
1% 리스크 기반 포지션 사이징 모듈 (Curtis Faith 원서 기준)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from src.types import Direction


@dataclass
class LivePosition:
    symbol: str
    direction: Direction
    entry_date: datetime
    entry_price: float
    quantity: int
    n_at_entry: float
    stop_price: float
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        if self.direction == Direction.LONG:
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity


@dataclass
class AccountState:
    initial_capital: float
    current_equity: float = 0.0
    cash: float = 0.0
    positions: Dict[str, LivePosition] = field(default_factory=dict)
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    realized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0

    def __post_init__(self):
        if self.current_equity == 0:
            self.current_equity = self.initial_capital
        if self.cash == 0:
            self.cash = self.initial_capital
        if self.peak_equity == 0:
            self.peak_equity = self.initial_capital

    def update_equity(self, prices: Optional[Dict[str, float]] = None):
        if prices:
            for symbol, pos in self.positions.items():
                if symbol in prices:
                    pos.current_price = prices[symbol]

        position_value = sum(pos.market_value for pos in self.positions.values())
        self.current_equity = self.cash + position_value

        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

        current_dd = (self.peak_equity - self.current_equity) / self.peak_equity
        self.max_drawdown = max(self.max_drawdown, current_dd)

    def get_sizing_equity(self, dd_step: float = 0.10, reduction_per_step: float = 0.20) -> float:
        """드로다운 기반 가상 계좌 크기 (Curtis Faith 원서)

        매 dd_step(기본 10%) 드로다운마다 peak_equity에서 reduction_per_step(기본 20%)만큼 감소.
        sizing_equity = min(current_equity, peak_equity * (1 - steps * reduction))
        """
        if self.peak_equity <= 0:
            return 0.0
        dd_pct = (self.peak_equity - self.current_equity) / self.peak_equity
        if dd_pct <= 0:
            return self.current_equity
        steps = int(dd_pct / dd_step)
        if steps <= 0:
            return self.current_equity
        reduction = steps * reduction_per_step
        notional = self.peak_equity * max(0.0, 1.0 - reduction)
        return min(self.current_equity, notional)


# Backward compatibility alias (deprecated, will be removed in v4.0)
Position = LivePosition


class PositionSizer:
    def __init__(self, risk_percent: float = 0.01, max_position_pct: float = 0.20):
        self.risk_percent = risk_percent
        self.max_position_pct = max_position_pct

    def calculate_unit(self, account_equity: float, n_value: float, point_value: float = 1.0) -> int:
        if n_value <= 0 or account_equity <= 0:
            return 0
        dollar_volatility = n_value * point_value
        return max(1, int((account_equity * self.risk_percent) / dollar_volatility))

    def calculate_stop_price(
        self, entry_price: float, n_value: float, direction: Direction, stop_distance_n: float = 2.0
    ) -> float:
        stop_distance = n_value * stop_distance_n
        if direction == Direction.LONG:
            return entry_price - stop_distance
        return entry_price + stop_distance
