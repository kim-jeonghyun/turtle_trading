"""
거래 안전 가드 모듈.

일일 손실 서킷브레이커와 최대 주문 크기 제한을 구현한다.

설계 원칙:
  - Entry-Only Block: BUY 주문만 차단, SELL(청산)은 항상 허용
  - (bool, reason) 튜플 반환 패턴 (vi_cb_detector와 동일)
  - 킬 스위치 연동: 서킷브레이커 발동 시 KillSwitch.activate() 호출
  - 상태 영속화: data/trading_guard_state.json (cron 독립 프로세스 간 공유)
  - Defense-in-depth: TradingGuard(2M, 비즈니스 가드) + AutoTrader(5M, 시스템 안전망)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.kill_switch import KillSwitch
from src.utils import atomic_write_json, safe_load_json

logger = logging.getLogger(__name__)

# 기본 상태 파일 경로 (프로젝트 루트 기준)
GUARD_STATE_PATH = Path(__file__).parent.parent / "data" / "trading_guard_state.json"


@dataclass
class TradingLimits:
    """거래 안전 한도 설정.

    Attributes:
        max_daily_loss_pct: 일일 최대 손실 비율 (총자산 대비). 기본 3%
        max_order_amount: 단일 주문 최대 금액(원). 기본 200만원 (비즈니스 가드)
        max_order_pct: 단일 주문 최대 비율 (총자산 대비). 기본 10%

    Note:
        AutoTrader의 기존 max_order_amount(500만원)는 별도의 시스템 안전망으로 유지.
        TradingGuard(200만원)가 먼저 비즈니스 로직 가드로 작동한다 (defense-in-depth).
    """

    max_daily_loss_pct: float = 0.03  # 일일 최대 손실: 총자산의 3%
    max_order_amount: float = 2_000_000  # 단일 주문 최대 금액: 200만원
    max_order_pct: float = 0.10  # 단일 주문 최대 비율: 총자산의 10%


class TradingGuard:
    """거래 안전 가드.

    auto_trader.place_order() 사전 체크용.
    가드 체인: kill_switch → vi_cb_detector → trading_guard → [AutoTrader 5M 안전망] → place_order

    일일 손실 카운터는 data/trading_guard_state.json에 영속화되어
    cron 독립 프로세스 간에 공유된다.
    """

    def __init__(
        self,
        limits: TradingLimits,
        kill_switch: KillSwitch,
        state_path: Path = GUARD_STATE_PATH,
    ):
        """초기화 및 파일에서 상태 복원.

        Args:
            limits: 거래 한도 설정
            kill_switch: 킬 스위치 인스턴스 (서킷브레이커 발동 시 사용)
            state_path: 일일 손실 상태 파일 경로 (기본: data/trading_guard_state.json)
        """
        self.limits = limits
        self.kill_switch = kill_switch
        self._state_path = state_path
        # 파일에서 상태 복원 (날짜 불일치 시 자동 리셋)
        self._daily_realized_loss, self._daily_reset_date = self._load_state()

    def _load_state(self) -> tuple[float, str]:
        """파일에서 일일 손실 상태 로드.

        날짜가 오늘과 일치하면 기존 손실 복원, 아니면 0으로 리셋.
        파일 없으면 0으로 초기화 (안전한 방향 — 리셋은 허용적).

        Returns:
            (daily_realized_loss, today_date_str) 튜플
        """
        today = datetime.now().strftime("%Y-%m-%d")
        state = safe_load_json(self._state_path, default={})
        if isinstance(state, dict) and state.get("date") == today:
            loss = state.get("daily_realized_loss", 0.0)
            return float(loss), today
        return 0.0, today

    def _save_state(self) -> None:
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

        손실이 total_equity * max_daily_loss_pct를 초과하면 거래 차단 + 킬 스위치 활성화.
        예: 총자산 500만원 × 3% = 15만원 손실 시 당일 거래 중단.

        Args:
            total_equity: 현재 총 자산(원)

        Returns:
            (allowed, reason): allowed=True이면 거래 허용, False이면 차단
        """
        # H2: 킬 스위치 이미 활성 시 중복 호출 방지
        if not self.kill_switch.is_trading_enabled:
            return False, "킬 스위치 이미 활성 (중복 호출 방지)"

        max_loss = total_equity * self.limits.max_daily_loss_pct
        if abs(self._daily_realized_loss) > max_loss:
            reason = f"일일 손실 서킷브레이커 발동 ({self._daily_realized_loss:,.0f}원)"
            self.kill_switch.activate(
                reason=(f"일일 손실 한도 초과: {self._daily_realized_loss:,.0f}원 (한도: {max_loss:,.0f}원)")
            )
            # M2: CB 발동 시 상태 즉시 저장 (프로세스 재시작 후에도 상태 유지)
            self._save_state()
            logger.critical(
                f"[TradingGuard] 일일 손실 한도 초과: {self._daily_realized_loss:,.0f}원 "
                f"(한도: {max_loss:,.0f}원, 총자산: {total_equity:,.0f}원)"
            )
            return False, reason
        return True, ""

    def check_order_size(self, amount: float, total_equity: float) -> tuple[bool, str]:
        """주문 크기 체크 — 절대 금액 + 비율 이중 제한.

        Note:
            AutoTrader의 기존 5M 안전망과 별개 (defense-in-depth).
            이 가드(2M)가 먼저 통과하면 AutoTrader(5M)가 최후 안전망으로 작동.

        Args:
            amount: 주문 총 금액 (price * quantity, 원)
            total_equity: 현재 총 자산(원)

        Returns:
            (allowed, reason): allowed=True이면 허용, False이면 차단
        """
        # C3: 총자산 비정상 가드 (division error 방지)
        if total_equity <= 0:
            return False, "총자산 비정상"

        if amount > self.limits.max_order_amount:
            reason = f"주문 금액 초과: {amount:,.0f}원 (한도: {self.limits.max_order_amount:,.0f}원)"
            logger.warning(f"[TradingGuard] {reason}")
            return False, reason

        max_by_pct = total_equity * self.limits.max_order_pct
        if amount > max_by_pct:
            reason = f"주문 비율 초과: {amount / total_equity:.1%} (한도: {self.limits.max_order_pct:.0%})"
            logger.warning(f"[TradingGuard] {reason}")
            return False, reason

        return True, ""

    def record_trade_result(self, pnl: float) -> None:
        """거래 결과 기록 — 일일 손실 누적 + 파일 저장.

        날짜가 바뀌면 카운터를 자동 리셋한다.
        손실(pnl < 0)만 누적하고, 수익(pnl >= 0)은 무시한다.

        Args:
            pnl: 거래 손익(원). 음수면 손실, 양수면 수익.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            logger.info(f"[TradingGuard] 날짜 변경 — 일일 손실 카운터 리셋 ({self._daily_reset_date} → {today})")
            self._daily_realized_loss = 0.0
            self._daily_reset_date = today

        if pnl < 0:
            self._daily_realized_loss += pnl
            logger.debug(f"[TradingGuard] 손실 누적: {pnl:,.0f}원, 일일 합계: {self._daily_realized_loss:,.0f}원")

        self._save_state()

    @property
    def daily_realized_loss(self) -> float:
        """현재 일일 실현 손실 합계(원). 음수."""
        return self._daily_realized_loss

    @property
    def daily_reset_date(self) -> str:
        """일일 손실 카운터 기준 날짜 (YYYY-MM-DD)."""
        return self._daily_reset_date
