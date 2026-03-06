"""
공유 타입 정의 모듈
- Direction, SignalType, AssetGroup, OrderStatus 등 프로젝트 전역 Enum
- SerializableEnum: str 상속으로 JSON 직렬화/문자열 비교 자동 호환
- 하위 호환: Enum.value는 기존 문자열과 동일
"""

from enum import Enum
from typing import Protocol, runtime_checkable


class SerializableEnum(str, Enum):
    """JSON 직렬화 호환 Enum 베이스 클래스.

    str을 상속하여 다음이 자동으로 동작:
    - json.dumps / dataclasses.asdict 시 문자열로 직렬화
    - == "LONG" 등 문자열 직접 비교 가능
    - .value 접근도 여전히 동작 (하위 호환)
    """

    pass


class Direction(SerializableEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalType(SerializableEnum):
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"
    PYRAMID_LONG = "pyramid_long"
    PYRAMID_SHORT = "pyramid_short"
    STOP_LOSS = "stop_loss"


class AssetGroup(SerializableEnum):
    KR_EQUITY = "kr_equity"
    US_EQUITY = "us_equity"
    ASIA_EQUITY = "asia_equity"
    EU_EQUITY = "eu_equity"
    CHINA_EQUITY = "china_equity"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    COMMODITY_ENERGY = "commodity_energy"
    COMMODITY_AGRI = "commodity_agri"
    BOND = "bond"
    INVERSE = "inverse"
    CURRENCY = "currency"
    REIT = "reit"
    ALTERNATIVES = "alternatives"


class OrderStatus(SerializableEnum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    DRY_RUN = "dry_run"
    UNKNOWN = "unknown"


@runtime_checkable
class PositionSnapshot(Protocol):
    """포지션 공통 스냅샷 인터페이스 (risk_manager 등 공통 참조용)"""

    symbol: str
    direction: Direction
    entry_price: float
    quantity: int
    current_price: float

    @property
    def market_value(self) -> float: ...

    @property
    def unrealized_pnl(self) -> float: ...
