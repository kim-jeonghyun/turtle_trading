"""
scripts/check_positions.py 단위 테스트

- check_entry_signals(): 진입 시그널 + System 1 필터
- check_exit_signals(): 청산 시그널 (10일/20일 이탈)
- check_stop_loss(): 스톱로스 발동 판단
- _should_allow_entry(): System 1 필터 헬퍼
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

# scripts/ 디렉토리를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.check_positions import (
    _should_allow_entry,
    check_entry_signals,
    check_exit_signals,
    check_stop_loss,
)
from src.position_tracker import Position
from src.types import SignalType

# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------

def _make_df(
    today_high: float,
    today_low: float,
    today_close: float,
    dc_high_20: float,
    dc_low_20: float,
    dc_high_55: float,
    dc_low_55: float,
    n_value: float = 2.0,
) -> pd.DataFrame:
    """최소 2행 DataFrame 생성.

    check_entry_signals 는 df.iloc[-2] (yesterday) 의 Donchian 값과
    df.iloc[-1] (today) 의 high/low 를 비교하므로 두 행이 필요하다.
    yesterday 행의 Donchian 값이 돌파 기준선이 된다.
    """
    yesterday = {
        "date": pd.Timestamp("2025-03-01"),
        "high": 100.0,
        "low": 98.0,
        "close": 99.0,
        "N": n_value,
        "dc_high_20": dc_high_20,
        "dc_low_20": dc_low_20,
        "dc_high_55": dc_high_55,
        "dc_low_55": dc_low_55,
    }
    today = {
        "date": pd.Timestamp("2025-03-02"),
        "high": today_high,
        "low": today_low,
        "close": today_close,
        "N": n_value,
        "dc_high_20": dc_high_20,
        "dc_low_20": dc_low_20,
        "dc_high_55": dc_high_55,
        "dc_low_55": dc_low_55,
    }
    return pd.DataFrame([yesterday, today])


def _make_closed_position(
    symbol: str,
    system: int = 1,
    pnl: float = 100.0,
    exit_date: str = "2025-02-15",
) -> Position:
    """청산된 Position 객체 생성."""
    return Position(
        position_id=f"{symbol}_{system}_LONG_20250201_120000",
        symbol=symbol,
        system=system,
        direction="LONG",
        entry_date="2025-02-01",
        entry_price=100.0,
        entry_n=2.0,
        units=1,
        max_units=4,
        shares_per_unit=40,
        total_shares=40,
        stop_loss=96.0,
        pyramid_level=0,
        exit_period=10,
        status="closed",
        last_update="2025-02-15T12:00:00",
        exit_date=exit_date,
        exit_price=110.0 if pnl > 0 else 90.0,
        pnl=pnl,
    )


def _make_tracker_mock(symbol: str, positions: list) -> MagicMock:
    """get_position_history 를 mocking 한 PositionTracker."""
    tracker = MagicMock()
    tracker.get_position_history.return_value = positions
    return tracker


# ---------------------------------------------------------------------------
# 테스트 상수
# ---------------------------------------------------------------------------

SYMBOL_US = "SPY"       # 미국 심볼 — 롱/숏 모두 허용
SYMBOL_KR = "005930.KS"  # 한국 심볼 — 롱만 허용

# 기준 Donchian 값 (yesterday 행에 설정)
DC_HIGH_20 = 105.0
DC_LOW_20 = 95.0
DC_HIGH_55 = 110.0
DC_LOW_55 = 90.0

# 돌파 가격 (today 행)
ABOVE_20_ONLY = DC_HIGH_20 + 1.0   # 20일 돌파, 55일 미돌파
ABOVE_BOTH = DC_HIGH_55 + 1.0      # 20일 + 55일 모두 돌파

BELOW_20_ONLY = DC_LOW_20 - 1.0    # 20일 이탈, 55일 미이탈
BELOW_BOTH = DC_LOW_55 - 1.0       # 20일 + 55일 모두 이탈


# ---------------------------------------------------------------------------
# 테스트 클래스
# ---------------------------------------------------------------------------

class TestSystem1FilterLong:
    """System 1 롱 진입 필터 테스트"""

    def test_system1_filter_skip_20day_breakout_after_profitable_trade(self):
        """직전 System 1 거래 수익 + 20일만 돌파 → 진입 스킵"""
        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        profitable_pos = _make_closed_position(SYMBOL_US, system=1, pnl=200.0)
        tracker = _make_tracker_mock(SYMBOL_US, [profitable_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 0, (
            "직전 System 1 거래가 수익일 때 20일 돌파 롱 진입은 스킵되어야 한다"
        )

    def test_system1_filter_failsafe_55day_breakout_after_profitable_trade(self):
        """직전 System 1 거래 수익 + 20일 & 55일 모두 돌파 → failsafe override로 진입 허용"""
        df = _make_df(
            today_high=ABOVE_BOTH,
            today_low=99.0,
            today_close=ABOVE_BOTH,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        profitable_pos = _make_closed_position(SYMBOL_US, system=1, pnl=200.0)
        tracker = _make_tracker_mock(SYMBOL_US, [profitable_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, (
            "55일 failsafe breakout은 직전 수익 거래 필터를 무시하고 롱 진입을 허용해야 한다"
        )
        assert long_signals[0]["type"] == SignalType.ENTRY_LONG.value
        assert long_signals[0]["system"] == 1

    def test_system1_no_filter_after_losing_trade(self):
        """직전 System 1 거래 손실 + 20일 돌파 → 필터 미적용, 진입 허용"""
        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        losing_pos = _make_closed_position(SYMBOL_US, system=1, pnl=-150.0)
        tracker = _make_tracker_mock(SYMBOL_US, [losing_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, (
            "직전 System 1 거래가 손실이면 20일 돌파 롱 진입이 허용되어야 한다"
        )
        assert long_signals[0]["type"] == SignalType.ENTRY_LONG.value

    def test_system1_no_filter_when_no_history(self):
        """System 1 거래 이력 없음 → 필터 미적용, 진입 허용"""
        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        tracker = _make_tracker_mock(SYMBOL_US, [])  # 빈 이력

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, (
            "System 1 거래 이력이 없으면 필터 없이 진입이 허용되어야 한다"
        )


class TestSystem1FilterShort:
    """System 1 숏 진입 필터 테스트 (미국 심볼 전용)"""

    def test_system1_filter_short_skip_20day_after_profitable(self):
        """직전 System 1 거래 수익 + 20일만 이탈 → 숏 진입 스킵"""
        df = _make_df(
            today_high=99.0,
            today_low=BELOW_20_ONLY,
            today_close=BELOW_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        profitable_pos = _make_closed_position(SYMBOL_US, system=1, pnl=200.0)
        tracker = _make_tracker_mock(SYMBOL_US, [profitable_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 0, (
            "직전 System 1 거래가 수익일 때 20일 이탈 숏 진입은 스킵되어야 한다"
        )

    def test_system1_filter_short_failsafe_55day_after_profitable(self):
        """직전 System 1 거래 수익 + 20일 & 55일 모두 이탈 → failsafe override로 숏 진입 허용"""
        df = _make_df(
            today_high=99.0,
            today_low=BELOW_BOTH,
            today_close=BELOW_BOTH,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        profitable_pos = _make_closed_position(SYMBOL_US, system=1, pnl=200.0)
        tracker = _make_tracker_mock(SYMBOL_US, [profitable_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 1, (
            "55일 failsafe breakout은 직전 수익 거래 필터를 무시하고 숏 진입을 허용해야 한다"
        )
        assert short_signals[0]["type"] == SignalType.ENTRY_SHORT.value
        assert short_signals[0]["system"] == 1

    def test_system1_short_blocked_for_korean_market(self):
        """한국 심볼은 공매도 제한 — 숏 시그널이 생성되지 않아야 함"""
        df = _make_df(
            today_high=99.0,
            today_low=BELOW_BOTH,  # 55일 이탈로 failsafe 조건 만족
            today_close=BELOW_BOTH,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        profitable_pos = _make_closed_position(SYMBOL_KR, system=1, pnl=200.0)
        tracker = _make_tracker_mock(SYMBOL_KR, [profitable_pos])

        signals = check_entry_signals(df, SYMBOL_KR, system=1, tracker=tracker)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 0, (
            "한국 시장 종목은 공매도 제한이므로 숏 시그널이 생성되면 안 된다"
        )


class TestSystem2NoFilter:
    """System 2는 직전 거래 수익 여부에 관계없이 필터를 적용하지 않는다."""

    def test_system2_no_filter_after_profitable_trade(self):
        """System 2: 직전 거래 수익이어도 55일 돌파 시 롱 진입 허용"""
        df = _make_df(
            today_high=ABOVE_BOTH,  # 55일 돌파
            today_low=99.0,
            today_close=ABOVE_BOTH,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        profitable_pos = _make_closed_position(SYMBOL_US, system=1, pnl=500.0)
        tracker = _make_tracker_mock(SYMBOL_US, [profitable_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=2, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, (
            "System 2는 직전 거래 수익 여부와 무관하게 55일 돌파 롱 진입을 허용해야 한다"
        )
        assert long_signals[0]["system"] == 2

    def test_system2_no_filter_with_profitable_system2_history(self):
        """System 2: 직전 System 2 거래가 수익이어도 진입 허용 (System 2 필터 없음)"""
        df = _make_df(
            today_high=ABOVE_BOTH,
            today_low=99.0,
            today_close=ABOVE_BOTH,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        # System 2 수익 거래 이력 생성
        profitable_s2_pos = _make_closed_position(SYMBOL_US, system=2, pnl=800.0)
        tracker = _make_tracker_mock(SYMBOL_US, [profitable_s2_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=2, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, (
            "System 2는 이전 System 2 수익 거래가 있어도 진입 필터를 적용하지 않아야 한다"
        )


class TestNoTrackerNoFilter:
    """tracker=None 일 때 필터 없이 시그널이 정상 생성되어야 한다."""

    def test_no_tracker_long_signal_returned(self):
        """tracker=None + 20일 돌파 → 롱 진입 시그널 반환"""
        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, (
            "tracker 가 None 이면 필터를 적용하지 않고 롱 진입 시그널을 반환해야 한다"
        )

    def test_no_tracker_short_signal_returned(self):
        """tracker=None + 20일 이탈 → 숏 진입 시그널 반환 (미국 심볼)"""
        df = _make_df(
            today_high=99.0,
            today_low=BELOW_20_ONLY,
            today_close=BELOW_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 1, (
            "tracker 가 None 이면 필터를 적용하지 않고 숏 진입 시그널을 반환해야 한다"
        )


class TestSignalStructure:
    """반환된 시그널 딕셔너리의 구조와 값 검증."""

    def test_long_signal_keys_and_values(self):
        """롱 시그널 딕셔너리에 필수 키가 포함되어야 한다."""
        n_value = 2.0
        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
            n_value=n_value,
        )
        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)

        assert len(signals) >= 1
        sig = next(s for s in signals if s["direction"] == "LONG")

        required_keys = {
            "symbol", "type", "system", "direction", "price",
            "current", "n", "stop_loss", "date", "message",
        }
        assert required_keys.issubset(sig.keys()), (
            f"시그널에 필수 키가 누락됨: {required_keys - sig.keys()}"
        )

        assert sig["symbol"] == SYMBOL_US
        assert sig["direction"] == "LONG"
        assert sig["system"] == 1
        assert sig["type"] == SignalType.ENTRY_LONG.value
        assert sig["price"] == DC_HIGH_20  # yesterday 의 dc_high_20
        assert sig["n"] == n_value
        assert sig["stop_loss"] == DC_HIGH_20 - 2 * n_value
        assert sig["date"] == "2025-03-02"

    def test_short_signal_keys_and_values(self):
        """숏 시그널 딕셔너리에 필수 키가 포함되어야 한다."""
        n_value = 2.0
        df = _make_df(
            today_high=99.0,
            today_low=BELOW_20_ONLY,
            today_close=BELOW_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
            n_value=n_value,
        )
        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)

        assert len(signals) >= 1
        sig = next(s for s in signals if s["direction"] == "SHORT")

        required_keys = {
            "symbol", "type", "system", "direction", "price",
            "current", "n", "stop_loss", "date", "message",
        }
        assert required_keys.issubset(sig.keys())

        assert sig["symbol"] == SYMBOL_US
        assert sig["direction"] == "SHORT"
        assert sig["system"] == 1
        assert sig["type"] == SignalType.ENTRY_SHORT.value
        assert sig["price"] == DC_LOW_20  # yesterday 의 dc_low_20
        assert sig["stop_loss"] == DC_LOW_20 + 2 * n_value  # 숏 스톱은 위로

    def test_no_signal_when_no_breakout(self):
        """돌파/이탈 조건 미충족 → 시그널 없음"""
        df = _make_df(
            today_high=DC_HIGH_20 - 0.5,   # 20일 고가 미달
            today_low=DC_LOW_20 + 0.5,     # 20일 저가 미달
            today_close=100.0,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)

        assert len(signals) == 0, "돌파 조건이 없으면 시그널이 생성되어서는 안 된다"

    def test_insufficient_data_returns_empty(self):
        """df 행 수가 2 미만이면 빈 리스트 반환"""
        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        single_row_df = df.iloc[:1]

        signals = check_entry_signals(single_row_df, SYMBOL_US, system=1, tracker=None)

        assert signals == [], "데이터가 1행뿐이면 빈 리스트를 반환해야 한다"


class TestBoundaryValues:
    """Donchian 채널 경계값(정확히 같은 값) 테스트.

    프로덕션 코드는 strict 비교(>, <)를 사용하므로
    정확히 채널 값과 같은 경우의 동작을 명시적으로 검증한다.
    """

    def test_high_equals_dc_high_20_no_breakout(self):
        """today high == dc_high_20 → 돌파 아님 (strict >), 시그널 없음"""
        df = _make_df(
            today_high=DC_HIGH_20,  # 정확히 같음
            today_low=99.0,
            today_close=DC_HIGH_20,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 0, (
            "today high == dc_high_20 일 때 strict > 비교이므로 돌파가 아니어야 한다"
        )

    def test_low_equals_dc_low_20_no_breakout(self):
        """today low == dc_low_20 → 이탈 아님 (strict <), 숏 시그널 없음"""
        df = _make_df(
            today_high=99.0,
            today_low=DC_LOW_20,  # 정확히 같음
            today_close=DC_LOW_20,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 0, (
            "today low == dc_low_20 일 때 strict < 비교이므로 이탈이 아니어야 한다"
        )

    def test_high_equals_dc_high_55_no_failsafe(self):
        """수익 거래 후 today high == dc_high_55 → failsafe 비발동, 스킵"""
        df = _make_df(
            today_high=DC_HIGH_55,  # 55일 채널과 정확히 같음 (> 아님)
            today_low=99.0,
            today_close=DC_HIGH_55,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        profitable_pos = _make_closed_position(SYMBOL_US, system=1, pnl=200.0)
        tracker = _make_tracker_mock(SYMBOL_US, [profitable_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 0, (
            "today high == dc_high_55 일 때 strict > 비교이므로 failsafe가 발동하지 않아야 한다"
        )

    def test_low_equals_dc_low_55_no_failsafe(self):
        """수익 거래 후 today low == dc_low_55 → failsafe 비발동, 숏 스킵"""
        df = _make_df(
            today_high=99.0,
            today_low=DC_LOW_55,  # 55일 채널과 정확히 같음 (< 아님)
            today_close=DC_LOW_55,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        profitable_pos = _make_closed_position(SYMBOL_US, system=1, pnl=200.0)
        tracker = _make_tracker_mock(SYMBOL_US, [profitable_pos])

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 0, (
            "today low == dc_low_55 일 때 strict < 비교이므로 failsafe가 발동하지 않아야 한다"
        )


class TestSystem1FilterLastTradeSelection:
    """여러 청산 이력 중 가장 최근 System 1 거래를 기준으로 필터가 적용되는지 검증."""

    def test_most_recent_system1_trade_is_used_for_filter(self):
        """이전 수익 + 가장 최근 손실 → 필터 미적용 (최근 거래 기준)"""
        older_profitable = _make_closed_position(
            SYMBOL_US, system=1, pnl=300.0, exit_date="2025-01-15"
        )
        recent_losing = _make_closed_position(
            SYMBOL_US, system=1, pnl=-100.0, exit_date="2025-02-15"
        )
        tracker = _make_tracker_mock(SYMBOL_US, [older_profitable, recent_losing])

        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, (
            "가장 최근 System 1 거래가 손실이면 이전 수익 거래와 무관하게 진입이 허용되어야 한다"
        )

    def test_most_recent_system1_trade_profitable_skips(self):
        """이전 손실 + 가장 최근 수익 → 필터 적용, 20일 돌파 스킵"""
        older_losing = _make_closed_position(
            SYMBOL_US, system=1, pnl=-200.0, exit_date="2025-01-10"
        )
        recent_profitable = _make_closed_position(
            SYMBOL_US, system=1, pnl=400.0, exit_date="2025-02-20"
        )
        tracker = _make_tracker_mock(SYMBOL_US, [older_losing, recent_profitable])

        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 0, (
            "가장 최근 System 1 거래가 수익이면 20일 돌파 롱 진입은 스킵되어야 한다"
        )

    def test_system2_history_does_not_affect_system1_filter(self):
        """System 2 수익 이력은 System 1 필터에 영향을 주지 않아야 한다."""
        system2_profitable = _make_closed_position(SYMBOL_US, system=2, pnl=1000.0)
        tracker = _make_tracker_mock(SYMBOL_US, [system2_profitable])

        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )

        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=tracker)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, (
            "System 2 수익 이력은 System 1 필터에 영향을 주지 않아야 한다"
        )


class TestShouldAllowEntry:
    """_should_allow_entry() 헬퍼 함수 직접 단위 테스트."""

    def test_not_profitable_always_allows(self):
        assert _should_allow_entry(system=1, is_profitable=False, is_55day_breakout=False) is True
        assert _should_allow_entry(system=1, is_profitable=False, is_55day_breakout=True) is True

    def test_profitable_system1_with_55day_breakout_allows(self):
        assert _should_allow_entry(system=1, is_profitable=True, is_55day_breakout=True) is True

    def test_profitable_system1_without_55day_breakout_blocks(self):
        assert _should_allow_entry(system=1, is_profitable=True, is_55day_breakout=False) is False

    def test_system2_always_allows_regardless_of_profitability(self):
        """System 2는 필터 없음 — is_profitable 값에 관계없이 항상 True 반환."""
        assert _should_allow_entry(system=2, is_profitable=True, is_55day_breakout=True) is True
        assert _should_allow_entry(system=2, is_profitable=True, is_55day_breakout=False) is True
        assert _should_allow_entry(system=2, is_profitable=False, is_55day_breakout=False) is True


# ---------------------------------------------------------------------------
# 청산 시그널 헬퍼
# ---------------------------------------------------------------------------

# 청산용 Donchian 채널 값
DC_HIGH_10 = 103.0  # System 1 숏 청산 기준
DC_LOW_10 = 97.0    # System 1 롱 청산 기준
DC_HIGH_20_EXIT = 107.0  # System 2 숏 청산 기준
DC_LOW_20_EXIT = 93.0    # System 2 롱 청산 기준


def _make_exit_df(
    today_high: float,
    today_low: float,
    today_close: float,
    n_value: float = 2.0,
) -> pd.DataFrame:
    """check_exit_signals용 2행 DataFrame 생성."""
    yesterday = {
        "date": pd.Timestamp("2025-03-01"),
        "high": 100.0,
        "low": 98.0,
        "close": 99.0,
        "N": n_value,
        "dc_low_10": DC_LOW_10,
        "dc_high_10": DC_HIGH_10,
        "dc_low_20": DC_LOW_20_EXIT,
        "dc_high_20": DC_HIGH_20_EXIT,
    }
    today = {
        "date": pd.Timestamp("2025-03-02"),
        "high": today_high,
        "low": today_low,
        "close": today_close,
        "N": n_value,
        "dc_low_10": DC_LOW_10,
        "dc_high_10": DC_HIGH_10,
        "dc_low_20": DC_LOW_20_EXIT,
        "dc_high_20": DC_HIGH_20_EXIT,
    }
    return pd.DataFrame([yesterday, today])


def _make_open_position(
    symbol: str = "SPY",
    direction: str = "LONG",
    system: int = 1,
    stop_loss: float = 96.0,
) -> Position:
    """오픈 포지션 생성."""
    return Position(
        position_id=f"{symbol}_{system}_{direction}_20250201_120000",
        symbol=symbol,
        system=system,
        direction=direction,
        entry_date="2025-02-01",
        entry_price=100.0,
        entry_n=2.0,
        units=1,
        max_units=4,
        shares_per_unit=40,
        total_shares=40,
        stop_loss=stop_loss,
        pyramid_level=0,
        exit_period=10 if system == 1 else 20,
        status="open",
        last_update="2025-02-15T12:00:00",
    )


# ---------------------------------------------------------------------------
# check_exit_signals() 테스트
# ---------------------------------------------------------------------------


class TestExitSignalsLong:
    """롱 포지션 청산 시그널 테스트."""

    def test_system1_long_exit_below_dc_low_10(self):
        """System 1 롱: today low < yesterday dc_low_10 → 청산"""
        pos = _make_open_position(direction="LONG", system=1)
        df = _make_exit_df(today_high=100.0, today_low=DC_LOW_10 - 1.0, today_close=97.0)

        result = check_exit_signals(df, pos, system=1)

        assert result is not None
        assert result["type"] == SignalType.EXIT_LONG.value
        assert result["position_id"] == pos.position_id
        assert result["price"] == DC_LOW_10

    def test_system2_long_exit_below_dc_low_20(self):
        """System 2 롱: today low < yesterday dc_low_20 → 청산"""
        pos = _make_open_position(direction="LONG", system=2)
        df = _make_exit_df(today_high=100.0, today_low=DC_LOW_20_EXIT - 1.0, today_close=93.0)

        result = check_exit_signals(df, pos, system=2)

        assert result is not None
        assert result["type"] == SignalType.EXIT_LONG.value
        assert result["price"] == DC_LOW_20_EXIT

    def test_long_no_exit_when_above_channel(self):
        """롱: today low > dc_low_10 → 청산 아님"""
        pos = _make_open_position(direction="LONG", system=1)
        df = _make_exit_df(today_high=102.0, today_low=DC_LOW_10 + 1.0, today_close=101.0)

        result = check_exit_signals(df, pos, system=1)

        assert result is None

    def test_long_no_exit_boundary_equal(self):
        """롱: today low == dc_low_10 → strict < 비교이므로 청산 아님"""
        pos = _make_open_position(direction="LONG", system=1)
        df = _make_exit_df(today_high=100.0, today_low=DC_LOW_10, today_close=98.0)

        result = check_exit_signals(df, pos, system=1)

        assert result is None

    def test_long_exit_insufficient_data(self):
        """데이터 1행이면 None 반환"""
        pos = _make_open_position(direction="LONG", system=1)
        df = _make_exit_df(today_high=100.0, today_low=90.0, today_close=91.0)
        single = df.iloc[:1]

        result = check_exit_signals(single, pos, system=1)

        assert result is None


class TestExitSignalsShort:
    """숏 포지션 청산 시그널 테스트."""

    def test_system1_short_exit_above_dc_high_10(self):
        """System 1 숏: today high > yesterday dc_high_10 → 청산"""
        pos = _make_open_position(direction="SHORT", system=1)
        df = _make_exit_df(today_high=DC_HIGH_10 + 1.0, today_low=99.0, today_close=103.0)

        result = check_exit_signals(df, pos, system=1)

        assert result is not None
        assert result["type"] == SignalType.EXIT_SHORT.value
        assert result["position_id"] == pos.position_id
        assert result["price"] == DC_HIGH_10

    def test_system2_short_exit_above_dc_high_20(self):
        """System 2 숏: today high > yesterday dc_high_20 → 청산"""
        pos = _make_open_position(direction="SHORT", system=2)
        df = _make_exit_df(today_high=DC_HIGH_20_EXIT + 1.0, today_low=99.0, today_close=107.0)

        result = check_exit_signals(df, pos, system=2)

        assert result is not None
        assert result["type"] == SignalType.EXIT_SHORT.value
        assert result["price"] == DC_HIGH_20_EXIT

    def test_short_no_exit_when_below_channel(self):
        """숏: today high < dc_high_10 → 청산 아님"""
        pos = _make_open_position(direction="SHORT", system=1)
        df = _make_exit_df(today_high=DC_HIGH_10 - 1.0, today_low=98.0, today_close=100.0)

        result = check_exit_signals(df, pos, system=1)

        assert result is None

    def test_short_no_exit_boundary_equal(self):
        """숏: today high == dc_high_10 → strict > 비교이므로 청산 아님"""
        pos = _make_open_position(direction="SHORT", system=1)
        df = _make_exit_df(today_high=DC_HIGH_10, today_low=98.0, today_close=100.0)

        result = check_exit_signals(df, pos, system=1)

        assert result is None


class TestExitSignalStructure:
    """청산 시그널 딕셔너리 구조 검증."""

    def test_exit_signal_has_required_keys(self):
        """청산 시그널에 필수 키가 포함되어야 한다."""
        pos = _make_open_position(direction="LONG", system=1, stop_loss=90.0)
        df = _make_exit_df(today_high=100.0, today_low=DC_LOW_10 - 1.0, today_close=96.5)

        result = check_exit_signals(df, pos, system=1)

        assert result is not None
        required_keys = {"symbol", "type", "system", "position_id", "price", "current", "n", "date", "message"}
        assert required_keys.issubset(result.keys()), f"누락 키: {required_keys - result.keys()}"
        assert result["symbol"] == pos.symbol
        assert result["system"] == 1
        assert result["date"] == "2025-03-02"


# ---------------------------------------------------------------------------
# check_stop_loss() 테스트
# ---------------------------------------------------------------------------


class TestStopLoss:
    """check_stop_loss() 스톱로스 발동 테스트."""

    def test_long_stop_triggered_low_below_stop(self):
        """LONG: 장중 저가가 stop_loss 이하이면 발동"""
        pos = _make_open_position(direction="LONG", stop_loss=96.0)
        today = {"low": 95.5, "high": 100.0}

        assert check_stop_loss(pos, today) is True

    def test_long_stop_triggered_low_equals_stop(self):
        """LONG: 장중 저가가 stop_loss와 정확히 같으면 발동 (<=)"""
        pos = _make_open_position(direction="LONG", stop_loss=96.0)
        today = {"low": 96.0, "high": 100.0}

        assert check_stop_loss(pos, today) is True

    def test_long_stop_not_triggered(self):
        """LONG: 장중 저가가 stop_loss 초과이면 미발동"""
        pos = _make_open_position(direction="LONG", stop_loss=96.0)
        today = {"low": 96.5, "high": 100.0}

        assert check_stop_loss(pos, today) is False

    def test_short_stop_triggered_high_above_stop(self):
        """SHORT: 장중 고가가 stop_loss 이상이면 발동"""
        pos = _make_open_position(direction="SHORT", stop_loss=104.0)
        today = {"low": 99.0, "high": 104.5}

        assert check_stop_loss(pos, today) is True

    def test_short_stop_triggered_high_equals_stop(self):
        """SHORT: 장중 고가가 stop_loss와 정확히 같으면 발동 (>=)"""
        pos = _make_open_position(direction="SHORT", stop_loss=104.0)
        today = {"low": 99.0, "high": 104.0}

        assert check_stop_loss(pos, today) is True

    def test_short_stop_not_triggered(self):
        """SHORT: 장중 고가가 stop_loss 미만이면 미발동"""
        pos = _make_open_position(direction="SHORT", stop_loss=104.0)
        today = {"low": 99.0, "high": 103.5}

        assert check_stop_loss(pos, today) is False

    @pytest.mark.parametrize(
        "direction,stop_loss,low,high,expected",
        [
            ("LONG", 100.0, 99.0, 105.0, True),
            ("LONG", 100.0, 100.0, 105.0, True),
            ("LONG", 100.0, 100.01, 105.0, False),
            ("SHORT", 100.0, 95.0, 101.0, True),
            ("SHORT", 100.0, 95.0, 100.0, True),
            ("SHORT", 100.0, 95.0, 99.99, False),
        ],
        ids=[
            "long-below", "long-equal", "long-above",
            "short-above", "short-equal", "short-below",
        ],
    )
    def test_stop_loss_parametrized(self, direction, stop_loss, low, high, expected):
        """다양한 가격 조합의 스톱로스 발동 경계값 검증."""
        pos = _make_open_position(direction=direction, stop_loss=stop_loss)
        today = {"low": low, "high": high}

        assert check_stop_loss(pos, today) is expected


# ---------------------------------------------------------------------------
# 리스크 매니저 통합 테스트
# ---------------------------------------------------------------------------


class TestRiskManagerIntegration:
    """진입 시그널이 리스크 매니저에 의해 필터링되는 시나리오 검증.

    check_entry_signals 자체는 리스크 매니저를 호출하지 않으므로,
    _run_checks 에서 사용하는 패턴을 재현하여 통합 동작을 검증한다.
    """

    def test_signal_passes_risk_check(self):
        """리스크 한도 내이면 시그널이 유지된다."""
        from src.risk_manager import PortfolioRiskManager
        from src.types import Direction

        risk_mgr = PortfolioRiskManager(symbol_groups={})
        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)

        accepted = []
        for sig in signals:
            direction = Direction.LONG if sig["direction"] == "LONG" else Direction.SHORT
            can_add, _ = risk_mgr.can_add_position(
                symbol=sig["symbol"], units=1, n_value=sig["n"], direction=direction,
            )
            if can_add:
                accepted.append(sig)
                risk_mgr.add_position(sig["symbol"], 1, sig["n"], direction)

        assert len(accepted) >= 1, "리스크 한도 내에서 시그널이 통과해야 한다"

    def test_signal_blocked_by_direction_limit(self):
        """단일 방향 한도(12 Units) 초과 시 시그널이 거부된다."""
        from src.risk_manager import PortfolioRiskManager
        from src.types import Direction

        risk_mgr = PortfolioRiskManager(symbol_groups={})

        # 12개 롱 포지션을 미리 추가하여 한도 채움
        for i in range(12):
            risk_mgr.add_position(f"SYM{i}", 1, 2.0, Direction.LONG)

        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        signals = check_entry_signals(df, SYMBOL_US, system=1, tracker=None)
        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) >= 1, "시그널 자체는 생성되어야 한다"

        can_add, reason = risk_mgr.can_add_position(
            symbol=SYMBOL_US, units=1, n_value=long_signals[0]["n"], direction=Direction.LONG,
        )
        assert can_add is False, f"단일 방향 12 Units 초과 시 거부되어야 한다. reason={reason}"
