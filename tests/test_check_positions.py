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

# 프로젝트 루트와 tests/ 디렉토리를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

# Integration test imports
import fcntl
import os
from datetime import datetime
from unittest.mock import AsyncMock, patch

from conftest import PatchManager

from scripts.check_positions import (
    _build_trade_record,
    _run_checks,
    _should_allow_entry,
    acquire_lock,
    check_entry_signals,
    check_exit_signals,
    check_stop_loss,
    is_korean_market,
    load_config,
    main,
    release_lock,
    setup_notifier,
    setup_risk_manager,
)
from src.position_tracker import Position
from src.types import AssetGroup, Direction, SignalType
from src.universe_manager import Asset

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

SYMBOL_US = "SPY"  # 미국 심볼 — 롱/숏 모두 허용
SYMBOL_KR = "005930.KS"  # 한국 심볼 — 롱만 허용

# 기준 Donchian 값 (yesterday 행에 설정)
DC_HIGH_20 = 105.0
DC_LOW_20 = 95.0
DC_HIGH_55 = 110.0
DC_LOW_55 = 90.0

# 돌파 가격 (today 행)
ABOVE_20_ONLY = DC_HIGH_20 + 1.0  # 20일 돌파, 55일 미돌파
ABOVE_BOTH = DC_HIGH_55 + 1.0  # 20일 + 55일 모두 돌파

BELOW_20_ONLY = DC_LOW_20 - 1.0  # 20일 이탈, 55일 미이탈
BELOW_BOTH = DC_LOW_55 - 1.0  # 20일 + 55일 모두 이탈


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
        assert len(long_signals) == 0, "직전 System 1 거래가 수익일 때 20일 돌파 롱 진입은 스킵되어야 한다"

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
        assert len(long_signals) == 1, "55일 failsafe breakout은 직전 수익 거래 필터를 무시하고 롱 진입을 허용해야 한다"
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
        assert len(long_signals) == 1, "직전 System 1 거래가 손실이면 20일 돌파 롱 진입이 허용되어야 한다"
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
        assert len(long_signals) == 1, "System 1 거래 이력이 없으면 필터 없이 진입이 허용되어야 한다"


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
        assert len(short_signals) == 0, "직전 System 1 거래가 수익일 때 20일 이탈 숏 진입은 스킵되어야 한다"

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
        assert len(short_signals) == 0, "한국 시장 종목은 공매도 제한이므로 숏 시그널이 생성되면 안 된다"


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
        assert len(long_signals) == 1, "System 2는 직전 거래 수익 여부와 무관하게 55일 돌파 롱 진입을 허용해야 한다"
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
        assert len(long_signals) == 1, "System 2는 이전 System 2 수익 거래가 있어도 진입 필터를 적용하지 않아야 한다"


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
        assert len(long_signals) == 1, "tracker 가 None 이면 필터를 적용하지 않고 롱 진입 시그널을 반환해야 한다"

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
        assert len(short_signals) == 1, "tracker 가 None 이면 필터를 적용하지 않고 숏 진입 시그널을 반환해야 한다"


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
            "symbol",
            "type",
            "system",
            "direction",
            "price",
            "current",
            "n",
            "stop_loss",
            "date",
            "message",
        }
        assert required_keys.issubset(sig.keys()), f"시그널에 필수 키가 누락됨: {required_keys - sig.keys()}"

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
            "symbol",
            "type",
            "system",
            "direction",
            "price",
            "current",
            "n",
            "stop_loss",
            "date",
            "message",
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
            today_high=DC_HIGH_20 - 0.5,  # 20일 고가 미달
            today_low=DC_LOW_20 + 0.5,  # 20일 저가 미달
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
        assert len(long_signals) == 0, "today high == dc_high_20 일 때 strict > 비교이므로 돌파가 아니어야 한다"

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
        assert len(short_signals) == 0, "today low == dc_low_20 일 때 strict < 비교이므로 이탈이 아니어야 한다"

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
        older_profitable = _make_closed_position(SYMBOL_US, system=1, pnl=300.0, exit_date="2025-01-15")
        recent_losing = _make_closed_position(SYMBOL_US, system=1, pnl=-100.0, exit_date="2025-02-15")
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
        older_losing = _make_closed_position(SYMBOL_US, system=1, pnl=-200.0, exit_date="2025-01-10")
        recent_profitable = _make_closed_position(SYMBOL_US, system=1, pnl=400.0, exit_date="2025-02-20")
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
        assert len(long_signals) == 0, "가장 최근 System 1 거래가 수익이면 20일 돌파 롱 진입은 스킵되어야 한다"

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
        assert len(long_signals) == 1, "System 2 수익 이력은 System 1 필터에 영향을 주지 않아야 한다"


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
DC_LOW_10 = 97.0  # System 1 롱 청산 기준
DC_HIGH_20_EXIT = 107.0  # System 2 숏 청산 기준
DC_LOW_20_EXIT = 93.0  # System 2 롱 청산 기준


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
            "long-below",
            "long-equal",
            "long-above",
            "short-above",
            "short-equal",
            "short-below",
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
            direction = Direction(sig["direction"])
            can_add, _ = risk_mgr.can_add_position(
                symbol=sig["symbol"],
                units=1,
                n_value=sig["n"],
                direction=direction,
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
            symbol=SYMBOL_US,
            units=1,
            n_value=long_signals[0]["n"],
            direction=Direction.LONG,
        )
        assert can_add is False, f"단일 방향 12 Units 초과 시 거부되어야 한다. reason={reason}"


# ---------------------------------------------------------------------------
# Integration tests: is_korean_market
# ---------------------------------------------------------------------------


class TestIsKoreanMarket:
    """is_korean_market() 한국 시장 판별 테스트."""

    def test_ks_suffix(self):
        assert is_korean_market("005930.KS") is True

    def test_kq_suffix(self):
        assert is_korean_market("035420.KQ") is True

    def test_us_symbol(self):
        assert is_korean_market("SPY") is False

    def test_crypto_symbol(self):
        assert is_korean_market("BTC-USD") is False


# ---------------------------------------------------------------------------
# Integration tests: acquire_lock / release_lock
# ---------------------------------------------------------------------------


class TestAcquireLock:
    """acquire_lock() 파일 잠금 테스트."""

    @patch("scripts.check_positions.fcntl")
    @patch("builtins.open")
    @patch("scripts.check_positions.LOCK_FILE")
    def test_acquire_lock_success(self, mock_lock_file, mock_open_fn, mock_fcntl):
        mock_fd = MagicMock()
        mock_open_fn.return_value = mock_fd
        mock_lock_file.parent.mkdir = MagicMock()

        result = acquire_lock()

        assert result is mock_fd
        mock_fd.write.assert_called_once()
        mock_fd.flush.assert_called_once()

    @patch("scripts.check_positions.fcntl")
    @patch("builtins.open")
    @patch("scripts.check_positions.LOCK_FILE")
    def test_acquire_lock_blocked(self, mock_lock_file, mock_open_fn, mock_fcntl):
        mock_fd = MagicMock()
        mock_open_fn.return_value = mock_fd
        mock_lock_file.parent.mkdir = MagicMock()
        mock_fcntl.flock.side_effect = IOError("locked")
        mock_fcntl.LOCK_EX = fcntl.LOCK_EX
        mock_fcntl.LOCK_NB = fcntl.LOCK_NB

        result = acquire_lock()

        assert result is None
        mock_fd.close.assert_called_once()

    @patch("scripts.check_positions.fcntl")
    @patch("builtins.open")
    @patch("scripts.check_positions.LOCK_FILE")
    def test_acquire_lock_creates_parent_dir(self, mock_lock_file, mock_open_fn, mock_fcntl):
        mock_fd = MagicMock()
        mock_open_fn.return_value = mock_fd
        mock_lock_file.parent.mkdir = MagicMock()

        acquire_lock()

        mock_lock_file.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)


class TestReleaseLock:
    """release_lock() 잠금 해제 테스트."""

    @patch("scripts.check_positions.fcntl")
    def test_release_lock_success(self, mock_fcntl):
        mock_fd = MagicMock()

        release_lock(mock_fd)

        mock_fcntl.flock.assert_called_once_with(mock_fd, mock_fcntl.LOCK_UN)
        mock_fd.close.assert_called_once()

    @patch("scripts.check_positions.fcntl")
    def test_release_lock_none(self, mock_fcntl):
        release_lock(None)  # Should not raise
        mock_fcntl.flock.assert_not_called()

    @patch("scripts.check_positions.fcntl")
    def test_release_lock_exception_swallowed(self, mock_fcntl):
        mock_fd = MagicMock()
        mock_fd.close.side_effect = OSError("close failed")

        release_lock(mock_fd)  # Should not raise
        mock_fcntl.flock.assert_called_once_with(mock_fd, mock_fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Integration tests: load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """load_config() 환경 변수 로드 테스트."""

    def test_load_config_with_env(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "cid"}):
            config = load_config()
        assert config["telegram_token"] == "tok"
        assert config["telegram_chat_id"] == "cid"

    def test_load_config_missing_env(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("dotenv.load_dotenv"):
                config = load_config()
        assert config["telegram_token"] is None
        assert config["telegram_chat_id"] is None


# ---------------------------------------------------------------------------
# Integration tests: setup_notifier
# ---------------------------------------------------------------------------


class TestSetupNotifier:
    """setup_notifier() 알림 채널 설정 테스트."""

    def test_with_telegram_credentials(self):
        config = {"telegram_token": "tok", "telegram_chat_id": "cid"}
        with patch("src.script_helpers.TelegramChannel") as MockTg:
            notifier = setup_notifier(config)
        MockTg.assert_called_once_with("tok", "cid")
        assert notifier is not None

    def test_without_credentials(self):
        config = {"telegram_token": None, "telegram_chat_id": None}
        with patch("src.script_helpers.TelegramChannel") as MockTg:
            notifier = setup_notifier(config)
        MockTg.assert_not_called()
        assert notifier is not None

    def test_partial_credentials_missing_token(self):
        config = {"telegram_token": None, "telegram_chat_id": "cid"}
        with patch("src.script_helpers.TelegramChannel") as MockTg:
            setup_notifier(config)
        MockTg.assert_not_called()

    def test_partial_credentials_missing_chat_id(self):
        config = {"telegram_token": "tok", "telegram_chat_id": None}
        with patch("src.script_helpers.TelegramChannel") as MockTg:
            setup_notifier(config)
        MockTg.assert_not_called()


# ---------------------------------------------------------------------------
# Integration tests: setup_risk_manager
# ---------------------------------------------------------------------------


class TestSetupRiskManager:
    """setup_risk_manager() 리스크 매니저 설정 테스트.

    에러 핸들링/엣지 케이스 테스트는 test_script_helpers.py::TestSetupRiskManager 참조.
    """

    def test_loads_real_config(self):
        """실제 config/correlation_groups.yaml 로 정상 로드."""
        rm = setup_risk_manager()
        assert rm is not None


# ---------------------------------------------------------------------------
# Integration tests: main()
# ---------------------------------------------------------------------------


class TestMain:
    """main() 비동기 엔트리포인트 테스트."""

    async def test_acquires_and_releases_lock(self):
        mock_fd = MagicMock()
        with (
            patch("scripts.check_positions.acquire_lock", return_value=mock_fd),
            patch("scripts.check_positions._run_checks", new_callable=AsyncMock) as mock_run,
            patch("scripts.check_positions.release_lock") as mock_release,
        ):
            await main()
        mock_run.assert_awaited_once()
        mock_release.assert_called_once_with(mock_fd)

    async def test_skips_when_already_locked(self):
        with (
            patch("scripts.check_positions.acquire_lock", return_value=None),
            patch("scripts.check_positions._run_checks", new_callable=AsyncMock) as mock_run,
        ):
            await main()
        mock_run.assert_not_awaited()

    async def test_releases_lock_on_exception(self):
        mock_fd = MagicMock()
        with (
            patch("scripts.check_positions.acquire_lock", return_value=mock_fd),
            patch("scripts.check_positions._run_checks", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("scripts.check_positions.release_lock") as mock_release,
        ):
            with pytest.raises(RuntimeError):
                await main()
        mock_release.assert_called_once_with(mock_fd)


# ---------------------------------------------------------------------------
# Integration tests: _run_checks()
# ---------------------------------------------------------------------------


class TestRunChecks:
    """_run_checks() 비동기 오케스트레이션 통합 테스트."""

    def _make_mock_df(self, high=101.0, low=97.0, close=100.0, n=2.0):
        """터틀 지표가 포함된 2행 DataFrame 생성.

        NOTE: conftest.py의 make_turtle_df fixture와 동일 로직.
        클래스 내부에서 self._make_mock_df 호출이 30+건이라 당장 마이그레이션하지 않음.
        신규 테스트 클래스에서는 make_turtle_df fixture 사용 권장.
        """
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2025-03-01"),
                    "high": 100,
                    "low": 98,
                    "close": 99,
                    "N": n,
                    "dc_high_20": 105,
                    "dc_low_20": 95,
                    "dc_high_55": 110,
                    "dc_low_55": 90,
                    "dc_high_10": 103,
                    "dc_low_10": 97,
                },
                {
                    "date": pd.Timestamp("2025-03-02"),
                    "high": high,
                    "low": low,
                    "close": close,
                    "N": n,
                    "dc_high_20": 105,
                    "dc_low_20": 95,
                    "dc_high_55": 110,
                    "dc_low_55": 90,
                    "dc_high_10": 103,
                    "dc_low_10": 97,
                },
            ]
        )

    def _build_patches(
        self,
        open_positions=None,
        symbols=None,
        fetch_df=None,
        should_check=True,
        can_add=(True, ""),
        should_pyramid=False,
    ):
        """_run_checks()의 모든 의존성을 패치하는 딕셔너리를 반환."""
        if open_positions is None:
            open_positions = []
        if symbols is None:
            symbols = ["SPY"]
        if fetch_df is None:
            fetch_df = self._make_mock_df()

        patches = {}

        # load_config
        patches["load_config"] = patch(
            "scripts.check_positions.load_config",
            return_value={"telegram_token": None, "telegram_chat_id": None},
        )

        # setup_notifier
        mock_notifier = MagicMock()
        mock_notifier.send_signal = AsyncMock()
        patches["setup_notifier"] = patch(
            "scripts.check_positions.setup_notifier",
            return_value=mock_notifier,
        )

        # DataFetcher
        mock_fetcher = MagicMock()
        mock_fetcher.fetch.return_value = fetch_df
        patches["DataFetcher"] = patch(
            "scripts.check_positions.DataFetcher",
            return_value=mock_fetcher,
        )

        # ParquetDataStore
        mock_data_store = MagicMock()
        patches["ParquetDataStore"] = patch(
            "scripts.check_positions.ParquetDataStore",
            return_value=mock_data_store,
        )

        # PositionTracker
        mock_tracker = MagicMock()
        mock_tracker.get_open_positions.side_effect = lambda sym=None: (
            [p for p in open_positions if p.symbol == sym] if sym else open_positions
        )
        mock_tracker.get_summary.return_value = {"open": len(open_positions)}
        mock_tracker.should_pyramid.return_value = should_pyramid
        mock_tracker.get_position_history.return_value = []
        mock_tracker.get_all_positions.return_value = []
        patches["PositionTracker"] = patch(
            "scripts.check_positions.PositionTracker",
            return_value=mock_tracker,
        )

        # TradingGuard / CostAnalyzer / KillSwitch
        mock_trading_guard = MagicMock()
        mock_trading_guard.record_trade_result = MagicMock()
        patches["TradingGuard"] = patch(
            "scripts.check_positions.TradingGuard",
            return_value=mock_trading_guard,
        )
        patches["TradingLimits"] = patch(
            "scripts.check_positions.TradingLimits",
        )
        mock_cost_analyzer = MagicMock()
        mock_cost_analyzer.check_budget_limit.return_value = (True, "")
        patches["CostAnalyzer"] = patch(
            "scripts.check_positions.CostAnalyzer",
            return_value=mock_cost_analyzer,
        )
        mock_ks = MagicMock()
        mock_ks.is_trading_enabled = True
        mock_ks.check_entry_allowed.return_value = (True, "")
        patches["KillSwitch"] = patch(
            "scripts.check_positions.KillSwitch",
            return_value=mock_ks,
        )

        # setup_risk_manager
        mock_rm = MagicMock()
        mock_rm.can_add_position.return_value = can_add
        mock_rm.get_risk_summary.return_value = {}
        patches["setup_risk_manager"] = patch(
            "scripts.check_positions.setup_risk_manager",
            return_value=mock_rm,
        )

        # UniverseManager
        mock_universe = MagicMock()
        mock_universe.get_enabled_symbols.return_value = symbols
        mock_universe.assets = {}
        patches["UniverseManager"] = patch(
            "scripts.check_positions.UniverseManager",
            return_value=mock_universe,
        )

        # InverseETFFilter
        mock_inverse = MagicMock()
        mock_inverse.is_inverse_etf.return_value = False
        patches["InverseETFFilter"] = patch(
            "scripts.check_positions.InverseETFFilter",
            return_value=mock_inverse,
        )

        # add_turtle_indicators (pass-through)
        patches["add_turtle_indicators"] = patch(
            "scripts.check_positions.add_turtle_indicators",
            side_effect=lambda df: df,
        )

        # get_market_status
        patches["get_market_status"] = patch(
            "scripts.check_positions.get_market_status",
            return_value="Market Open",
        )

        # should_check_signals
        patches["should_check_signals"] = patch(
            "scripts.check_positions.should_check_signals",
            return_value=should_check,
        )

        # infer_market (used in logging)
        patches["infer_market"] = patch(
            "scripts.check_positions.infer_market",
            return_value="US",
        )

        # Path for universe.yaml — need to keep real Path for other uses
        # We mock only the specific call site in _run_checks
        mock_yaml_path = MagicMock()
        mock_yaml_path.exists.return_value = False  # Use default universe
        patches["universe_yaml_path"] = patch(
            "scripts.check_positions.Path",
            side_effect=lambda p: mock_yaml_path if "universe" in str(p) else Path(p),
        )

        return patches, mock_notifier, mock_tracker, mock_rm, mock_fetcher, mock_data_store, mock_trading_guard

    def _start_patches(self, patches):
        """패치를 모두 시작하고 반환."""
        return PatchManager.start_all(patches)

    def _stop_patches(self, patches):
        """패치를 모두 중지."""
        PatchManager.stop_all(patches)

    async def test_run_checks_no_positions_no_signals(self):
        """오픈 포지션 없음, 돌파 없음 -> 깨끗한 실행."""
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=["SPY"],
            fetch_df=self._make_mock_df(high=101, low=97),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        # No breakout (high=101 < dc_high_20=105), so no signal notification
        notifier.send_signal.assert_not_awaited()

    async def test_run_checks_stop_loss_triggered(self):
        """오픈 포지션 스톱로스 발동 -> close + notify + record_trade_result."""
        pos = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=98.0)
        patches, notifier, tracker, rm, fetcher, ds, tg = self._build_patches(
            open_positions=[pos],
            fetch_df=self._make_mock_df(high=100, low=95, close=96),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        tracker.close_position.assert_called_once()
        notifier.send_signal.assert_awaited()
        # circuit breaker: 포지션 종료 시 record_trade_result 호출 보장
        tg.record_trade_result.assert_called_once_with(tracker.close_position.return_value.pnl)

    async def test_run_checks_exit_signal(self):
        """오픈 포지션 청산 시그널 -> close + save + notify + record_trade_result."""
        pos = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=80.0)
        # low=96 < dc_low_10=97 -> exit signal, but stop_loss=80 not hit
        patches, notifier, tracker, rm, fetcher, ds, tg = self._build_patches(
            open_positions=[pos],
            fetch_df=self._make_mock_df(high=100, low=96, close=97),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        tracker.close_position.assert_called_once()
        notifier.send_signal.assert_awaited()
        # circuit breaker: 포지션 종료 시 record_trade_result 호출 보장
        tg.record_trade_result.assert_called_once_with(tracker.close_position.return_value.pnl)

    async def test_run_checks_pyramid_opportunity(self):
        """피라미딩 기회 -> notify."""
        pos = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=80.0)
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos],
            fetch_df=self._make_mock_df(high=100, low=99, close=100),
            should_pyramid=True,
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        # Pyramid notification should have been sent
        assert notifier.send_signal.await_count >= 1
        call_args_list = notifier.send_signal.call_args_list
        assert any("PYRAMID" in str(call) for call in call_args_list)

    async def test_run_checks_entry_signal_generated(self):
        """새 진입 시그널 생성 + 리스크 통과 -> save + notify."""
        # high=106 > dc_high_20=105 -> long entry signal
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=["SPY"],
            fetch_df=self._make_mock_df(high=106, low=99, close=105),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        notifier.send_signal.assert_awaited()

    async def test_run_checks_signal_blocked_by_risk(self):
        """진입 시그널 리스크 차단 -> 알림 없음."""
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=["SPY"],
            fetch_df=self._make_mock_df(high=106, low=99, close=105),
            can_add=(False, "Direction limit exceeded"),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        notifier.send_signal.assert_not_awaited()

    async def test_run_checks_empty_fetch_skipped(self):
        """빈 DataFrame -> 에러 없이 스킵."""
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=["SPY"],
            fetch_df=pd.DataFrame(),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        notifier.send_signal.assert_not_awaited()

    async def test_run_checks_market_inactive_skipped(self):
        """마켓 비활동 -> 시그널 체크 스킵."""
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=["SPY"],
            fetch_df=self._make_mock_df(high=106, low=99, close=105),
            should_check=False,
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        notifier.send_signal.assert_not_awaited()

    async def test_run_checks_position_error_handled(self):
        """포지션 처리 중 예외 -> 로깅 후 계속."""
        pos = _make_open_position(symbol="SPY", direction="LONG", system=1)
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos],
        )
        # Make fetcher raise for position data (use instance mock, not class mock)
        fetcher.fetch.side_effect = RuntimeError("API error")
        self._start_patches(patches)
        try:
            await _run_checks()  # Should not raise
        finally:
            self._stop_patches(patches)
        # Verify error was handled gracefully: no signal sent, no crash
        notifier.send_signal.assert_not_awaited()

    async def test_run_checks_signal_error_handled(self):
        """시그널 처리 중 예외 -> 로깅 후 계속."""
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=["SPY", "QQQ"],
        )
        # Make fetcher raise for everything (use instance mock, not class mock)
        fetcher.fetch.side_effect = RuntimeError("API error")
        self._start_patches(patches)
        try:
            await _run_checks()  # Should not raise
        finally:
            self._stop_patches(patches)
        # Verify error was handled gracefully: no signal sent despite 2 symbols
        notifier.send_signal.assert_not_awaited()

    async def test_run_checks_symbol_tuple_handling(self):
        """(symbol, name) 튜플 심볼 처리."""
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=["SPY"],
            fetch_df=self._make_mock_df(high=106, low=99, close=105),
        )
        # Override UniverseManager to provide asset with name
        patches["UniverseManager"].stop()
        universe_mock = MagicMock()
        universe_mock.get_enabled_symbols.return_value = ["SPY"]
        asset_mock = MagicMock()
        asset_mock.name = "S&P 500 ETF"
        universe_mock.assets = {"SPY": asset_mock}
        patches["UniverseManager"] = patch(
            "scripts.check_positions.UniverseManager",
            return_value=universe_mock,
        )
        patches["UniverseManager"].start()
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)

    async def test_run_checks_existing_system_position_skipped(self):
        """기존 시스템 포지션 보유 중 -> 해당 시스템 시그널 스킵."""
        pos = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=80.0)
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos],
            symbols=["SPY"],
            fetch_df=self._make_mock_df(high=106, low=99, close=105),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)

    async def test_run_checks_save_signal_called(self):
        """시그널 저장이 data_store.save_signal()로 호출되는지 검증."""
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=["SPY"],
            fetch_df=self._make_mock_df(high=106, low=99, close=105),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        ds.save_signal.assert_called()

    async def test_run_checks_risk_summary_logged(self):
        """리스크 요약이 호출되는지 검증."""
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[],
            symbols=[],
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        rm.get_risk_summary.assert_called_once()

    async def test_run_checks_position_loaded_to_risk_manager(self):
        """오픈 포지션이 리스크 매니저에 로드되는지 검증."""
        pos = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=80.0)
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos],
            fetch_df=self._make_mock_df(high=100, low=99, close=100),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)
        rm.add_position.assert_any_call("SPY", 1, 2.0, Direction.LONG)

    async def test_run_checks_multiple_positions(self):
        """여러 포지션 동시 처리."""
        pos1 = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=80.0)
        pos2 = _make_open_position(symbol="QQQ", direction="SHORT", system=2, stop_loss=120.0)
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos1, pos2],
            symbols=["SPY", "QQQ"],
            fetch_df=self._make_mock_df(high=100, low=99, close=100),
        )
        self._start_patches(patches)
        try:
            await _run_checks()
        finally:
            self._stop_patches(patches)


# ---------------------------------------------------------------------------
# Integration tests: _run_checks() — Inverse ETF branch
# ---------------------------------------------------------------------------


class TestRunChecksInverseETF:
    """_run_checks() Inverse ETF 처리 분기 테스트."""

    def _make_mock_df(self, high=101.0, low=97.0, close=100.0, n=2.0):
        """터틀 지표가 포함된 2행 DataFrame 생성.

        NOTE: conftest.py의 make_turtle_df fixture와 동일 로직.
        클래스 내부에서 self._make_mock_df 호출이 30+건이라 당장 마이그레이션하지 않음.
        신규 테스트 클래스에서는 make_turtle_df fixture 사용 권장.
        """
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2025-03-01"),
                    "high": 100,
                    "low": 98,
                    "close": 99,
                    "N": n,
                    "dc_high_20": 105,
                    "dc_low_20": 95,
                    "dc_high_55": 110,
                    "dc_low_55": 90,
                    "dc_high_10": 103,
                    "dc_low_10": 97,
                },
                {
                    "date": pd.Timestamp("2025-03-02"),
                    "high": high,
                    "low": low,
                    "close": close,
                    "N": n,
                    "dc_high_20": 105,
                    "dc_low_20": 95,
                    "dc_high_55": 110,
                    "dc_low_55": 90,
                    "dc_high_10": 103,
                    "dc_low_10": 97,
                },
            ]
        )

    async def test_inverse_etf_force_exit(self):
        """Inverse ETF 괴리/보유일 초과 -> 강제 청산."""
        pos = _make_open_position(symbol="SH", direction="LONG", system=1, stop_loss=50.0)

        mock_notifier = MagicMock()
        mock_notifier.send_signal = AsyncMock()

        mock_fetcher = MagicMock()
        mock_fetcher.fetch.return_value = self._make_mock_df(high=100, low=99, close=100)

        mock_tracker = MagicMock()
        mock_tracker.get_open_positions.side_effect = lambda sym=None: [pos] if sym is None or sym == "SH" else []
        mock_tracker.get_summary.return_value = {"open": 1}
        mock_tracker.should_pyramid.return_value = False
        mock_tracker.get_position_history.return_value = []

        mock_rm = MagicMock()
        mock_rm.can_add_position.return_value = (True, "")
        mock_rm.get_risk_summary.return_value = {}

        mock_universe = MagicMock()
        mock_universe.get_enabled_symbols.return_value = []
        mock_universe.assets = {}

        # Inverse ETF filter: is_inverse=True, should_force_exit=True
        mock_inverse = MagicMock()
        mock_inverse.is_inverse_etf.return_value = True
        mock_inverse.get_config.return_value = MagicMock(underlying="SPY")
        mock_inverse.should_force_exit.return_value = (True, "DECAY_THRESHOLD", "Decay > 5%")

        mock_yaml_path = MagicMock()
        mock_yaml_path.exists.return_value = False

        mock_tg = MagicMock()
        mock_tg.record_trade_result = MagicMock()
        mock_ca = MagicMock()
        mock_ca.check_budget_limit.return_value = (True, "")
        mock_ks = MagicMock()
        mock_ks.is_trading_enabled = True
        mock_ks.check_entry_allowed.return_value = (True, "")

        with (
            patch(
                "scripts.check_positions.load_config", return_value={"telegram_token": None, "telegram_chat_id": None}
            ),
            patch("scripts.check_positions.setup_notifier", return_value=mock_notifier),
            patch("scripts.check_positions.DataFetcher", return_value=mock_fetcher),
            patch("scripts.check_positions.ParquetDataStore", return_value=MagicMock()),
            patch("scripts.check_positions.PositionTracker", return_value=mock_tracker),
            patch("scripts.check_positions.setup_risk_manager", return_value=mock_rm),
            patch("scripts.check_positions.UniverseManager", return_value=mock_universe),
            patch("scripts.check_positions.InverseETFFilter", return_value=mock_inverse),
            patch("scripts.check_positions.add_turtle_indicators", side_effect=lambda df: df),
            patch("scripts.check_positions.get_market_status", return_value="Open"),
            patch("scripts.check_positions.should_check_signals", return_value=True),
            patch("scripts.check_positions.infer_market", return_value="US"),
            patch(
                "scripts.check_positions.Path",
                side_effect=lambda p: mock_yaml_path if "universe" in str(p) else Path(p),
            ),
            patch("scripts.check_positions.TradingGuard", return_value=mock_tg),
            patch("scripts.check_positions.TradingLimits"),
            patch("scripts.check_positions.CostAnalyzer", return_value=mock_ca),
            patch("scripts.check_positions.KillSwitch", return_value=mock_ks),
        ):
            await _run_checks()

        mock_tracker.close_position.assert_called_once()
        notifier_calls = mock_notifier.send_signal.call_args_list
        assert any("INVERSE" in str(call) for call in notifier_calls)
        # record_trade_result가 포지션 종료 시 호출되어야 함 (circuit breaker 작동 보장)
        mock_tg.record_trade_result.assert_called_once_with(mock_tracker.close_position.return_value.pnl)

    async def test_inverse_etf_no_force_exit(self):
        """Inverse ETF 정상 범위 내 -> 강제 청산 안 함."""
        pos = _make_open_position(symbol="SH", direction="LONG", system=1, stop_loss=50.0)

        mock_notifier = MagicMock()
        mock_notifier.send_signal = AsyncMock()

        mock_fetcher = MagicMock()
        mock_fetcher.fetch.return_value = self._make_mock_df(high=100, low=99, close=100)

        mock_tracker = MagicMock()
        mock_tracker.get_open_positions.side_effect = lambda sym=None: [pos] if sym is None or sym == "SH" else []
        mock_tracker.get_summary.return_value = {"open": 1}
        mock_tracker.should_pyramid.return_value = False
        mock_tracker.get_position_history.return_value = []

        mock_rm = MagicMock()
        mock_rm.can_add_position.return_value = (True, "")
        mock_rm.get_risk_summary.return_value = {}

        mock_universe = MagicMock()
        mock_universe.get_enabled_symbols.return_value = []
        mock_universe.assets = {}

        mock_inverse = MagicMock()
        mock_inverse.is_inverse_etf.return_value = True
        mock_inverse.get_config.return_value = MagicMock(underlying="SPY")
        mock_inverse.should_force_exit.return_value = (False, None, "")

        mock_yaml_path = MagicMock()
        mock_yaml_path.exists.return_value = False

        with (
            patch(
                "scripts.check_positions.load_config", return_value={"telegram_token": None, "telegram_chat_id": None}
            ),
            patch("scripts.check_positions.setup_notifier", return_value=mock_notifier),
            patch("scripts.check_positions.DataFetcher", return_value=mock_fetcher),
            patch("scripts.check_positions.ParquetDataStore", return_value=MagicMock()),
            patch("scripts.check_positions.PositionTracker", return_value=mock_tracker),
            patch("scripts.check_positions.setup_risk_manager", return_value=mock_rm),
            patch("scripts.check_positions.UniverseManager", return_value=mock_universe),
            patch("scripts.check_positions.InverseETFFilter", return_value=mock_inverse),
            patch("scripts.check_positions.add_turtle_indicators", side_effect=lambda df: df),
            patch("scripts.check_positions.get_market_status", return_value="Open"),
            patch("scripts.check_positions.should_check_signals", return_value=True),
            patch("scripts.check_positions.infer_market", return_value="US"),
            patch(
                "scripts.check_positions.Path",
                side_effect=lambda p: mock_yaml_path if "universe" in str(p) else Path(p),
            ),
            patch("scripts.check_positions.TradingGuard", return_value=MagicMock()),
            patch("scripts.check_positions.TradingLimits"),
            patch(
                "scripts.check_positions.CostAnalyzer",
                return_value=MagicMock(check_budget_limit=MagicMock(return_value=(True, ""))),
            ),
            patch(
                "scripts.check_positions.KillSwitch",
                return_value=MagicMock(
                    is_trading_enabled=True,
                    check_entry_allowed=MagicMock(return_value=(True, "")),
                ),
            ),
        ):
            await _run_checks()

        # No force exit, so check_exit_signals should run next (no exit signal either, no pyramid)
        mock_tracker.close_position.assert_not_called()

    async def test_inverse_etf_underlying_empty_df(self):
        """Inverse ETF 기초자산 데이터 없음 -> 강제 청산 체크 스킵."""
        pos = _make_open_position(symbol="SH", direction="LONG", system=1, stop_loss=50.0)

        mock_notifier = MagicMock()
        mock_notifier.send_signal = AsyncMock()

        main_df = self._make_mock_df(high=100, low=99, close=100)
        mock_fetcher = MagicMock()

        # Return main_df for SH, empty for SPY (underlying)
        def fetch_side_effect(symbol, **kwargs):
            if symbol == "SH":
                return main_df
            return pd.DataFrame()

        mock_fetcher.fetch.side_effect = fetch_side_effect

        mock_tracker = MagicMock()
        mock_tracker.get_open_positions.side_effect = lambda sym=None: [pos] if sym is None or sym == "SH" else []
        mock_tracker.get_summary.return_value = {"open": 1}
        mock_tracker.should_pyramid.return_value = False
        mock_tracker.get_position_history.return_value = []

        mock_rm = MagicMock()
        mock_rm.can_add_position.return_value = (True, "")
        mock_rm.get_risk_summary.return_value = {}

        mock_universe = MagicMock()
        mock_universe.get_enabled_symbols.return_value = []
        mock_universe.assets = {}

        mock_inverse = MagicMock()
        mock_inverse.is_inverse_etf.return_value = True
        mock_inverse.get_config.return_value = MagicMock(underlying="SPY")

        mock_yaml_path = MagicMock()
        mock_yaml_path.exists.return_value = False

        with (
            patch(
                "scripts.check_positions.load_config", return_value={"telegram_token": None, "telegram_chat_id": None}
            ),
            patch("scripts.check_positions.setup_notifier", return_value=mock_notifier),
            patch("scripts.check_positions.DataFetcher", return_value=mock_fetcher),
            patch("scripts.check_positions.ParquetDataStore", return_value=MagicMock()),
            patch("scripts.check_positions.PositionTracker", return_value=mock_tracker),
            patch("scripts.check_positions.setup_risk_manager", return_value=mock_rm),
            patch("scripts.check_positions.UniverseManager", return_value=mock_universe),
            patch("scripts.check_positions.InverseETFFilter", return_value=mock_inverse),
            patch("scripts.check_positions.add_turtle_indicators", side_effect=lambda df: df),
            patch("scripts.check_positions.get_market_status", return_value="Open"),
            patch("scripts.check_positions.should_check_signals", return_value=True),
            patch("scripts.check_positions.infer_market", return_value="US"),
            patch(
                "scripts.check_positions.Path",
                side_effect=lambda p: mock_yaml_path if "universe" in str(p) else Path(p),
            ),
            patch("scripts.check_positions.TradingGuard", return_value=MagicMock()),
            patch("scripts.check_positions.TradingLimits"),
            patch(
                "scripts.check_positions.CostAnalyzer",
                return_value=MagicMock(check_budget_limit=MagicMock(return_value=(True, ""))),
            ),
            patch(
                "scripts.check_positions.KillSwitch",
                return_value=MagicMock(
                    is_trading_enabled=True,
                    check_entry_allowed=MagicMock(return_value=(True, "")),
                ),
            ),
        ):
            await _run_checks()

        # should_force_exit should NOT have been called (underlying df is empty)
        mock_inverse.should_force_exit.assert_not_called()


# ---------------------------------------------------------------------------
# save_trade() 파이프라인 통합 테스트
# ---------------------------------------------------------------------------


class TestSaveTradeIntegration:
    """_build_trade_record() 헬퍼 + 3개 청산 경로 save_trade() 호출 검증."""

    # -- _build_trade_record() 단위 테스트 --

    def test_build_trade_record_long_position(self):
        """LONG 포지션 청산 후 거래 기록 dict 검증."""
        pos = Position(
            position_id="SPY_1_LONG_20250301_120000",
            symbol="SPY",
            system=1,
            direction="LONG",
            entry_date="2025-03-01",
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
            last_update="2025-03-10T12:00:00",
            exit_date="2025-03-10",
            exit_price=110.0,
            exit_reason="Exit Signal",
            pnl=400.0,
            pnl_pct=10.0,
            r_multiple=2.5,
        )

        record = _build_trade_record(pos)

        assert record["position_id"] == "SPY_1_LONG_20250301_120000"
        assert record["symbol"] == "SPY"
        assert record["system"] == 1
        assert record["direction"] == "LONG"
        assert record["entry_date"] == "2025-03-01"
        assert record["entry_price"] == 100.0
        assert record["exit_date"] == "2025-03-10"
        assert record["exit_price"] == 110.0
        assert record["exit_reason"] == "Exit Signal"
        assert record["units"] == 1
        assert record["total_shares"] == 40
        assert record["pnl"] == 400.0
        assert record["pnl_pct"] == 10.0
        assert record["r_multiple"] == 2.5
        assert record["entry_n"] == 2.0

    def test_build_trade_record_short_position(self):
        """SHORT 포지션 청산 후 거래 기록 dict 검증."""
        pos = Position(
            position_id="AAPL_2_SHORT_20250301_120000",
            symbol="AAPL",
            system=2,
            direction="SHORT",
            entry_date="2025-03-01",
            entry_price=150.0,
            entry_n=3.0,
            units=2,
            max_units=4,
            shares_per_unit=20,
            total_shares=40,
            stop_loss=156.0,
            pyramid_level=1,
            exit_period=20,
            status="closed",
            last_update="2025-03-15T12:00:00",
            exit_date="2025-03-15",
            exit_price=140.0,
            exit_reason="Stop Loss",
            pnl=400.0,
            pnl_pct=6.67,
            r_multiple=1.67,
        )

        record = _build_trade_record(pos)

        assert record["direction"] == "SHORT"
        assert record["symbol"] == "AAPL"
        assert record["system"] == 2
        assert record["exit_price"] == 140.0
        assert record["units"] == 2
        assert record["total_shares"] == 40

    def test_build_trade_record_includes_position_id_and_recorded_at(self):
        """position_id와 recorded_at 필드 존재 검증."""
        pos = Position(
            position_id="QQQ_1_LONG_20250301_120000",
            symbol="QQQ",
            system=1,
            direction="LONG",
            entry_date="2025-03-01",
            entry_price=400.0,
            entry_n=5.0,
            units=1,
            max_units=4,
            shares_per_unit=10,
            total_shares=10,
            stop_loss=390.0,
            pyramid_level=0,
            exit_period=10,
            status="closed",
            last_update="2025-03-10T12:00:00",
            exit_date="2025-03-10",
            exit_price=420.0,
            exit_reason="Exit Signal",
            pnl=200.0,
            pnl_pct=5.0,
            r_multiple=2.0,
        )

        record = _build_trade_record(pos)

        assert "position_id" in record
        assert record["position_id"] == "QQQ_1_LONG_20250301_120000"
        assert "recorded_at" in record
        # recorded_at은 ISO format이어야 함
        datetime.fromisoformat(record["recorded_at"])  # 파싱 실패 시 예외

    # -- 통합 테스트: 3개 청산 경로에서 save_trade() 호출 검증 --

    def _make_mock_df(self, high=101.0, low=97.0, close=100.0, n=2.0):
        """터틀 지표가 포함된 2행 DataFrame 생성."""
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2025-03-01"),
                    "high": 100,
                    "low": 98,
                    "close": 99,
                    "N": n,
                    "dc_high_20": 105,
                    "dc_low_20": 95,
                    "dc_high_55": 110,
                    "dc_low_55": 90,
                    "dc_high_10": 103,
                    "dc_low_10": 97,
                },
                {
                    "date": pd.Timestamp("2025-03-02"),
                    "high": high,
                    "low": low,
                    "close": close,
                    "N": n,
                    "dc_high_20": 105,
                    "dc_low_20": 95,
                    "dc_high_55": 110,
                    "dc_low_55": 90,
                    "dc_high_10": 103,
                    "dc_low_10": 97,
                },
            ]
        )

    def _build_patches(
        self,
        open_positions=None,
        symbols=None,
        fetch_df=None,
        should_check=True,
        can_add=(True, ""),
        should_pyramid=False,
    ):
        """_run_checks()의 모든 의존성을 패치하는 딕셔너리를 반환."""
        if open_positions is None:
            open_positions = []
        if symbols is None:
            symbols = ["SPY"]
        if fetch_df is None:
            fetch_df = self._make_mock_df()

        patches = {}

        patches["load_config"] = patch(
            "scripts.check_positions.load_config",
            return_value={"telegram_token": None, "telegram_chat_id": None},
        )

        mock_notifier = MagicMock()
        mock_notifier.send_signal = AsyncMock()
        patches["setup_notifier"] = patch(
            "scripts.check_positions.setup_notifier",
            return_value=mock_notifier,
        )

        mock_fetcher = MagicMock()
        mock_fetcher.fetch.return_value = fetch_df
        patches["DataFetcher"] = patch(
            "scripts.check_positions.DataFetcher",
            return_value=mock_fetcher,
        )

        mock_data_store = MagicMock()
        patches["ParquetDataStore"] = patch(
            "scripts.check_positions.ParquetDataStore",
            return_value=mock_data_store,
        )

        mock_tracker = MagicMock()
        mock_tracker.get_open_positions.side_effect = lambda sym=None: (
            [p for p in open_positions if p.symbol == sym] if sym else open_positions
        )
        mock_tracker.get_summary.return_value = {"open": len(open_positions)}
        mock_tracker.should_pyramid.return_value = should_pyramid
        mock_tracker.get_position_history.return_value = []
        mock_tracker.get_all_positions.return_value = []
        # close_position 기본 반환: 청산된 Position mock
        mock_closed = MagicMock()
        mock_closed.position_id = "test_pos_id"
        mock_closed.symbol = "SPY"
        mock_closed.system = 1
        mock_closed.direction = Direction.LONG
        mock_closed.entry_date = "2025-03-01"
        mock_closed.entry_price = 100.0
        mock_closed.exit_date = "2025-03-10"
        mock_closed.exit_price = 96.0
        mock_closed.exit_reason = "Stop Loss"
        mock_closed.units = 1
        mock_closed.total_shares = 40
        mock_closed.pnl = -160.0
        mock_closed.pnl_pct = -4.0
        mock_closed.r_multiple = -1.0
        mock_closed.entry_n = 2.0
        mock_tracker.close_position.return_value = mock_closed
        patches["PositionTracker"] = patch(
            "scripts.check_positions.PositionTracker",
            return_value=mock_tracker,
        )

        # TradingGuard / CostAnalyzer / KillSwitch
        mock_trading_guard = MagicMock()
        mock_trading_guard.record_trade_result = MagicMock()
        patches["TradingGuard"] = patch(
            "scripts.check_positions.TradingGuard",
            return_value=mock_trading_guard,
        )
        patches["TradingLimits"] = patch(
            "scripts.check_positions.TradingLimits",
        )
        mock_cost_analyzer = MagicMock()
        mock_cost_analyzer.check_budget_limit.return_value = (True, "")
        patches["CostAnalyzer"] = patch(
            "scripts.check_positions.CostAnalyzer",
            return_value=mock_cost_analyzer,
        )
        mock_ks = MagicMock()
        mock_ks.is_trading_enabled = True
        mock_ks.check_entry_allowed.return_value = (True, "")
        patches["KillSwitch"] = patch(
            "scripts.check_positions.KillSwitch",
            return_value=mock_ks,
        )

        mock_rm = MagicMock()
        mock_rm.can_add_position.return_value = can_add
        mock_rm.get_risk_summary.return_value = {}
        patches["setup_risk_manager"] = patch(
            "scripts.check_positions.setup_risk_manager",
            return_value=mock_rm,
        )

        mock_universe = MagicMock()
        mock_universe.get_enabled_symbols.return_value = symbols
        mock_universe.assets = {}
        patches["UniverseManager"] = patch(
            "scripts.check_positions.UniverseManager",
            return_value=mock_universe,
        )

        mock_inverse = MagicMock()
        mock_inverse.is_inverse_etf.return_value = False
        patches["InverseETFFilter"] = patch(
            "scripts.check_positions.InverseETFFilter",
            return_value=mock_inverse,
        )

        patches["add_turtle_indicators"] = patch(
            "scripts.check_positions.add_turtle_indicators",
            side_effect=lambda df: df,
        )

        patches["get_market_status"] = patch(
            "scripts.check_positions.get_market_status",
            return_value="Market Open",
        )

        patches["should_check_signals"] = patch(
            "scripts.check_positions.should_check_signals",
            return_value=should_check,
        )

        patches["infer_market"] = patch(
            "scripts.check_positions.infer_market",
            return_value="US",
        )

        mock_yaml_path = MagicMock()
        mock_yaml_path.exists.return_value = False
        patches["universe_yaml_path"] = patch(
            "scripts.check_positions.Path",
            side_effect=lambda p: mock_yaml_path if "universe" in str(p) else Path(p),
        )

        return patches, mock_notifier, mock_tracker, mock_rm, mock_fetcher, mock_data_store, mock_trading_guard

    async def test_stop_loss_saves_trade_record(self):
        """스톱로스 청산 시 save_trade() 호출 검증."""
        pos = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=98.0)
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos],
            fetch_df=self._make_mock_df(high=100, low=95, close=96),
        )
        PatchManager.start_all(patches)
        try:
            await _run_checks()
        finally:
            PatchManager.stop_all(patches)

        tracker.close_position.assert_called_once()
        ds.save_trade.assert_called_once()
        trade_record = ds.save_trade.call_args[0][0]
        assert trade_record["position_id"] == "test_pos_id"
        assert "recorded_at" in trade_record

    async def test_exit_signal_saves_trade_record(self):
        """청산 시그널 경로에서 save_trade() 호출 검증."""
        pos = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=80.0)
        # low=96 < dc_low_10=97 -> exit signal, stop_loss=80 not hit
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos],
            fetch_df=self._make_mock_df(high=100, low=96, close=97),
        )
        PatchManager.start_all(patches)
        try:
            await _run_checks()
        finally:
            PatchManager.stop_all(patches)

        tracker.close_position.assert_called_once()
        ds.save_trade.assert_called_once()
        trade_record = ds.save_trade.call_args[0][0]
        assert trade_record["position_id"] == "test_pos_id"

    async def test_inverse_exit_saves_trade_record(self):
        """Inverse ETF 강제 청산 시 save_trade() 호출 검증."""
        pos = _make_open_position(symbol="SH", direction="LONG", system=1, stop_loss=50.0)

        mock_notifier = MagicMock()
        mock_notifier.send_signal = AsyncMock()

        mock_fetcher = MagicMock()
        mock_fetcher.fetch.return_value = self._make_mock_df(high=100, low=99, close=100)

        mock_tracker = MagicMock()
        mock_tracker.get_open_positions.side_effect = lambda sym=None: [pos] if sym is None or sym == "SH" else []
        mock_tracker.get_summary.return_value = {"open": 1}
        mock_tracker.should_pyramid.return_value = False
        mock_tracker.get_position_history.return_value = []
        # close_position 반환값 설정
        mock_closed = MagicMock()
        mock_closed.position_id = "SH_1_LONG_test"
        mock_closed.symbol = "SH"
        mock_closed.system = 1
        mock_closed.direction = Direction.LONG
        mock_closed.entry_date = "2025-03-01"
        mock_closed.entry_price = 100.0
        mock_closed.exit_date = "2025-03-10"
        mock_closed.exit_price = 100.0
        mock_closed.exit_reason = "Inverse Filter: Decay > 5%"
        mock_closed.units = 1
        mock_closed.total_shares = 40
        mock_closed.pnl = 0.0
        mock_closed.pnl_pct = 0.0
        mock_closed.r_multiple = 0.0
        mock_closed.entry_n = 2.0
        mock_tracker.close_position.return_value = mock_closed

        mock_rm = MagicMock()
        mock_rm.can_add_position.return_value = (True, "")
        mock_rm.get_risk_summary.return_value = {}

        mock_universe = MagicMock()
        mock_universe.get_enabled_symbols.return_value = []
        mock_universe.assets = {}

        mock_inverse = MagicMock()
        mock_inverse.is_inverse_etf.return_value = True
        mock_inverse.get_config.return_value = MagicMock(underlying="SPY")
        mock_inverse.should_force_exit.return_value = (True, "DECAY_THRESHOLD", "Decay > 5%")

        mock_data_store = MagicMock()

        mock_yaml_path = MagicMock()
        mock_yaml_path.exists.return_value = False

        with (
            patch(
                "scripts.check_positions.load_config",
                return_value={"telegram_token": None, "telegram_chat_id": None},
            ),
            patch("scripts.check_positions.setup_notifier", return_value=mock_notifier),
            patch("scripts.check_positions.DataFetcher", return_value=mock_fetcher),
            patch("scripts.check_positions.ParquetDataStore", return_value=mock_data_store),
            patch("scripts.check_positions.PositionTracker", return_value=mock_tracker),
            patch("scripts.check_positions.setup_risk_manager", return_value=mock_rm),
            patch("scripts.check_positions.UniverseManager", return_value=mock_universe),
            patch("scripts.check_positions.InverseETFFilter", return_value=mock_inverse),
            patch("scripts.check_positions.add_turtle_indicators", side_effect=lambda df: df),
            patch("scripts.check_positions.get_market_status", return_value="Open"),
            patch("scripts.check_positions.should_check_signals", return_value=True),
            patch("scripts.check_positions.infer_market", return_value="US"),
            patch(
                "scripts.check_positions.Path",
                side_effect=lambda p: mock_yaml_path if "universe" in str(p) else Path(p),
            ),
        ):
            await _run_checks()

        mock_tracker.close_position.assert_called_once()
        mock_data_store.save_trade.assert_called_once()
        trade_record = mock_data_store.save_trade.call_args[0][0]
        assert trade_record["position_id"] == "SH_1_LONG_test"
        assert trade_record["exit_reason"] == "Inverse Filter: Decay > 5%"

    async def test_save_trade_failure_does_not_halt_processing(self):
        """save_trade() 실패 시 루프가 중단되지 않고 계속 진행되는지 검증."""
        pos1 = _make_open_position(symbol="SPY", direction="LONG", system=1, stop_loss=98.0)
        pos2 = _make_open_position(symbol="QQQ", direction="LONG", system=1, stop_loss=98.0)
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos1, pos2],
            fetch_df=self._make_mock_df(high=100, low=95, close=96),
        )
        # save_trade가 항상 예외를 발생시키도록 설정
        ds.save_trade.side_effect = RuntimeError("Disk full")
        PatchManager.start_all(patches)
        try:
            await _run_checks()  # 예외로 중단되지 않아야 함
        finally:
            PatchManager.stop_all(patches)

        # 두 포지션 모두 close_position이 호출되어야 함 (루프가 중단되지 않음)
        assert tracker.close_position.call_count == 2
        # save_trade도 두 번 시도되어야 함
        assert ds.save_trade.call_count == 2

    async def test_close_position_none_skips_save_trade(self):
        """close_position()이 None 반환 시 save_trade 호출 안 됨."""
        pos = _make_open_position(symbol="SPY", stop_loss=98.0)
        patches, notifier, tracker, rm, fetcher, ds, _tg = self._build_patches(
            open_positions=[pos],
            fetch_df=self._make_mock_df(high=100, low=95, close=96),
        )
        tracker.close_position.return_value = None
        PatchManager.start_all(patches)
        try:
            await _run_checks()
        finally:
            PatchManager.stop_all(patches)
        ds.save_trade.assert_not_called()


# ---------------------------------------------------------------------------
# Short restriction filter tests (Issue #132)
# ---------------------------------------------------------------------------


def _make_asset(symbol: str, short_restricted: bool) -> Asset:
    """테스트용 Asset 생성 헬퍼."""
    group = AssetGroup.KR_EQUITY if symbol.endswith((".KS", ".KQ")) else AssetGroup.US_EQUITY
    country = "KR" if symbol.endswith((".KS", ".KQ")) else "US"
    return Asset(
        symbol=symbol,
        name=symbol,
        country=country,
        asset_type="equity",
        group=group,
        short_restricted=short_restricted,
    )


class TestShortRestrictionFilter:
    """asset.short_restricted 기반 숏 시그널 필터 테스트"""

    def test_short_signal_blocked_when_restricted(self):
        """short_restricted=True 이면 이탈이 있어도 숏 시그널 미생성"""
        df = _make_df(
            today_high=99.0,
            today_low=BELOW_20_ONLY,
            today_close=BELOW_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        asset = _make_asset("005930.KS", short_restricted=True)
        signals = check_entry_signals(df, "005930.KS", system=1, tracker=None, asset=asset)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 0, "short_restricted=True 이면 숏 시그널이 생성되지 않아야 한다"

    def test_short_signal_allowed_when_not_restricted(self):
        """short_restricted=False 이면 이탈 시 숏 시그널 생성"""
        df = _make_df(
            today_high=99.0,
            today_low=BELOW_20_ONLY,
            today_close=BELOW_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        asset = _make_asset("SPY", short_restricted=False)
        signals = check_entry_signals(df, "SPY", system=1, tracker=None, asset=asset)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 1, "short_restricted=False 이면 숏 시그널이 생성되어야 한다"
        assert short_signals[0]["type"] == SignalType.ENTRY_SHORT.value

    def test_long_signal_not_affected_by_short_restriction(self):
        """short_restricted=True 이어도 롱 시그널은 정상 생성"""
        df = _make_df(
            today_high=ABOVE_20_ONLY,
            today_low=99.0,
            today_close=ABOVE_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        asset = _make_asset("005930.KS", short_restricted=True)
        signals = check_entry_signals(df, "005930.KS", system=1, tracker=None, asset=asset)

        long_signals = [s for s in signals if s["direction"] == "LONG"]
        assert len(long_signals) == 1, "short_restricted=True 이어도 롱 시그널은 생성되어야 한다"

    def test_no_asset_fallback_uses_is_korean_market(self):
        """asset=None 이면 is_korean_market() fallback 사용 — KR 심볼은 숏 차단"""
        df = _make_df(
            today_high=99.0,
            today_low=BELOW_20_ONLY,
            today_close=BELOW_20_ONLY,
            dc_high_20=DC_HIGH_20,
            dc_low_20=DC_LOW_20,
            dc_high_55=DC_HIGH_55,
            dc_low_55=DC_LOW_55,
        )
        # asset=None → fallback to is_korean_market("005930.KS") → True → 차단
        signals = check_entry_signals(df, "005930.KS", system=1, tracker=None, asset=None)

        short_signals = [s for s in signals if s["direction"] == "SHORT"]
        assert len(short_signals) == 0, "asset=None + KR 심볼이면 fallback으로 숏이 차단되어야 한다"
