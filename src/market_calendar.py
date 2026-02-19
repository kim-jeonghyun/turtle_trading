"""
마켓 캘린더 및 시간대 관리 모듈
- 한국/미국 시장 시간 확인
- 주말/공휴일 체크
- 시간대 변환

============================
미국 일광절약시간(DST) 규칙
============================
NYSE/NASDAQ 는 Eastern Time (ET) 기준으로 운영됩니다.
DST 는 미국 연방법(Energy Policy Act 2005)에 따라:
  - 시작: 3월 두 번째 일요일 02:00 AM EST -> EDT (UTC-5 -> UTC-4)
  - 종료: 11월 첫 번째 일요일 02:00 AM EDT -> EST (UTC-4 -> UTC-5)

실용적 영향:
  - 표준시(EST, UTC-5): 11월 첫째 일요일 ~ 3월 둘째 일요일
  - 일광절약시(EDT, UTC-4): 3월 둘째 일요일 ~ 11월 첫째 일요일
  - 장 개장(한국시간 기준):
      표준시 기간: 23:30 KST (전날) ~ 06:00 KST
      일광절약시 기간: 22:30 KST (전날) ~ 05:00 KST

pytz / zoneinfo 라이브러리가 DST 변환을 자동으로 처리합니다.
수동으로 DST 날짜를 계산하려면 dst_start() / dst_end() 헬퍼 함수를 사용하세요.
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import pytz

    KST = pytz.timezone("Asia/Seoul")
    EST = pytz.timezone("US/Eastern")
    UTC = pytz.UTC
except ImportError:
    # Fallback: use zoneinfo (Python 3.9+)
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
    EST = ZoneInfo("US/Eastern")
    UTC = ZoneInfo("UTC")
    # Shim for pytz-like localize
    pytz = None


def dst_start(year: int) -> date:
    """미국 DST 시작일: 3월 두 번째 일요일 반환

    Args:
        year: 연도 (2007년 이후 현행 규칙 적용)

    Returns:
        DST 시작 날짜 (02:00 AM EST에 EDT로 전환)
    """
    # 3월 1일부터 첫 번째 일요일 찾기
    march_1 = date(year, 3, 1)
    days_until_sunday = (6 - march_1.weekday()) % 7
    first_sunday = march_1 + timedelta(days=days_until_sunday)
    return first_sunday + timedelta(weeks=1)  # 두 번째 일요일


def dst_end(year: int) -> date:
    """미국 DST 종료일: 11월 첫 번째 일요일 반환

    Args:
        year: 연도 (2007년 이후 현행 규칙 적용)

    Returns:
        DST 종료 날짜 (02:00 AM EDT에 EST로 전환)
    """
    november_1 = date(year, 11, 1)
    days_until_sunday = (6 - november_1.weekday()) % 7
    return november_1 + timedelta(days=days_until_sunday)  # 첫 번째 일요일


def is_dst(dt: date, year: Optional[int] = None) -> bool:
    """주어진 날짜가 미국 DST(일광절약시간) 기간인지 확인

    Args:
        dt: 확인할 날짜
        year: 연도 (dt에서 자동 추출됨)

    Returns:
        DST 기간이면 True
    """
    y = dt.year if year is None else year
    return dst_start(y) <= dt < dst_end(y)


MARKET_HOURS = {
    "KR": {
        "open": time(9, 0),
        "close": time(15, 30),
        "tz": KST,
        "name": "한국거래소 (KRX)",
    },
    "US": {
        "open": time(9, 30),
        "close": time(16, 0),
        "tz": EST,
        "name": "NYSE/NASDAQ",
    },
    "CRYPTO": {
        "open": time(0, 0),
        "close": time(23, 59),
        "tz": UTC,
        "name": "Crypto (24/7)",
    },
}

# 한국 공휴일 (2026년) - 수동 관리 필요 (대체공휴일 포함)
KR_HOLIDAYS_2026 = {
    date(2026, 1, 1),  # 신정
    date(2026, 2, 16),  # 설날 연휴
    date(2026, 2, 17),  # 설날
    date(2026, 2, 18),  # 설날 연휴
    date(2026, 3, 1),  # 삼일절 (일요일)
    date(2026, 3, 2),  # 삼일절 대체공휴일
    date(2026, 5, 5),  # 어린이날
    date(2026, 5, 24),  # 부처님오신날 (일요일)
    date(2026, 5, 25),  # 부처님오신날 대체공휴일
    date(2026, 6, 6),  # 현충일 (토요일)
    date(2026, 6, 8),  # 현충일 대체공휴일
    date(2026, 8, 15),  # 광복절 (토요일)
    date(2026, 8, 17),  # 광복절 대체공휴일
    date(2026, 9, 24),  # 추석 연휴
    date(2026, 9, 25),  # 추석
    date(2026, 9, 26),  # 추석 연휴 (토요일)
    date(2026, 9, 28),  # 추석 대체공휴일
    date(2026, 10, 3),  # 개천절 (토요일)
    date(2026, 10, 5),  # 개천절 대체공휴일
    date(2026, 10, 9),  # 한글날
    date(2026, 12, 25),  # 크리스마스
}

# 미국 공휴일 (2026년) - 주요 휴장일
US_HOLIDAYS_2026 = {
    date(2026, 1, 1),  # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),  # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),  # Independence Day (observed)
    date(2026, 9, 7),  # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}

# 한국 공휴일 (2027년) - 대체공휴일 포함
# 설날: 2/6(토)~2/8(월) - 2/6(토)→2/9(화) 대체, 2/7(일)→2/10(수) 대체
# 현충일: 6/6(일)→6/7(월) 대체
# 광복절: 8/15(일)→8/16(월) 대체
# 개천절: 10/3(일)→10/4(월) 대체
# 한글날: 10/9(토)→10/11(월) 대체
# 크리스마스: 12/25(토)→12/27(월) 대체
KR_HOLIDAYS_2027 = {
    date(2027, 1, 1),  # 신정
    date(2027, 2, 6),  # 설날 연휴 (토)
    date(2027, 2, 7),  # 설날 (일)
    date(2027, 2, 8),  # 설날 연휴 (월)
    date(2027, 2, 9),  # 설날 대체공휴일 (토→화)
    date(2027, 2, 10),  # 설날 대체공휴일 (일→수)
    date(2027, 3, 1),  # 삼일절 (월)
    date(2027, 5, 5),  # 어린이날 (수)
    date(2027, 5, 13),  # 부처님오신날 (목)
    date(2027, 6, 6),  # 현충일 (일)
    date(2027, 6, 7),  # 현충일 대체공휴일 (월)
    date(2027, 8, 15),  # 광복절 (일)
    date(2027, 8, 16),  # 광복절 대체공휴일 (월)
    date(2027, 9, 22),  # 추석 연휴 (수)
    date(2027, 9, 23),  # 추석 (목)
    date(2027, 9, 24),  # 추석 연휴 (금)
    date(2027, 10, 3),  # 개천절 (일)
    date(2027, 10, 4),  # 개천절 대체공휴일 (월)
    date(2027, 10, 9),  # 한글날 (토)
    date(2027, 10, 11),  # 한글날 대체공휴일 (월)
    date(2027, 12, 25),  # 크리스마스 (토)
    date(2027, 12, 27),  # 크리스마스 대체공휴일 (월)
}

# 미국 공휴일 (2027년) - NYSE 휴장일
# Juneteenth: 6/19(토)→6/18(금) 관찰
# Independence Day: 7/4(일)→7/5(월) 관찰
# Christmas: 12/25(토)→12/24(금) 관찰
# New Year's Day 2028: 1/1(토)→12/31(금) 관찰 (2027년 휴장)
US_HOLIDAYS_2027 = {
    date(2027, 1, 1),  # New Year's Day (Fri)
    date(2027, 1, 18),  # MLK Day (3rd Monday January)
    date(2027, 2, 15),  # Presidents' Day (3rd Monday February)
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),  # Memorial Day (last Monday May)
    date(2027, 6, 18),  # Juneteenth observed (Sat → Fri)
    date(2027, 7, 5),  # Independence Day observed (Sun → Mon)
    date(2027, 9, 6),  # Labor Day (1st Monday September)
    date(2027, 11, 25),  # Thanksgiving (4th Thursday November)
    date(2027, 12, 24),  # Christmas observed (Sat → Fri)
    date(2027, 12, 31),  # New Year's Day 2028 observed (Sat → Fri)
}

# 한국 공휴일 (2028년) - 대체공휴일 없음
# 설날: 1/26(수)~1/28(금) - 모두 평일
# 부처님오신날: 5/2(화)
# 추석: 10/10(화)~10/12(목)
KR_HOLIDAYS_2028 = {
    date(2028, 1, 1),  # 신정
    date(2028, 1, 26),  # 설날 연휴 (수)
    date(2028, 1, 27),  # 설날 (목)
    date(2028, 1, 28),  # 설날 연휴 (금)
    date(2028, 3, 1),  # 삼일절 (수)
    date(2028, 5, 2),  # 부처님오신날 (화)
    date(2028, 5, 5),  # 어린이날 (금)
    date(2028, 6, 6),  # 현충일 (화)
    date(2028, 8, 15),  # 광복절 (화)
    date(2028, 10, 3),  # 개천절 (화)
    date(2028, 10, 9),  # 한글날 (월)
    date(2028, 10, 10),  # 추석 연휴 (화)
    date(2028, 10, 11),  # 추석 (수)
    date(2028, 10, 12),  # 추석 연휴 (목)
    date(2028, 12, 25),  # 크리스마스 (월)
}

# 미국 공휴일 (2028년) - NYSE 휴장일
# New Year's Day 2028은 토요일이므로 2027-12-31(금)에 관찰 (US_HOLIDAYS_2027에 포함)
US_HOLIDAYS_2028 = {
    date(2028, 1, 17),  # MLK Day (3rd Monday January)
    date(2028, 2, 21),  # Presidents' Day (3rd Monday February)
    date(2028, 4, 14),  # Good Friday
    date(2028, 5, 29),  # Memorial Day (last Monday May)
    date(2028, 6, 19),  # Juneteenth (Mon)
    date(2028, 7, 4),  # Independence Day (Tue)
    date(2028, 9, 4),  # Labor Day (1st Monday September)
    date(2028, 11, 23),  # Thanksgiving (4th Thursday November)
    date(2028, 12, 25),  # Christmas (Mon)
}

# 한국 공휴일 (2029년) - 대체공휴일 포함
# 설날: 2/12(월)~2/14(수) - 모두 평일
# 어린이날: 5/5(토)→5/7(월) 대체
# 부처님오신날: 5/20(일)→5/21(월) 대체
# 추석: 9/29(토)~10/1(월) - 9/29(토)→10/2(화) 대체, 9/30(일)→10/4(목) 대체
KR_HOLIDAYS_2029 = {
    date(2029, 1, 1),  # 신정
    date(2029, 2, 12),  # 설날 연휴 (월)
    date(2029, 2, 13),  # 설날 (화)
    date(2029, 2, 14),  # 설날 연휴 (수)
    date(2029, 3, 1),  # 삼일절 (목)
    date(2029, 5, 5),  # 어린이날 (토)
    date(2029, 5, 7),  # 어린이날 대체공휴일 (월)
    date(2029, 5, 20),  # 부처님오신날 (일)
    date(2029, 5, 21),  # 부처님오신날 대체공휴일 (월)
    date(2029, 6, 6),  # 현충일 (수)
    date(2029, 8, 15),  # 광복절 (수)
    date(2029, 9, 29),  # 추석 연휴 (토)
    date(2029, 9, 30),  # 추석 (일)
    date(2029, 10, 1),  # 추석 연휴 (월)
    date(2029, 10, 2),  # 추석 대체공휴일 (토→화)
    date(2029, 10, 3),  # 개천절 (수)
    date(2029, 10, 4),  # 추석 대체공휴일 (일→목)
    date(2029, 10, 9),  # 한글날 (화)
    date(2029, 12, 25),  # 크리스마스 (화)
}

# 미국 공휴일 (2029년) - NYSE 휴장일
US_HOLIDAYS_2029 = {
    date(2029, 1, 1),  # New Year's Day (Mon)
    date(2029, 1, 15),  # MLK Day (3rd Monday January)
    date(2029, 2, 19),  # Presidents' Day (3rd Monday February)
    date(2029, 3, 30),  # Good Friday
    date(2029, 5, 28),  # Memorial Day (last Monday May)
    date(2029, 6, 19),  # Juneteenth (Wed)
    date(2029, 7, 4),  # Independence Day (Wed)
    date(2029, 9, 3),  # Labor Day (1st Monday September)
    date(2029, 11, 22),  # Thanksgiving (4th Thursday November)
    date(2029, 12, 25),  # Christmas (Tue)
}

# 한국 공휴일 (2030년) - 대체공휴일 포함
# 설날: 2/2(토)~2/4(월) - 2/2(토)→2/5(화) 대체, 2/3(일)→2/6(수) 대체
# 어린이날: 5/5(일)→5/6(월) 대체
# 추석: 9/19(목)~9/21(토) - 9/21(토)→9/23(월) 대체
KR_HOLIDAYS_2030 = {
    date(2030, 1, 1),  # 신정
    date(2030, 2, 2),  # 설날 연휴 (토)
    date(2030, 2, 3),  # 설날 (일)
    date(2030, 2, 4),  # 설날 연휴 (월)
    date(2030, 2, 5),  # 설날 대체공휴일 (토→화)
    date(2030, 2, 6),  # 설날 대체공휴일 (일→수)
    date(2030, 3, 1),  # 삼일절 (금)
    date(2030, 5, 5),  # 어린이날 (일)
    date(2030, 5, 6),  # 어린이날 대체공휴일 (월)
    date(2030, 5, 9),  # 부처님오신날 (목)
    date(2030, 6, 6),  # 현충일 (목)
    date(2030, 8, 15),  # 광복절 (목)
    date(2030, 9, 19),  # 추석 연휴 (목)
    date(2030, 9, 20),  # 추석 (금)
    date(2030, 9, 21),  # 추석 연휴 (토)
    date(2030, 9, 23),  # 추석 대체공휴일 (월)
    date(2030, 10, 3),  # 개천절 (목)
    date(2030, 10, 9),  # 한글날 (수)
    date(2030, 12, 25),  # 크리스마스 (수)
}

# 미국 공휴일 (2030년) - NYSE 휴장일
US_HOLIDAYS_2030 = {
    date(2030, 1, 1),  # New Year's Day (Tue)
    date(2030, 1, 21),  # MLK Day (3rd Monday January)
    date(2030, 2, 18),  # Presidents' Day (3rd Monday February)
    date(2030, 4, 19),  # Good Friday
    date(2030, 5, 27),  # Memorial Day (last Monday May)
    date(2030, 6, 19),  # Juneteenth (Wed)
    date(2030, 7, 4),  # Independence Day (Thu)
    date(2030, 9, 2),  # Labor Day (1st Monday September)
    date(2030, 11, 28),  # Thanksgiving (4th Thursday November)
    date(2030, 12, 25),  # Christmas (Wed)
}

HOLIDAYS = {
    "KR": KR_HOLIDAYS_2026 | KR_HOLIDAYS_2027 | KR_HOLIDAYS_2028 | KR_HOLIDAYS_2029 | KR_HOLIDAYS_2030,
    "US": US_HOLIDAYS_2026 | US_HOLIDAYS_2027 | US_HOLIDAYS_2028 | US_HOLIDAYS_2029 | US_HOLIDAYS_2030,
}

# 연도별 공휴일 조회를 위한 맵
KR_HOLIDAYS_BY_YEAR = {
    2026: KR_HOLIDAYS_2026,
    2027: KR_HOLIDAYS_2027,
    2028: KR_HOLIDAYS_2028,
    2029: KR_HOLIDAYS_2029,
    2030: KR_HOLIDAYS_2030,
}

US_HOLIDAYS_BY_YEAR = {
    2026: US_HOLIDAYS_2026,
    2027: US_HOLIDAYS_2027,
    2028: US_HOLIDAYS_2028,
    2029: US_HOLIDAYS_2029,
    2030: US_HOLIDAYS_2030,
}


def get_market_time(market: str = "KR") -> datetime:
    """해당 마켓의 현재 시간 반환"""
    config = MARKET_HOURS.get(market)
    if not config:
        raise ValueError(f"Unknown market: {market}")
    return datetime.now(config["tz"])


def is_weekend(dt: Optional[datetime] = None, market: str = "KR") -> bool:
    """주말 여부 확인"""
    if dt is None:
        dt = get_market_time(market)
    return dt.weekday() >= 5


def is_holiday(dt: Optional[datetime] = None, market: str = "KR") -> bool:
    """공휴일 여부 확인"""
    if market == "CRYPTO":
        return False  # Crypto markets never have holidays
    if dt is None:
        dt = get_market_time(market)

    check_date = dt.date() if isinstance(dt, datetime) else dt
    holidays = HOLIDAYS.get(market, set())
    if holidays and check_date.year not in range(2026, 2031):
        logger.warning(f"Holiday data only available for 2026-2030, checking year {check_date.year}")
    return check_date in holidays


def is_market_open(market: str = "KR") -> bool:
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
    return config["open"] <= now.time() <= config["close"]


def get_market_status(market: str = "KR") -> str:
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

    if now.time() < config["open"]:
        return f"{config['name']}: 장전 ({now.strftime('%H:%M')}, 개장 {config['open'].strftime('%H:%M')})"

    return f"{config['name']}: 장후 ({now.strftime('%H:%M')}, 마감 {config['close'].strftime('%H:%M')})"


def infer_market(symbol: str) -> str:
    """심볼에서 마켓 추론"""
    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return "KR"
    if symbol.endswith("-USD") or symbol.endswith("USDT"):
        return "CRYPTO"
    return "US"


def should_check_signals(symbol: str) -> bool:
    """해당 심볼의 시그널 체크가 가능한 시간인지 확인"""
    market = infer_market(symbol)
    if market == "CRYPTO":
        return True  # Crypto: 24/7 trading

    now = get_market_time(market)

    # 주말/공휴일이면 체크 불필요
    if is_weekend(now, market) or is_holiday(now, market):
        return False

    # 장 마감 후 ~ 자정 사이에 일일 데이터 기반 시그널 체크 가능
    config = MARKET_HOURS[market]
    return now.time() >= config["close"]
