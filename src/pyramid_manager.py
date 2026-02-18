"""
피라미딩 관리 모듈
- 0.5N 간격 추가 매수
- 최대 4 Units
- Trailing Stop
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from src.types import Direction


@dataclass
class PyramidEntry:
    entry_number: int
    entry_date: datetime
    entry_price: float
    units: int
    n_at_entry: float
    stop_price: float


@dataclass
class PyramidPosition:
    symbol: str
    direction: Direction
    entries: List[PyramidEntry] = field(default_factory=list)
    max_units: int = 4
    pyramid_interval_n: float = 0.5
    stop_distance_n: float = 2.0

    @property
    def total_units(self) -> int:
        return sum(e.units for e in self.entries)

    @property
    def is_full(self) -> bool:
        return self.total_units >= self.max_units

    @property
    def average_entry_price(self) -> float:
        if not self.entries:
            return 0.0
        total = sum(e.entry_price * e.units for e in self.entries)
        return total / self.total_units

    @property
    def current_stop(self) -> float:
        return self.entries[-1].stop_price if self.entries else 0.0

    def get_next_pyramid_price(self, current_n: float) -> float:
        if not self.entries:
            return 0.0
        interval = current_n * self.pyramid_interval_n
        if self.direction == Direction.LONG:
            return self.entries[-1].entry_price + interval
        return self.entries[-1].entry_price - interval

    def can_pyramid(self, current_price: float, current_n: float) -> Tuple[bool, str]:
        if self.is_full:
            return False, f"최대 Unit 도달: {self.total_units}/{self.max_units}"
        if not self.entries:
            return True, "초기 진입 가능"

        pyramid_price = self.get_next_pyramid_price(current_n)
        if self.direction == Direction.LONG:
            if current_price >= pyramid_price:
                return True, f"피라미딩 가격 도달: {current_price:.2f} >= {pyramid_price:.2f}"
        else:
            if current_price <= pyramid_price:
                return True, f"피라미딩 가격 도달: {current_price:.2f} <= {pyramid_price:.2f}"

        return False, f"피라미딩 대기 중"

    def add_entry(self, date: datetime, price: float, units: int, n_value: float):
        stop_distance = n_value * self.stop_distance_n
        if self.direction == Direction.LONG:
            stop_price = price - stop_distance
        else:
            stop_price = price + stop_distance

        entry = PyramidEntry(
            entry_number=len(self.entries) + 1,
            entry_date=date,
            entry_price=price,
            units=units,
            n_at_entry=n_value,
            stop_price=stop_price
        )
        self.entries.append(entry)
        self._update_trailing_stops()
        return entry

    def _update_trailing_stops(self):
        if len(self.entries) <= 1:
            return
        latest_stop = self.entries[-1].stop_price
        for entry in self.entries[:-1]:
            if self.direction == Direction.LONG:
                entry.stop_price = max(entry.stop_price, latest_stop)
            else:
                entry.stop_price = min(entry.stop_price, latest_stop)

    def check_stop_hit(self, current_price: float) -> bool:
        if not self.entries:
            return False
        if self.direction == Direction.LONG:
            return current_price <= self.current_stop
        return current_price >= self.current_stop


class PyramidManager:
    def __init__(self, max_units: int = 4, pyramid_interval_n: float = 0.5):
        self.max_units = max_units
        self.pyramid_interval_n = pyramid_interval_n
        self.positions: Dict[str, PyramidPosition] = {}

    def create_position(
        self,
        symbol: str,
        direction: Direction,
        date: datetime,
        price: float,
        units: int,
        n_value: float
    ) -> PyramidPosition:
        position = PyramidPosition(
            symbol=symbol,
            direction=direction,
            max_units=self.max_units,
            pyramid_interval_n=self.pyramid_interval_n
        )
        position.add_entry(date, price, units, n_value)
        self.positions[symbol] = position
        return position

    def get_position(self, symbol: str) -> Optional[PyramidPosition]:
        return self.positions.get(symbol)

    def close_position(self, symbol: str):
        self.positions.pop(symbol, None)
