"""
VI/CB 상태 감지 및 거래 가드.

VI (변동성 완화장치): 발동 시 2분간 단일가 매매 -> 해당 종목 주문 보류
CB (서킷브레이커): 발동 시 전체 시장 20분 중단 -> 전체 신규 진입 차단

Fail-Open 정책:
  캐시 만료 또는 캐시 미존재 시 진입 허용 (기회손실 방지).
  미정의 VI 코드는 VIStatus.NONE으로 처리.

Entry-Only Block:
  신규 진입(BUY)만 차단. 청산(SELL)은 항상 허용 (손절 보장).
  BUY/SELL 구분은 호출측(auto_trader.place_order)에서 처리.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class VIStatus(Enum):
    """VI (변동성 완화장치) 상태."""

    NONE = "none"  # 정상
    STATIC_VI = "static"  # 정적 VI (전일 종가 기준 +/-상한)
    DYNAMIC_VI = "dynamic"  # 동적 VI (직전 체결가 기준)


class CBStatus(Enum):
    """CB (서킷브레이커) 상태."""

    NONE = "none"
    SIDECAR = "sidecar"  # 프로그램매매 호가 5분 효력 정지
    CB_LEVEL1 = "cb_1"  # 1단계: KOSPI 8% 하락, 20분 중단
    CB_LEVEL2 = "cb_2"  # 2단계: KOSPI 15% 하락, 20분 중단
    CB_LEVEL3 = "cb_3"  # 3단계: KOSPI 20% 하락, 당일 거래 중지


@dataclass
class MarketSafetyStatus:
    """종목별 시장 안전 상태."""

    symbol: str
    vi_status: VIStatus
    cb_status: CBStatus
    is_entry_blocked: bool
    reason: str
    detected_at: datetime


class VICBDetector:
    """VI/CB 상태 감지 및 거래 가드.

    Thread-safety: NOT thread-safe. 단일 asyncio event loop 내에서만 사용.
    각 스크립트(auto_trade, check_positions, monitor_positions)는
    독립 프로세스로 실행되므로 인스턴스 공유 없음.
    """

    # KIS API vi_cls_code 매핑
    VI_CODE_MAP: dict[str, VIStatus] = {
        "0": VIStatus.NONE,
        "1": VIStatus.STATIC_VI,
        "2": VIStatus.DYNAMIC_VI,
    }

    def __init__(self, cache_ttl_sec: int = 30):
        self._cache: dict[str, tuple[MarketSafetyStatus, datetime]] = {}
        self._cache_ttl = timedelta(seconds=cache_ttl_sec)
        self._cb_active = False  # 시장 전체 CB

    def update_from_spot(self, symbol: str, spot_data: dict) -> MarketSafetyStatus:
        """spot_price 응답에서 VI/CB 상태 업데이트.

        Args:
            symbol: 종목 코드
            spot_data: get_korea_price() 응답 dict (vi_cls_code 포함)

        Returns:
            MarketSafetyStatus: 갱신된 상태
        """
        vi_code = spot_data.get("vi_cls_code", "0")
        vi_status = self.VI_CODE_MAP.get(vi_code, VIStatus.NONE)

        status = MarketSafetyStatus(
            symbol=symbol,
            vi_status=vi_status,
            cb_status=CBStatus.CB_LEVEL1 if self._cb_active else CBStatus.NONE,
            is_entry_blocked=(vi_status != VIStatus.NONE or self._cb_active),
            reason=self._build_reason(vi_status, self._cb_active),
            detected_at=datetime.now(),
        )
        self._cache[symbol] = (status, datetime.now())
        return status

    def check_entry_allowed(self, symbol: str) -> tuple[bool, str]:
        """주문 전 가드: (허용여부, 사유).

        Fail-Open: 캐시 없거나 만료 시 진입 허용.

        Args:
            symbol: 종목 코드

        Returns:
            (allowed, reason): allowed=False이면 reason에 차단 사유
        """
        cached = self._cache.get(symbol)
        if cached is None:
            return True, ""  # Fail-Open: 캐시 없으면 허용

        status, cached_at = cached
        if datetime.now() - cached_at > self._cache_ttl:
            return True, ""  # 캐시 만료 -> 허용

        if status.is_entry_blocked:
            return False, status.reason

        return True, ""

    def activate_cb(self, level: CBStatus, reason: str) -> None:
        """CB 발동 시 전체 시장 차단.

        Args:
            level: CB 단계
            reason: 발동 사유
        """
        self._cb_active = True
        logger.critical(f"CB 발동: {level.value} - {reason}")

    def deactivate_cb(self) -> None:
        """CB 해제."""
        self._cb_active = False
        logger.info("CB 해제")

    def _build_reason(self, vi: VIStatus, cb: bool) -> str:
        """차단 사유 문자열 생성."""
        parts: list[str] = []
        if vi != VIStatus.NONE:
            parts.append(f"VI 발동 ({vi.value})")
        if cb:
            parts.append("CB 발동 — 시장 거래 중단")
        return " / ".join(parts) if parts else ""
