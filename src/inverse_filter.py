"""
Inverse ETF 필터링 모듈
- 최대 보유일 제한
- Volatility Decay 모니터링
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from datetime import datetime
from enum import Enum


@dataclass
class InverseETFConfig:
    symbol: str
    leverage: float
    underlying: str
    max_holding_days: int
    decay_threshold_pct: float


@dataclass
class InverseHolding:
    symbol: str
    entry_date: datetime
    entry_inverse_price: float
    entry_underlying_price: float
    holding_days: int = 0
    current_decay_pct: float = 0.0


class ExitReason(Enum):
    MAX_HOLDING_DAYS = "max_holding_days"
    DECAY_THRESHOLD = "decay_threshold"


class InverseETFFilter:
    KNOWN_INVERSE_ETFS: Dict[str, InverseETFConfig] = {
        "SH": InverseETFConfig("SH", -1, "SPY", 20, 5.0),
        "PSQ": InverseETFConfig("PSQ", -1, "QQQ", 20, 5.0),
        "SDS": InverseETFConfig("SDS", -2, "SPY", 15, 5.0),
        "SQQQ": InverseETFConfig("SQQQ", -3, "QQQ", 10, 3.0),
        "SPXU": InverseETFConfig("SPXU", -3, "SPY", 10, 3.0),
    }

    def __init__(self):
        self.holdings: Dict[str, InverseHolding] = {}

    def is_inverse_etf(self, symbol: str) -> bool:
        return symbol in self.KNOWN_INVERSE_ETFS

    def get_config(self, symbol: str) -> Optional[InverseETFConfig]:
        return self.KNOWN_INVERSE_ETFS.get(symbol)

    def on_entry(self, symbol: str, entry_date: datetime, inverse_price: float, underlying_price: float):
        if not self.is_inverse_etf(symbol):
            return
        self.holdings[symbol] = InverseHolding(
            symbol=symbol,
            entry_date=entry_date,
            entry_inverse_price=inverse_price,
            entry_underlying_price=underlying_price
        )

    def on_daily_update(self, symbol: str, current_inverse: float, current_underlying: float):
        if symbol not in self.holdings:
            return

        holding = self.holdings[symbol]
        config = self.KNOWN_INVERSE_ETFS.get(symbol)
        if not config:
            return

        holding.holding_days += 1
        holding.current_decay_pct = self._calculate_decay(
            config.leverage,
            holding.entry_inverse_price,
            current_inverse,
            holding.entry_underlying_price,
            current_underlying
        )

    def _calculate_decay(self, leverage: float, entry_inv: float, curr_inv: float,
                         entry_und: float, curr_und: float) -> float:
        if entry_inv == 0 or entry_und == 0:
            return 0.0
        underlying_return = (curr_und - entry_und) / entry_und
        theoretical_return = leverage * underlying_return
        actual_return = (curr_inv - entry_inv) / entry_inv
        return (actual_return - theoretical_return) * 100

    def should_force_exit(self, symbol: str, curr_inv: float, curr_und: float) -> Tuple[bool, Optional[ExitReason], str]:
        if symbol not in self.holdings:
            return False, None, ""

        holding = self.holdings[symbol]
        config = self.KNOWN_INVERSE_ETFS.get(symbol)
        if not config:
            return False, None, ""

        if holding.holding_days >= config.max_holding_days:
            return True, ExitReason.MAX_HOLDING_DAYS, f"최대 보유일 초과: {holding.holding_days}일"

        decay = self._calculate_decay(config.leverage, holding.entry_inverse_price, curr_inv,
                                       holding.entry_underlying_price, curr_und)
        if abs(decay) >= config.decay_threshold_pct:
            return True, ExitReason.DECAY_THRESHOLD, f"괴리율 초과: {decay:.2f}%"

        return False, None, ""

    def on_exit(self, symbol: str):
        self.holdings.pop(symbol, None)
