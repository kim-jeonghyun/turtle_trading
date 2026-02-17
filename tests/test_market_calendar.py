"""tests/test_market_calendar.py - 마켓 캘린더 테스트"""

import sys
from pathlib import Path
from datetime import datetime, date, time

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.market_calendar import (
    is_weekend,
    is_holiday,
    is_market_open,
    get_market_status,
    infer_market,
    should_check_signals,
    MARKET_HOURS,
    KR_HOLIDAYS_2026,
    US_HOLIDAYS_2026,
)


class TestInferMarket:
    def test_korean_stock(self):
        assert infer_market("005930.KS") == "KR"

    def test_kosdaq(self):
        assert infer_market("035720.KQ") == "KR"

    def test_us_stock(self):
        assert infer_market("AAPL") == "US"

    def test_us_etf(self):
        assert infer_market("SPY") == "US"

    def test_crypto_btc(self):
        assert infer_market("BTC-USD") == "CRYPTO"

    def test_crypto_eth(self):
        assert infer_market("ETH-USD") == "CRYPTO"


class TestWeekend:
    def test_saturday(self):
        # 2026-02-14 is Saturday
        from src.market_calendar import KST
        if hasattr(KST, 'localize'):
            dt = KST.localize(datetime(2026, 2, 14, 12, 0))
        else:
            dt = datetime(2026, 2, 14, 12, 0, tzinfo=KST)
        assert is_weekend(dt) is True

    def test_weekday(self):
        from src.market_calendar import KST
        if hasattr(KST, 'localize'):
            dt = KST.localize(datetime(2026, 2, 16, 12, 0))
        else:
            dt = datetime(2026, 2, 16, 12, 0, tzinfo=KST)
        assert is_weekend(dt) is False


class TestHoliday:
    def test_kr_new_year(self):
        from src.market_calendar import KST
        if hasattr(KST, 'localize'):
            dt = KST.localize(datetime(2026, 1, 1, 12, 0))
        else:
            dt = datetime(2026, 1, 1, 12, 0, tzinfo=KST)
        assert is_holiday(dt, 'KR') is True

    def test_kr_normal_day(self):
        from src.market_calendar import KST
        if hasattr(KST, 'localize'):
            dt = KST.localize(datetime(2026, 2, 20, 12, 0))
        else:
            dt = datetime(2026, 2, 20, 12, 0, tzinfo=KST)
        assert is_holiday(dt, 'KR') is False

    def test_us_thanksgiving(self):
        from src.market_calendar import EST
        if hasattr(EST, 'localize'):
            dt = EST.localize(datetime(2026, 11, 26, 12, 0))
        else:
            dt = datetime(2026, 11, 26, 12, 0, tzinfo=EST)
        assert is_holiday(dt, 'US') is True


class TestMarketHours:
    def test_kr_has_correct_hours(self):
        assert MARKET_HOURS['KR']['open'] == time(9, 0)
        assert MARKET_HOURS['KR']['close'] == time(15, 30)

    def test_us_has_correct_hours(self):
        assert MARKET_HOURS['US']['open'] == time(9, 30)
        assert MARKET_HOURS['US']['close'] == time(16, 0)


class TestMarketStatus:
    def test_returns_string(self):
        status = get_market_status('KR')
        assert isinstance(status, str)
        assert '한국거래소' in status

    def test_us_market_status(self):
        status = get_market_status('US')
        assert isinstance(status, str)
        assert 'NYSE' in status


class TestHolidayCompleteness:
    def test_kr_holidays_count(self):
        assert len(KR_HOLIDAYS_2026) >= 15  # Updated: includes 대체공휴일

    def test_us_holidays_count(self):
        assert len(US_HOLIDAYS_2026) >= 8

    def test_kr_substitute_holiday(self):
        """대체공휴일 확인 - 삼일절 2026/3/1 일요일 → 3/2 월요일"""
        from src.market_calendar import KST
        if hasattr(KST, 'localize'):
            dt = KST.localize(datetime(2026, 3, 2, 12, 0))
        else:
            dt = datetime(2026, 3, 2, 12, 0, tzinfo=KST)
        assert is_holiday(dt, 'KR') is True
