"""
공유 타입 정의 모듈
- Direction, SignalType, AssetGroup, OrderStatus 등 프로젝트 전역 Enum
- 하위 호환: Enum.value는 기존 문자열과 동일
"""

from enum import Enum


class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalType(Enum):
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"
    PYRAMID_LONG = "pyramid_long"
    PYRAMID_SHORT = "pyramid_short"
    STOP_LOSS = "stop_loss"


class AssetGroup(Enum):
    KR_EQUITY = "kr_equity"
    US_EQUITY = "us_equity"
    ASIA_EQUITY = "asia_equity"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    BOND = "bond"
    INVERSE = "inverse"
    CURRENCY = "currency"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    DRY_RUN = "dry_run"
    UNKNOWN = "unknown"
