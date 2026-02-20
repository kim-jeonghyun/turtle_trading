"""
1% 리스크 기반 포지션 사이징 모듈 (Curtis Faith 원서 기준)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from src.types import Direction


@dataclass
class Position:
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
    positions: Dict[str, Position] = field(default_factory=dict)
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
