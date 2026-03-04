"""Paper Trading 포트폴리오 매니저 — 슬리피지 포함 가상 체결."""

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils import atomic_write_json, safe_load_json

logger = logging.getLogger(__name__)

PAPER_TRADING_DIR = Path(__file__).parent.parent / "data" / "paper_trading"
PORTFOLIO_PATH = PAPER_TRADING_DIR / "portfolio.json"
TRADES_PATH = PAPER_TRADING_DIR / "trades.json"


@dataclass
class PaperPosition:
    symbol: str
    side: str  # "buy" or "sell"
    quantity: int
    avg_price: float
    unrealized_pnl: float = 0.0


@dataclass
class PaperTradeRecord:
    order_id: str
    symbol: str
    side: str
    quantity: int
    requested_price: float
    fill_price: float
    slippage: float
    commission: float
    timestamp: str = ""
    pnl: float = 0.0  # for closing trades


class PaperPortfolio:
    """가상 포트폴리오 — dry_run 주문을 슬리피지 적용하여 추적.

    고정 비율 슬리피지 모델 한계 인지. v4.0에서 변동 슬리피지 모델 검토."""

    def __init__(
        self,
        initial_capital: float = 5_000_000,
        slippage_pct: Optional[float] = None,
        commission_pct: float = 0.001,  # backtester.py와 동일
    ):
        self.initial_capital = initial_capital
        self.slippage_pct = (
            slippage_pct if slippage_pct is not None else float(os.environ.get("PAPER_SLIPPAGE_PCT", "0.0005"))
        )
        self.commission_pct = commission_pct

        PAPER_TRADING_DIR.mkdir(parents=True, exist_ok=True)

        self.cash = initial_capital
        self.positions: dict[str, PaperPosition] = {}
        self.trades: list[dict] = []
        self._load_state()

    def _load_state(self) -> None:
        """기존 포트폴리오 상태 로드"""
        portfolio = safe_load_json(PORTFOLIO_PATH, default={})
        if portfolio:
            self.cash = portfolio.get("cash", self.initial_capital)
            for sym, pos_data in portfolio.get("positions", {}).items():
                self.positions[sym] = PaperPosition(**pos_data)

        self.trades = safe_load_json(TRADES_PATH, default=[])

    def _save_state(self) -> None:
        """포트폴리오 상태 저장"""
        portfolio_data = {
            "cash": self.cash,
            "positions": {sym: asdict(pos) for sym, pos in self.positions.items()},
            "last_updated": datetime.now().isoformat(),
        }
        atomic_write_json(PORTFOLIO_PATH, portfolio_data)
        atomic_write_json(TRADES_PATH, self.trades)

    def _simulate_fill_price(self, requested_price: float, side: str) -> float:
        """슬리피지 시뮬레이션 — 시장 마찰 반영.

        BUY: 약간 높은 가격에 체결 (불리), SELL: 약간 낮은 가격에 체결 (불리)"""
        if side == "buy":
            return requested_price * (1 + self.slippage_pct)
        else:
            return requested_price * (1 - self.slippage_pct)

    def execute_paper_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        quantity: int,
        requested_price: float,
    ) -> PaperTradeRecord:
        """가상 주문 실행 — 슬리피지 + 수수료 적용"""
        fill_price = self._simulate_fill_price(requested_price, side)
        slippage = fill_price - requested_price
        trade_amount = fill_price * quantity
        commission = trade_amount * self.commission_pct
        pnl = 0.0

        if side == "buy":
            self.cash -= trade_amount + commission
            if symbol in self.positions:
                pos = self.positions[symbol]
                total_qty = pos.quantity + quantity
                pos.avg_price = ((pos.avg_price * pos.quantity) + (fill_price * quantity)) / total_qty
                pos.quantity = total_qty
            else:
                self.positions[symbol] = PaperPosition(
                    symbol=symbol,
                    side="buy",
                    quantity=quantity,
                    avg_price=fill_price,
                )
        else:  # sell
            self.cash += trade_amount - commission
            if symbol in self.positions:
                pos = self.positions[symbol]
                pnl = (fill_price - pos.avg_price) * quantity
                pos.quantity -= quantity
                if pos.quantity <= 0:
                    del self.positions[symbol]

        record = PaperTradeRecord(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            requested_price=requested_price,
            fill_price=fill_price,
            slippage=slippage,
            commission=commission,
            timestamp=datetime.now().isoformat(),
            pnl=pnl,
        )
        self.trades.append(asdict(record))
        self._save_state()
        logger.info(
            f"[PAPER] {side.upper()} {symbol} {quantity}주 @ {fill_price:,.0f}원 "
            f"(슬리피지 {slippage:+,.0f}원, 수수료 {commission:,.0f}원)"
        )
        return record

    def get_portfolio_snapshot(self) -> dict:
        """현재 포트폴리오 스냅샷"""
        total_position_value = sum(pos.quantity * pos.avg_price for pos in self.positions.values())
        total_equity = self.cash + total_position_value
        total_pnl = total_equity - self.initial_capital
        return {
            "cash": self.cash,
            "positions": {sym: asdict(pos) for sym, pos in self.positions.items()},
            "total_position_value": total_position_value,
            "total_equity": total_equity,
            "total_pnl": total_pnl,
            "return_pct": (total_pnl / self.initial_capital) * 100 if self.initial_capital > 0 else 0,
            "trade_count": len(self.trades),
            "total_slippage": sum(abs(t.get("slippage", 0) * t.get("quantity", 0)) for t in self.trades),
            "total_commission": sum(t.get("commission", 0) for t in self.trades),
        }
