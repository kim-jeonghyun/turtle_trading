"""
포지션 동기화 검증 모듈

KIS 계좌 잔고(get_balance)와 로컬 positions.json을 비교하여
불일치를 감지하고 보고한다.

- 불일치 유형: missing_local, missing_broker, quantity_mismatch
- missing_broker는 Principle 1(Broker-is-Truth) 위반 가능 → ERROR 레벨
- 동기화 불일치는 거래를 차단하지 않음 (정보성 보고 전용)
- API 장애 시 예외를 호출측에 전파 (Fail-Open은 스크립트에서 처리)
"""

import logging
from dataclasses import dataclass

from src.kis_api import KISAPIClient
from src.position_tracker import PositionTracker

logger = logging.getLogger(__name__)


@dataclass
class SyncDiscrepancy:
    """포지션 동기화 불일치 항목."""

    symbol: str
    discrepancy_type: str  # "missing_local", "missing_broker", "quantity_mismatch"
    local_quantity: int
    broker_quantity: int
    details: str

    @property
    def is_critical(self) -> bool:
        """missing_broker는 Principle 1 위반 가능 → ERROR 레벨."""
        return self.discrepancy_type == "missing_broker"


class PositionSyncVerifier:
    """KIS 잔고와 로컬 포지션 비교 검증기.

    Note: PositionTracker는 동기 메서드, KIS API는 비동기.
    verify()는 async 메서드로 두 소스를 비교한다.
    """

    def __init__(self, kis_client: KISAPIClient, tracker: PositionTracker):
        self.kis = kis_client
        self.tracker = tracker

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """KIS pdno(005930)와 로컬 symbol(005930.KS) 통일.

        Pattern from src/spot_price.py:72
        """
        return symbol.replace(".KS", "").replace(".KQ", "")

    async def verify(self) -> list[SyncDiscrepancy]:
        """KIS 잔고와 로컬 포지션 비교, 불일치 목록 반환.

        Raises:
            Exception: KIS API 호출 실패 시 (Fail-Open은 호출측에서 처리)
        """
        broker_positions = await self._fetch_broker_positions()
        local_positions = self._get_local_positions()
        return self._compare(broker_positions, local_positions)

    async def _fetch_broker_positions(self) -> dict[str, int]:
        """KIS get_balance() -> {normalized_symbol: quantity} 매핑.

        Raises:
            RuntimeError: get_balance()가 빈 dict 반환 시 (API 장애 가능성)
        """
        balance = await self.kis.get_balance()
        if not balance:
            raise RuntimeError(
                "KIS get_balance() returned empty response — API failure suspected, skipping sync to avoid false alerts"
            )
        return {p["symbol"]: p["quantity"] for p in balance.get("positions", []) if p["quantity"] > 0}

    def _get_local_positions(self) -> dict[str, int]:
        """positions.json -> {normalized_symbol: total_shares} 매핑.

        같은 종목의 다중 포지션은 total_shares를 합산한다.
        .KS/.KQ 접미사를 제거하여 KIS pdno와 비교 가능하게 한다.
        """
        open_positions = self.tracker.get_open_positions()
        result: dict[str, int] = {}
        for pos in open_positions:
            normalized = self._normalize_symbol(pos.symbol)
            result[normalized] = result.get(normalized, 0) + pos.total_shares
        return result

    def _compare(self, broker: dict[str, int], local: dict[str, int]) -> list[SyncDiscrepancy]:
        """브로커/로컬 포지션 비교 후 불일치 리스트 반환."""
        discrepancies: list[SyncDiscrepancy] = []
        all_symbols = set(broker.keys()) | set(local.keys())

        for symbol in sorted(all_symbols):
            b_qty = broker.get(symbol, 0)
            l_qty = local.get(symbol, 0)

            if b_qty > 0 and l_qty == 0:
                discrepancies.append(
                    SyncDiscrepancy(
                        symbol=symbol,
                        discrepancy_type="missing_local",
                        local_quantity=0,
                        broker_quantity=b_qty,
                        details=f"브로커에 {b_qty}주 보유, 로컬 추적 없음",
                    )
                )
            elif b_qty == 0 and l_qty > 0:
                discrepancies.append(
                    SyncDiscrepancy(
                        symbol=symbol,
                        discrepancy_type="missing_broker",
                        local_quantity=l_qty,
                        broker_quantity=0,
                        details=f"로컬 {l_qty}주 추적 중, 브로커 잔고 없음 [CRITICAL]",
                    )
                )
            elif b_qty != l_qty:
                discrepancies.append(
                    SyncDiscrepancy(
                        symbol=symbol,
                        discrepancy_type="quantity_mismatch",
                        local_quantity=l_qty,
                        broker_quantity=b_qty,
                        details=f"수량 불일치: 로컬 {l_qty}주 vs 브로커 {b_qty}주",
                    )
                )

        return discrepancies

    def format_report(self, discrepancies: list[SyncDiscrepancy]) -> str:
        """알림용 보고서 포맷팅.

        🔴 = critical (missing_broker)
        🟡 = warning (missing_local, quantity_mismatch)
        """
        lines = [f"포지션 동기화 검증 결과: {len(discrepancies)}건 불일치"]
        for d in discrepancies:
            prefix = "\U0001f534" if d.is_critical else "\U0001f7e1"
            lines.append(f"{prefix} [{d.discrepancy_type}] {d.symbol}: {d.details}")
        return "\n".join(lines)
