"""
슬리피지/수수료 실측 및 예산 알림 모듈.

주요 기능:
- 주문별 슬리피지·수수료 계산
- 누적 비용 집계
- 이중 임계 예산 한도 점검 (자산 기준 + 수익 기준)

Dual threshold (v2 설계):
1. equity_threshold_pct = 0.002 (0.2%) - 누적 비용 vs 총 자산
2. profit_threshold_pct = 0.15 (15%) - 누적 비용 vs 실현 수익

둘 중 하나 초과 시 킬 스위치 + 알림 활성화.
realized_profit <= 0인 경우 수익 임계 검사 스킵 (자산 임계만 적용).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils import atomic_write_json, safe_load_json

logger = logging.getLogger(__name__)

COST_LOG_PATH = Path(__file__).parent.parent / "data" / "cost_log.json"


@dataclass
class TradeCost:
    order_id: str
    symbol: str
    requested_price: float
    fill_price: float
    quantity: int  # 주문 수량
    slippage: float  # fill_price - requested_price (부호 있음)
    slippage_pct: float  # slippage / requested_price
    commission: float  # fill_amount * commission_rate
    total_cost: float  # abs(slippage * qty) + commission
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "requested_price": self.requested_price,
            "fill_price": self.fill_price,
            "quantity": self.quantity,
            "slippage": self.slippage,
            "slippage_pct": self.slippage_pct,
            "commission": self.commission,
            "total_cost": self.total_cost,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TradeCost":
        return cls(
            order_id=d["order_id"],
            symbol=d["symbol"],
            requested_price=d["requested_price"],
            fill_price=d["fill_price"],
            quantity=d.get("quantity", 0),
            slippage=d["slippage"],
            slippage_pct=d["slippage_pct"],
            commission=d["commission"],
            total_cost=d["total_cost"],
            timestamp=d.get("timestamp", ""),
        )


class CostAnalyzer:
    """슬리피지/수수료 분석기 (이중 임계 예산 점검 포함).

    Dual threshold (v2 설계):
    1. equity_threshold_pct = 0.002 (0.2%) - 누적 비용 vs 총 자산
    2. profit_threshold_pct = 0.15 (15%) - 누적 비용 vs 실현 수익

    둘 중 하나 초과 시 → (False, 사유)
    """

    def __init__(
        self,
        commission_rate: float = 0.00015,
        cost_log_path: Optional[Path] = None,
    ):
        """한국투자증권 기본 수수료율 0.015% (0.00015)."""
        self.commission_rate = commission_rate
        self._cost_log_path = Path(cost_log_path) if cost_log_path else COST_LOG_PATH
        self._costs: list[TradeCost] = []
        self._load_costs()

    def analyze_order(
        self,
        order_id: str,
        symbol: str,
        requested_price: float,
        fill_price: float,
        quantity: int,
    ) -> TradeCost:
        """단일 주문 비용 분석 후 TradeCost 반환 및 저장."""
        if quantity <= 0:
            raise ValueError(f"quantity는 양수여야 합니다: {quantity}")
        if requested_price <= 0:
            raise ValueError(f"requested_price는 양수여야 합니다: {requested_price}")

        slippage = fill_price - requested_price
        slippage_pct = slippage / requested_price
        fill_amount = fill_price * quantity
        commission = fill_amount * self.commission_rate
        total_cost = abs(slippage * quantity) + commission

        cost = TradeCost(
            order_id=order_id,
            symbol=symbol,
            requested_price=requested_price,
            fill_price=fill_price,
            quantity=quantity,
            slippage=slippage,
            slippage_pct=slippage_pct,
            commission=commission,
            total_cost=total_cost,
        )
        self._costs.append(cost)
        self._save_costs()
        logger.info(
            f"비용 기록: {symbol} order={order_id} "
            f"slippage={slippage:+.1f}({slippage_pct:.4%}) "
            f"commission={commission:,.0f}원 total={total_cost:,.0f}원"
        )
        return cost

    def get_cumulative_costs(self, since: Optional[str] = None) -> dict:
        """누적 비용 요약: 총 슬리피지, 총 수수료, 평균 슬리피지율.

        Args:
            since: ISO 날짜 문자열 (예: "2026-03-01"). 미지정 시 전체 집계.
        """
        costs = self._costs
        if since:
            from datetime import datetime as dt

            since_dt = dt.fromisoformat(since) if "T" in since else dt.strptime(since, "%Y-%m-%d")
            costs = [c for c in costs if c.timestamp and dt.fromisoformat(c.timestamp) >= since_dt]

        if not costs:
            return {
                "total_slippage": 0.0,
                "total_commission": 0.0,
                "total_cost": 0.0,
                "avg_slippage_pct": 0.0,
                "trade_count": 0,
            }

        total_slippage = sum(abs(c.slippage) for c in costs)
        total_commission = sum(c.commission for c in costs)
        total_cost = sum(c.total_cost for c in costs)
        avg_slippage_pct = sum(abs(c.slippage_pct) for c in costs) / len(costs)

        return {
            "total_slippage": total_slippage,
            "total_commission": total_commission,
            "total_cost": total_cost,
            "avg_slippage_pct": avg_slippage_pct,
            "trade_count": len(costs),
        }

    def check_budget_limit(
        self,
        total_equity: float,
        realized_profit: float,
        equity_threshold_pct: float = 0.002,  # 0.2%
        profit_threshold_pct: float = 0.15,  # 수익의 15%
        since: Optional[str] = None,  # ISO 날짜 문자열 (예: "2026-03-01")
    ) -> tuple[bool, str]:
        """이중 임계 예산 점검.

        1) 누적 비용 > total_equity × equity_threshold_pct → 차단
        2) 누적 비용 > realized_profit × profit_threshold_pct → 차단
           (realized_profit <= 0이면 수익 임계 스킵 — 초기 단계 불필요 차단 방지)

        Args:
            since: 이 날짜 이후 비용만 집계. 미지정 시 전체 집계.

        Returns:
            (True, "") — 정상
            (False, 사유) — 임계 초과
        """
        cumulative = self.get_cumulative_costs(since=since)
        total_cost = cumulative["total_cost"]

        # 검사 1: 자산 임계
        equity_limit = total_equity * equity_threshold_pct
        if total_cost > equity_limit:
            reason = (
                f"슬리피지 예산 초과 (자산 기준): "
                f"{total_cost:,.0f}원 > {equity_limit:,.0f}원 "
                f"({equity_threshold_pct:.1%} of {total_equity:,.0f}원)"
            )
            logger.warning(reason)
            return False, reason

        # 검사 2: 수익 임계 (수익이 양수일 때만)
        if realized_profit > 0:
            profit_limit = realized_profit * profit_threshold_pct
            if total_cost > profit_limit:
                reason = (
                    f"슬리피지 예산 초과 (수익 기준): "
                    f"{total_cost:,.0f}원 > {profit_limit:,.0f}원 "
                    f"({profit_threshold_pct:.0%} of {realized_profit:,.0f}원)"
                )
                logger.warning(reason)
                return False, reason

        return True, ""

    def _load_costs(self) -> None:
        """파일에서 비용 이력 로드."""
        raw: list = safe_load_json(self._cost_log_path, default=[])
        self._costs = []
        for item in raw:
            try:
                self._costs.append(TradeCost.from_dict(item))
            except (KeyError, TypeError) as e:
                logger.warning(f"비용 레코드 파싱 실패 (스킵): {e} — {item}")

    def _save_costs(self) -> None:
        """비용 이력을 파일에 원자적 저장."""
        data = [c.to_dict() for c in self._costs]
        atomic_write_json(self._cost_log_path, data)
