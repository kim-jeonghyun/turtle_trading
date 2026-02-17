"""
마켓 캘린더 및 시간대 관리 모듈
- 한국/미국 시장 시간 확인
- 주말/공휴일 체크
- 시간대 변환
"""

from datetime import datetime, time, date
from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:
    import pytz
    KST = pytz.timezone('Asia/Seoul')
    EST = pytz.timezone('US/Eastern')
    UTC = pytz.UTC
except ImportError:
    # Fallback: use zoneinfo (Python 3.9+)
    from zoneinfo import ZoneInfo
    KST = ZoneInfo('Asia/Seoul')
    EST = ZoneInfo('US/Eastern')
    UTC = ZoneInfo('UTC')
    # Shim for pytz-like localize
    pytz = None


MARKET_HOURS = {
    'KR': {
        'open': time(9, 0),
        'close': time(15, 30),
        'tz': KST,
        'name': '한국거래소 (KRX)',
    },
    'US': {
        'open': time(9, 30),
        'close': time(16, 0),
        'tz': EST,
        'name': 'NYSE/NASDAQ',
    },
    'CRYPTO': {
        'open': time(0, 0),
        'close': time(23, 59),
        'tz': UTC,
        'name': 'Crypto (24/7)',
    },
}

# 한국 공휴일 (2026년) - 수동 관리 필요 (대체공휴일 포함)
KR_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # 신정
    date(2026, 2, 16),  # 설날 연휴
    date(2026, 2, 17),  # 설날
    date(2026, 2, 18),  # 설날 연휴
    date(2026, 3, 1),   # 삼일절 (일요일)
    date(2026, 3, 2),   # 삼일절 대체공휴일
    date(2026, 5, 5),   # 어린이날
    date(2026, 5, 24),  # 부처님오신날 (일요일)
    date(2026, 5, 25),  # 부처님오신날 대체공휴일
    date(2026, 6, 6),   # 현충일 (토요일)
    date(2026, 6, 8),   # 현충일 대체공휴일
    date(2026, 8, 15),  # 광복절 (토요일)
    date(2026, 8, 17),  # 광복절 대체공휴일
    date(2026, 9, 24),  # 추석 연휴
    date(2026, 9, 25),  # 추석
    date(2026, 9, 26),  # 추석 연휴 (토요일)
    date(2026, 9, 28),  # 추석 대체공휴일
    date(2026, 10, 3),  # 개천절 (토요일)
    date(2026, 10, 5),  # 개천절 대체공휴일
    date(2026, 10, 9),  # 한글날
    date(2026, 12, 25), # 크리스마스
}

# 미국 공휴일 (2026년) - 주요 휴장일
US_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}

HOLIDAYS = {
    'KR': KR_HOLIDAYS_2026,
    'US': US_HOLIDAYS_2026,
}


def get_market_time(market: str = 'KR') -> datetime:
    """해당 마켓의 현재 시간 반환"""
    config = MARKET_HOURS.get(market)
    if not config:
        raise ValueError(f"Unknown market: {market}")
    return datetime.now(config['tz'])


def is_weekend(dt: Optional[datetime] = None, market: str = 'KR') -> bool:
    """주말 여부 확인"""
    if dt is None:
        dt = get_market_time(market)
    return dt.weekday() >= 5


def is_holiday(dt: Optional[datetime] = None, market: str = 'KR') -> bool:
    """공휴일 여부 확인"""
    if market == 'CRYPTO':
        return False  # Crypto markets never have holidays
    if dt is None:
        dt = get_market_time(market)

    check_date = dt.date() if isinstance(dt, datetime) else dt
    holidays = HOLIDAYS.get(market, set())
    if holidays and check_date.year != 2026:
        logger.warning(f"Holiday data only available for 2026, checking year {check_date.year}")
    return check_date in holidays


def is_market_open(market: str = 'KR') -> bool:
    """해당 마켓이 현재 장중인지 확인"""
    config = MARKET_HOURS.get(market)
    if not config:
        raise ValueError(f"Unknown market: {market}")

    now = get_market_time(market)

    # 주말 체크
    if is_weekend(now, market):
        return False

    # 공휴일 체크
    if is_holiday(now, market):
        return False

    # 장시간 체크
    return config['open'] <= now.time() <= config['close']


def get_market_status(market: str = 'KR') -> str:
    """마켓 상태 문자열 반환"""
    config = MARKET_HOURS.get(market)
    if not config:
        return f"Unknown market: {market}"

    now = get_market_time(market)

    if is_weekend(now, market):
        return f"{config['name']}: 휴장 (주말)"

    if is_holiday(now, market):
        return f"{config['name']}: 휴장 (공휴일)"

    if is_market_open(market):
        return f"{config['name']}: 장중 ({now.strftime('%H:%M')})"

    if now.time() < config['open']:
        return f"{config['name']}: 장전 ({now.strftime('%H:%M')}, 개장 {config['open'].strftime('%H:%M')})"

    return f"{config['name']}: 장후 ({now.strftime('%H:%M')}, 마감 {config['close'].strftime('%H:%M')})"


def infer_market(symbol: str) -> str:
    """심볼에서 마켓 추론"""
    if symbol.endswith('.KS') or symbol.endswith('.KQ'):
        return 'KR'
    if symbol.endswith('-USD') or symbol.endswith('USDT'):
        return 'CRYPTO'
    return 'US'


def should_check_signals(symbol: str) -> bool:
    """해당 심볼의 시그널 체크가 가능한 시간인지 확인"""
    market = infer_market(symbol)
    if market == 'CRYPTO':
        return True  # Crypto: 24/7 trading

    now = get_market_time(market)

    # 주말/공휴일이면 체크 불필요
    if is_weekend(now, market) or is_holiday(now, market):
        return False

    # 장 마감 후 ~ 자정 사이에 일일 데이터 기반 시그널 체크 가능
    config = MARKET_HOURS[market]
    return now.time() >= config['close']
