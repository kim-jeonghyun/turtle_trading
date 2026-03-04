"""Trading Safety Guards -- 일일 손실 서킷브레이커 + 주문 크기 제한.

가드 체인: kill_switch -> vi_cb_detector -> trading_guard -> [AutoTrader 5M 안전망] -> place_order
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.kill_switch import KillSwitch
from src.utils import atomic_write_json, safe_load_json

logger = logging.getLogger(__name__)

GUARD_STATE_PATH = Path(__file__).parent.parent / "data" / "trading_guard_state.json"


@dataclass
class TradingLimits:
    """거래 안전 한도"""

    max_daily_loss_pct: float = 0.03  # 일일 최대 손실: 총자산의 3%
    max_order_amount: float = 2_000_000  # 단일 주문 최대 금액: 200만원 (비즈니스 가드)
    max_order_pct: float = 0.10  # 단일 주문 최대 비율: 총자산의 10%


class TradingGuard:
    """거래 안전 가드 -- auto_trader.place_order() 사전 체크

    Defense-in-depth:
    - TradingGuard: 2M 비즈니스 가드 (configurable) -> REJECTED
    - AutoTrader: 5M 하드 시스템 안전망 (기존 유지) -> FAILED
    """

    def __init__(
        self,
        limits: TradingLimits,
        kill_switch: KillSwitch,
        state_path: Path = GUARD_STATE_PATH,
    ):
        self.limits = limits
        self.kill_switch = kill_switch
        self._state_path = state_path
        self._daily_realized_loss, self._daily_reset_date = self._load_state()

    def _load_state(self) -> tuple[float, str]:
        """파일에서 일일 손실 상태 로드. 날짜 불일치 시 리셋."""
        today = datetime.now().strftime("%Y-%m-%d")
        state = safe_load_json(self._state_path, default={})
        if state.get("date") == today:
            return state.get("daily_realized_loss", 0.0), today
        return 0.0, today

    def _save_state(self):
        """일일 손실 상태를 파일에 atomic 저장."""
        atomic_write_json(
            self._state_path,
            {
                "date": self._daily_reset_date,
                "daily_realized_loss": self._daily_realized_loss,
                "last_updated": datetime.now().isoformat(),
            },
        )

    def check_daily_loss(self, total_equity: float) -> tuple[bool, str]:
        """일일 실현 손실 체크.
        손실이 total_equity * max_daily_loss_pct 초과 시 차단 + 킬 스위치 활성화."""
        max_loss = total_equity * self.limits.max_daily_loss_pct
        if abs(self._daily_realized_loss) > max_loss:
            reason = f"일일 손실 한도 초과: {self._daily_realized_loss:,.0f}원 (한도: {max_loss:,.0f}원)"
            self.kill_switch.activate(reason=reason)
            return False, f"일일 손실 서킷브레이커 발동 ({self._daily_realized_loss:,.0f}원)"
        return True, ""

    def check_order_size(self, amount: float, total_equity: float) -> tuple[bool, str]:
        """주문 크기 체크. 절대 금액 + 비율 이중 제한.
        Note: AutoTrader의 기존 5M 하드 안전망과 별개 (defense-in-depth)."""
        if amount > self.limits.max_order_amount:
            return False, (f"주문 금액 초과: {amount:,.0f}원 (한도: {self.limits.max_order_amount:,.0f}원)")
        if total_equity > 0:
            max_by_pct = total_equity * self.limits.max_order_pct
            if amount > max_by_pct:
                return False, (f"주문 비율 초과: {amount / total_equity:.1%} (한도: {self.limits.max_order_pct:.0%})")
        return True, ""

    def record_trade_result(self, pnl: float):
        """거래 결과 기록 -- 총 손실(gross loss) 누적 + 파일 저장.
        수익 거래는 손실 카운터에서 상계하지 않음 (의도적 보수적 설계)."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_realized_loss = 0.0
            self._daily_reset_date = today
        if pnl < 0:
            self._daily_realized_loss += pnl  # gross loss only, no profit offset
        self._save_state()
