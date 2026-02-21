"""
자동매매 래퍼 모듈
- Dry-run 모드 (기본)
- 주문 실행 + 추적
- 안전 장치 (포지션 한도, 주문 크기)
- 주문 이력 로깅
- 주문 예외 후 재확인 (phantom fill 방지)
"""

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.kis_api import KISAPIClient, OrderSide, OrderType
from src.notifier import NotificationLevel, NotificationManager, NotificationMessage
from src.types import OrderStatus
from src.utils import atomic_write_json, safe_load_json

logger = logging.getLogger(__name__)

# 주문 로그 파일 경로
ORDER_LOG_PATH = Path(__file__).parent.parent / "data" / "trades" / "order_log.json"


@dataclass
class OrderRecord:
    """주문 기록 데이터클래스"""

    order_id: str
    symbol: str
    side: str  # "buy" / "sell"
    quantity: int
    price: float
    order_type: str  # "MARKET" / "LIMIT"
    status: str  # OrderStatus 상수
    timestamp: str
    dry_run: bool
    fill_price: Optional[float] = None
    fill_time: Optional[str] = None
    error_message: Optional[str] = None
    reason: Optional[str] = None  # 주문 이유 (시그널 설명)

    def to_dict(self) -> dict:
        return asdict(self)


class AutoTrader:
    """
    자동매매 래퍼 클래스
    - dry_run=True (기본): 실제 API 호출 없이 주문 시뮬레이션
    - dry_run=False (live): KIS API를 통한 실거래
    """

    # 주문 예외 후 재확인까지 대기 시간 (초)
    DEFAULT_RECONFIRM_DELAY_SEC = 30

    def __init__(
        self,
        kis_client: KISAPIClient,
        dry_run: bool = True,
        max_order_amount: float = 5_000_000,
        notifier: Optional[NotificationManager] = None,
        reconfirm_delay_sec: float = DEFAULT_RECONFIRM_DELAY_SEC,
    ):
        self.kis_client = kis_client
        self.dry_run = dry_run
        self.max_order_amount = max_order_amount
        self.notifier = notifier
        self.reconfirm_delay_sec = reconfirm_delay_sec
        self._order_counter = 0

        if not dry_run:
            logger.warning(
                "=" * 60 + "\n[LIVE MODE] 실거래 모드 활성화!\n실제 주문이 체결됩니다. 신중하게 진행하세요.\n=" * 60
            )
        else:
            logger.info("[DRY-RUN MODE] 시뮬레이션 모드 - 실제 주문 없음")

    def _generate_order_id(self) -> str:
        """내부 주문 ID 생성"""
        self._order_counter += 1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        mode = "DRY" if self.dry_run else "LIVE"
        return f"{mode}_{ts}_{self._order_counter:04d}"

    def _load_order_log(self) -> List[dict]:
        """기존 주문 로그 로드"""
        return safe_load_json(ORDER_LOG_PATH, default=[])

    def _save_order_log(self, orders: List[dict]):
        """주문 로그 저장 (atomic write)"""
        atomic_write_json(ORDER_LOG_PATH, orders)

    def _append_order_to_log(self, record: OrderRecord):
        """주문 기록 로그에 추가"""
        orders = self._load_order_log()
        orders.append(record.to_dict())
        self._save_order_log(orders)
        logger.info(f"주문 로그 저장: {record.order_id} ({record.symbol} {record.side} {record.quantity})")

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        order_type: OrderType = OrderType.MARKET,
        reason: str = "",
    ) -> OrderRecord:
        """
        주문 실행 (dry-run 또는 live)

        Args:
            symbol: 종목 코드
            side: 매수/매도 (OrderSide.BUY / OrderSide.SELL)
            quantity: 주문 수량
            price: 주문 가격 (MARKET 주문 시에도 안전 체크용으로 사용)
            order_type: 주문 유형 (MARKET / LIMIT)
            reason: 주문 사유 (시그널 설명)

        Returns:
            OrderRecord: 주문 기록
        """
        order_id = self._generate_order_id()
        timestamp = datetime.now().isoformat()

        # 주문 금액 안전 체크
        order_amount = quantity * price
        if order_amount > self.max_order_amount:
            error_msg = (
                f"주문 금액 초과: {order_amount:,.0f}원 > 한도 {self.max_order_amount:,.0f}원 "
                f"({symbol} {side.value} {quantity}주 @ {price:,.0f})"
            )
            logger.error(error_msg)
            record = OrderRecord(
                order_id=order_id,
                symbol=symbol,
                side=side.value,
                quantity=quantity,
                price=price,
                order_type=order_type.name,
                status=OrderStatus.FAILED.value,
                timestamp=timestamp,
                dry_run=self.dry_run,
                error_message=error_msg,
                reason=reason,
            )
            self._append_order_to_log(record)
            return record

        # Dry-run 모드: API 호출 없이 시뮬레이션
        if self.dry_run:
            logger.info(
                f"[DRY-RUN] 주문 시뮬레이션: {symbol} {side.value} {quantity}주 "
                f"@ {price:,.0f}원 ({order_type.name}) | 사유: {reason}"
            )
            record = OrderRecord(
                order_id=order_id,
                symbol=symbol,
                side=side.value,
                quantity=quantity,
                price=price,
                order_type=order_type.name,
                status=OrderStatus.DRY_RUN.value,
                timestamp=timestamp,
                dry_run=True,
                fill_price=price,  # dry-run에서는 요청가로 체결 가정
                fill_time=timestamp,
                reason=reason,
            )
            self._append_order_to_log(record)
            return record

        # Live 모드: KIS API 호출
        logger.info(
            f"[LIVE] 주문 실행: {symbol} {side.value} {quantity}주 "
            f"@ {price:,.0f}원 ({order_type.name}) | 사유: {reason}"
        )
        try:
            result = await self.kis_client.place_order(
                symbol=symbol, side=side, quantity=quantity, price=price, order_type=order_type
            )

            if result.get("success"):
                record = OrderRecord(
                    order_id=order_id,
                    symbol=symbol,
                    side=side.value,
                    quantity=quantity,
                    price=price,
                    order_type=order_type.name,
                    status=OrderStatus.FILLED.value,
                    timestamp=timestamp,
                    dry_run=False,
                    fill_price=price,
                    fill_time=result.get("order_time", timestamp),
                    reason=reason,
                )
                # KIS API가 반환한 주문 번호로 order_id 업데이트
                if result.get("order_no"):
                    record.order_id = result["order_no"]
                logger.info(f"주문 성공: {record.order_id}")
            else:
                error_msg = result.get("message", "Unknown error")
                record = OrderRecord(
                    order_id=order_id,
                    symbol=symbol,
                    side=side.value,
                    quantity=quantity,
                    price=price,
                    order_type=order_type.name,
                    status=OrderStatus.FAILED.value,
                    timestamp=timestamp,
                    dry_run=False,
                    error_message=error_msg,
                    reason=reason,
                )
                logger.error(f"주문 실패: {symbol} - {error_msg}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"주문 중 예외 발생: {symbol} - {error_msg}")
            record = OrderRecord(
                order_id=order_id,
                symbol=symbol,
                side=side.value,
                quantity=quantity,
                price=price,
                order_type=order_type.name,
                status=OrderStatus.FAILED.value,
                timestamp=timestamp,
                dry_run=False,
                error_message=error_msg,
                reason=reason,
            )
            # Phantom fill 방지: 예외 발생 후 지연 재확인
            record = await self._reconfirm_order(record)

        self._append_order_to_log(record)
        return record

    async def _reconfirm_order(self, record: OrderRecord) -> OrderRecord:
        """
        주문 예외 후 지연 재확인 (phantom fill 방지)

        주문 실행 중 네트워크 오류 등 예외가 발생하면 실제 체결 여부를 알 수 없다.
        KIS 주문번호를 수신하지 못했으므로 주문번호 기반 조회가 불가능하다.
        대신 당일 체결 내역에서 동일 종목·방향·수량의 최근 체결을 검색하여
        phantom fill 여부를 판단한다.

        - dry_run 모드에서는 재확인을 건너뛴다.
        - 재확인 자체가 실패하면 알림을 발송하고 수동 점검을 요청한다.

        Args:
            record: 예외로 FAILED 처리된 주문 기록

        Returns:
            갱신된 OrderRecord (FILLED 또는 원래 FAILED 유지)
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] 주문 재확인 스킵: {record.order_id}")
            return record

        logger.info(
            f"주문 재확인 예약: {record.order_id} ({record.symbol}) "
            f"- {self.reconfirm_delay_sec}초 후 체결 내역 검색"
        )

        await asyncio.sleep(self.reconfirm_delay_sec)

        try:
            # 당일 체결 내역 전체 조회 (주문번호 없이)
            status_result = await self.kis_client.get_order_status("")
            filled_orders = status_result.get("orders", [])

            # 동일 종목의 최근 체결 검색
            matching_fill = self._find_matching_fill(
                filled_orders, record
            )

            if matching_fill:
                kis_order_no = matching_fill.get("odno", "unknown")
                logger.info(
                    f"[RECONFIRM] 주문 체결 확인됨 (phantom fill 감지): "
                    f"{record.order_id} -> KIS#{kis_order_no}"
                )
                record.status = OrderStatus.FILLED.value
                record.fill_price = float(
                    matching_fill.get("avg_prvs", 0)
                    or matching_fill.get("filled_price", record.price)
                )
                record.fill_time = matching_fill.get(
                    "ord_tmd", datetime.now().isoformat()
                )
                record.error_message = (
                    f"[재확인으로 FILLED 복구] KIS#{kis_order_no} | "
                    f"원래 예외: {record.error_message}"
                )
            else:
                logger.info(
                    f"[RECONFIRM] 일치하는 체결 내역 없음: {record.order_id} ({record.symbol})"
                )
        except Exception as reconfirm_err:
            original_error = record.error_message
            logger.error(
                f"[RECONFIRM] 주문 재확인 실패: {record.order_id} - {reconfirm_err}"
            )
            record.error_message = (
                f"{original_error} | 재확인 실패: {reconfirm_err}"
            )
            # 재확인 실패 시 수동 점검 요청 알림
            await self._notify_reconfirm_failure(record, reconfirm_err, original_error)

        return record

    def _find_matching_fill(
        self, filled_orders: list, record: OrderRecord
    ) -> Optional[dict]:
        """당일 체결 내역에서 주문 파라미터와 일치하는 체결을 검색.

        Args:
            filled_orders: KIS API에서 반환한 당일 체결 목록
            record: 매칭할 주문 기록

        Returns:
            매칭된 체결 dict, 없으면 None
        """
        for order in filled_orders:
            # 종목코드 일치
            order_symbol = order.get("pdno", "")
            if order_symbol != record.symbol:
                continue

            # 매수/매도 방향 일치 (KIS: 01=매도, 02=매수)
            kis_side = order.get("sll_buy_dvsn_cd", "")
            expected_side = "02" if record.side == "buy" else "01"
            if kis_side != expected_side:
                continue

            # 체결 수량 확인 (0이면 미체결)
            filled_qty = int(order.get("tot_ccld_qty", "0") or "0")
            if filled_qty == 0:
                continue

            # 주문 수량이 유사한지 확인 (부분 체결 허용)
            if filled_qty > record.quantity * 2:
                continue  # 수량이 2배 이상 다르면 다른 주문

            return order

        return None

    async def _notify_reconfirm_failure(
        self, record: OrderRecord, error: Exception, original_error: Optional[str] = None
    ) -> None:
        """재확인 실패 시 수동 점검 요청 알림 발송"""
        if self.notifier is None:
            logger.warning(
                f"[RECONFIRM] 알림 매니저 미설정 - 수동 점검 필요: "
                f"{record.order_id} ({record.symbol})"
            )
            return

        display_error = original_error or record.error_message

        message = NotificationMessage(
            title=f"주문 재확인 실패 - 수동 점검 필요: {record.symbol}",
            body=(
                f"주문 실행 중 예외 발생 후 재확인 조회도 실패했습니다.\n"
                f"체결 여부를 수동으로 확인해 주세요.\n\n"
                f"원래 예외: {display_error}\n"
                f"재확인 오류: {error}"
            ),
            level=NotificationLevel.ERROR,
            data={
                "주문ID": record.order_id,
                "종목": record.symbol,
                "방향": record.side,
                "수량": record.quantity,
                "가격": f"{record.price:,.0f}",
            },
        )
        try:
            await self.notifier.send_all(message)
        except Exception as notify_err:
            logger.critical(
                f"[RECONFIRM] 알림 발송 실패: {record.order_id} - {notify_err}"
            )

    async def check_order_status(self, order_no: str) -> dict:
        """
        주문 상태 조회 (KIS API)

        Args:
            order_no: KIS 주문 번호

        Returns:
            주문 상태 딕셔너리
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] 주문 상태 조회 스킵: {order_no}")
            return {"order_no": order_no, "status": "dry_run", "message": "Dry-run mode"}

        try:
            logger.info(f"주문 상태 조회: {order_no}")
            return await self.kis_client.get_order_status(order_no)
        except Exception as e:
            logger.error(f"주문 상태 조회 실패: {order_no} - {e}")
            return {"order_no": order_no, "status": "error", "message": str(e)}

    async def get_account_summary(self) -> dict:
        """
        계좌 요약 조회 (잔고 + 포지션)

        Returns:
            계좌 요약 딕셔너리
        """
        if self.dry_run:
            logger.info("[DRY-RUN] 계좌 조회 스킵 - 더미 데이터 반환")
            return {
                "dry_run": True,
                "total_equity": 0.0,
                "cash": 0.0,
                "positions": [],
                "message": "Dry-run mode - 실제 계좌 데이터 없음",
            }

        try:
            balance = await self.kis_client.get_balance()
            return {"dry_run": False, **balance}
        except Exception as e:
            logger.error(f"계좌 조회 실패: {e}")
            return {"dry_run": False, "error": str(e), "total_equity": 0.0, "cash": 0.0, "positions": []}

    def get_order_history(self) -> List[dict]:
        """
        전체 주문 이력 반환

        Returns:
            주문 기록 리스트
        """
        return self._load_order_log()

    def get_daily_stats(self) -> dict:
        """
        오늘의 주문 통계 계산

        Returns:
            {
                "date": "YYYY-MM-DD",
                "total_orders": int,
                "filled": int,
                "failed": int,
                "dry_run": int,
                "total_amount": float
            }
        """
        today = datetime.now().strftime("%Y-%m-%d")
        orders = self._load_order_log()

        today_orders = [o for o in orders if o.get("timestamp", "").startswith(today)]

        filled = sum(1 for o in today_orders if o.get("status") == OrderStatus.FILLED.value)
        failed = sum(1 for o in today_orders if o.get("status") == OrderStatus.FAILED.value)
        dry_run_count = sum(1 for o in today_orders if o.get("status") == OrderStatus.DRY_RUN.value)
        total_amount = sum(
            o.get("quantity", 0) * o.get("price", 0)
            for o in today_orders
            if o.get("status") in (OrderStatus.FILLED.value, OrderStatus.DRY_RUN.value)
        )

        return {
            "date": today,
            "total_orders": len(today_orders),
            "filled": filled,
            "failed": failed,
            "dry_run": dry_run_count,
            "total_amount": total_amount,
        }
