"""
scripts/check_positions.py - check_entry_signals() 단위 테스트

System 1 필터 로직:
- 직전 System 1 거래가 수익이면 20일 브레이크아웃 진입 스킵
- 단, 55일 failsafe breakout이면 필터 무시하고 진입 허용
- System 2는 필터 없음
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

# scripts/ 디렉토리를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.check_positions import check_entry_signals
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
