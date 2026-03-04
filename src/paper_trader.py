"""
Paper Trading 모듈
- 슬리피지 시뮬레이션 포함 가상 체결
- 포지션 및 잔고 추적
- JSON 영속화 (data/paper_trading/)

한계: 고정 비율 슬리피지 모델 사용 (거래량/호가 무관).
      v4.0에서 변동 슬리피지 모델로 개선 예정.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from src.auto_trader import OrderRecord
from src.utils import atomic_write_json, safe_load_json

logger = logging.getLogger(__name__)

PAPER_TRADING_DIR = Path(__file__).parent.parent / "data" / "paper_trading"
PORTFOLIO_PATH = PAPER_TRADING_DIR / "portfolio.json"
TRADES_PATH = PAPER_TRADING_DIR / "trades.json"


@dataclass
class PaperPosition:
    """Paper Trading 단일 포지션"""

    symbol: str
    side: str  # "buy" / "sell"
    quantity: int
    entry_price: float  # 요청가
    fill_price: float  # 슬리피지 적용 체결가
    commission: float  # 수수료 (원)
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


class PaperPortfolio:
    """
    Paper Trading 포트폴리오 매니저

    슬리피지와 수수료를 시뮬레이션하여 가상 체결을 기록하고
    PnL을 추적한다.

    Args:
        initial_capital: 초기 가상 자금 (기본 500만원)
        slippage_pct: 슬리피지 비율 (기본 0.05% = 시장가 기준 보수적 추정)
        commission_pct: 수수료 비율 (기본 0.1% = backtester.py와 동일)
    """

    def __init__(
        self,
        initial_capital: float = 5_000_000,
        slippage_pct: float = 0.0005,
        commission_pct: float = 0.001,
    ):
        self.initial_capital = initial_capital
        self.slippage_pct = slippage_pct
        self.commission_pct = commission_pct

        # 상태 로드 (영속화된 데이터 복원)
        state = self._load_portfolio_state()
        self.cash: float = state.get("cash", initial_capital)
        self.positions: dict[str, PaperPosition] = {}
        self.total_commission: float = state.get("total_commission", 0.0)
        self.total_slippage_cost: float = state.get("total_slippage_cost", 0.0)

        # 저장된 포지션 복원
        for sym, pos_dict in state.get("positions", {}).items():
            self.positions[sym] = PaperPosition(**pos_dict)

    def _load_portfolio_state(self) -> dict:
        """포트폴리오 상태 파일 로드"""
        result: dict = safe_load_json(PORTFOLIO_PATH, default={})
        return result

    def _simulate_fill_price(self, requested_price: float, side: str) -> float:
        """슬리피지 시뮬레이션 — 시장 마찰 반영

        BUY: 약간 높은 가격에 체결 (불리), SELL: 약간 낮은 가격에 체결 (불리)
        고정 비율 모델: 거래량/호가 스프레드 미반영 (v4.0에서 개선 예정).
        """
        if side == "buy":
            return requested_price * (1 + self.slippage_pct)
        else:
            return requested_price * (1 - self.slippage_pct)

    def execute_paper_order(self, record: OrderRecord) -> OrderRecord:
        """Paper 주문 실행: 슬리피지 적용 후 포지션/잔고 업데이트

        Args:
            record: dry_run OrderRecord (fill_price는 요청가로 설정된 상태)

        Returns:
            슬리피지가 적용된 fill_price로 수정된 OrderRecord
        """
        requested_price = record.price
        side = record.side  # "buy" / "sell"
        quantity = record.quantity
        symbol = record.symbol

        # 슬리피지 적용 체결가 계산
        fill_price = self._simulate_fill_price(requested_price, side)
        slippage_cost = abs(fill_price - requested_price) * quantity

        # 수수료 계산 (체결금액 기준)
        trade_amount = fill_price * quantity
        commission = trade_amount * self.commission_pct

        # 잔고 업데이트
        if side == "buy":
            total_cost = trade_amount + commission
            self.cash -= total_cost
            self.positions[symbol] = PaperPosition(
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=requested_price,
                fill_price=fill_price,
                commission=commission,
                timestamp=record.timestamp,
            )
            logger.info(
                f"[PAPER] BUY {symbol} {quantity}주 @ 요청:{requested_price:,.0f} "
                f"체결:{fill_price:,.0f} 수수료:{commission:,.0f} 잔고:{self.cash:,.0f}"
            )
        else:
            total_proceeds = trade_amount - commission
            self.cash += total_proceeds
            # 포지션 청산
            if symbol in self.positions:
                del self.positions[symbol]
            logger.info(
                f"[PAPER] SELL {symbol} {quantity}주 @ 요청:{requested_price:,.0f} "
                f"체결:{fill_price:,.0f} 수수료:{commission:,.0f} 잔고:{self.cash:,.0f}"
            )

        # 누적 비용 추적
        self.total_commission += commission
        self.total_slippage_cost += slippage_cost

        # 체결가 반영하여 record 수정
        record.fill_price = fill_price

        # 상태 저장
        self.save_state()

        # 거래 기록 추가
        self._append_trade(record, fill_price, commission, slippage_cost)

        return record

    def get_portfolio_snapshot(self) -> dict:
        """현재 포트폴리오 스냅샷 반환

        Returns:
            현재 포지션, 현금, 총 평가액, 수익률 정보
        """
        position_value = sum(pos.fill_price * pos.quantity for pos in self.positions.values())
        total_equity = self.cash + position_value
        return_rate = (total_equity - self.initial_capital) / self.initial_capital

        return {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "position_value": position_value,
            "total_equity": total_equity,
            "return_rate": return_rate,
            "total_commission": self.total_commission,
            "total_slippage_cost": self.total_slippage_cost,
            "positions": {sym: pos.to_dict() for sym, pos in self.positions.items()},
            "snapshot_time": datetime.now().isoformat(),
        }

    def save_state(self):
        """포트폴리오 상태를 JSON에 영속화"""
        position_value = sum(
            pos.fill_price * pos.quantity for pos in self.positions.values()
        )
        total_equity = self.cash + position_value
        state = {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "position_value": position_value,
            "total_equity": total_equity,
            "total_commission": self.total_commission,
            "total_slippage_cost": self.total_slippage_cost,
            "positions": {sym: pos.to_dict() for sym, pos in self.positions.items()},
            "last_updated": datetime.now().isoformat(),
        }
        atomic_write_json(PORTFOLIO_PATH, state)
        logger.debug(f"포트폴리오 상태 저장: 잔고={self.cash:,.0f}")

    def load_state(self):
        """포트폴리오 상태를 JSON에서 복원 (명시적 리로드용)"""
        state = self._load_portfolio_state()
        self.cash = state.get("cash", self.initial_capital)
        self.total_commission = state.get("total_commission", 0.0)
        self.total_slippage_cost = state.get("total_slippage_cost", 0.0)
        self.positions = {}
        for sym, pos_dict in state.get("positions", {}).items():
            self.positions[sym] = PaperPosition(**pos_dict)
        logger.info("포트폴리오 상태 복원 완료")

    def _append_trade(
        self,
        record: OrderRecord,
        fill_price: float,
        commission: float,
        slippage_cost: float,
    ):
        """거래 기록을 trades.json에 추가"""
        trades: list = safe_load_json(TRADES_PATH, default=[])
        trade_entry = {
            **record.to_dict(),
            "fill_price": fill_price,
            "commission": commission,
            "slippage_cost": slippage_cost,
            "paper_trade": True,
        }
        trades.append(trade_entry)
        atomic_write_json(TRADES_PATH, trades)

    def reset(self):
        """포트폴리오 초기화 (테스트/재시작용)"""
        self.cash = self.initial_capital
        self.positions = {}
        self.total_commission = 0.0
        self.total_slippage_cost = 0.0
        self.save_state()
        atomic_write_json(TRADES_PATH, [])
        logger.info(f"포트폴리오 초기화: 자본={self.initial_capital:,.0f}")
