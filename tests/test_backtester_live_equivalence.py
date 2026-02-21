"""
backtester._check_entry_signal() <-> check_positions.check_entry_signals() 동치성 검증

Issue #18: 동일한 시장 상황에서 backtester와 live checker가 동일한 진입/스킵 판단을
내리는지 parametrized 테스트로 검증한다.

설계 원칙:
  - 어느 한쪽만 수정했을 때 테스트가 깨져야 한다 (divergence 조기 감지).
  - 두 모듈의 인터페이스 차이를 어댑터 함수로 흡수한다.
  - 테스트 시나리오는 Curtis Faith 원서 규칙에 기반한다.

두 모듈 인터페이스 비교:
  - backtester._check_entry_signal(row, prev_row, symbol) -> Optional[SignalType]
    * self.config.system, self.config.use_filter, self.last_trade_profitable 에 의존
  - check_positions.check_entry_signals(df, symbol, system, tracker) -> list[dict]
    * tracker.get_position_history() 로 직전 거래 수익 여부 판단
"""

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pandas as pd
import pytest

# scripts/ 디렉토리를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.check_positions import _should_allow_entry, check_entry_signals
from src.backtester import BacktestConfig, TurtleBacktester
from src.position_tracker import Position
from src.types import SignalType

# ---------------------------------------------------------------------------
# Donchian 채널 기준값 (테스트 전체 공통)
# ---------------------------------------------------------------------------
DC_HIGH_20 = 105.0
DC_LOW_20 = 95.0
DC_HIGH_55 = 110.0
DC_LOW_55 = 90.0

# 돌파/이탈 가격
ABOVE_20_ONLY = DC_HIGH_20 + 1.0   # 106: 20일 돌파, 55일 미돌파
ABOVE_55 = DC_HIGH_55 + 1.0        # 111: 20일 + 55일 모두 돌파
BELOW_20_ONLY = DC_LOW_20 - 1.0    # 94: 20일 이탈, 55일 미이탈
BELOW_55 = DC_LOW_55 - 1.0         # 89: 20일 + 55일 모두 이탈

NEUTRAL_HIGH = 102.0  # 돌파 없음
NEUTRAL_LOW = 97.0    # 이탈 없음

SYMBOL = "SPY"  # 미국 심볼 (롱/숏 모두 가능)


# ---------------------------------------------------------------------------
# 어댑터: backtester 인터페이스
# ---------------------------------------------------------------------------

def backtester_decision(
    *,
    system: int,
    use_filter: bool,
    last_trade_profitable: bool,
    today_high: float,
    today_low: float,
    direction: str,
) -> bool:
    """backtester._check_entry_signal() 을 호출하여 진입 여부를 bool 로 반환.

    Returns:
        True  -> 진입 허용 (signal returned)
        False -> 스킵 (None returned)
    """
    config = BacktestConfig(system=system, use_filter=use_filter)
    bt = TurtleBacktester(config)

    if last_trade_profitable:
        bt.last_trade_profitable[SYMBOL] = True
    else:
        # False 를 명시적으로 넣거나, 키를 아예 안 넣으면 .get() 이 False 반환
        bt.last_trade_profitable[SYMBOL] = False

    # prev_row: yesterday (Donchian 채널 기준값)
    prev_row = pd.Series({
        "dc_high_20": DC_HIGH_20,
        "dc_low_20": DC_LOW_20,
        "dc_high_55": DC_HIGH_55,
        "dc_low_55": DC_LOW_55,
    })

    # row: today
    row = pd.Series({
        "high": today_high,
        "low": today_low,
    })

    signal = bt._check_entry_signal(row, prev_row, SYMBOL)

    if direction == "LONG":
        return signal == SignalType.ENTRY_LONG
    else:
        return signal == SignalType.ENTRY_SHORT


# ---------------------------------------------------------------------------
# 어댑터: live checker 인터페이스
# ---------------------------------------------------------------------------

def _make_closed_position(
    symbol: str,
    system: int,
    pnl: float,
) -> Position:
    """테스트용 청산 Position 객체 생성."""
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
        exit_date="2025-02-15",
        exit_price=110.0 if pnl > 0 else 90.0,
        pnl=pnl,
    )


def live_decision(
    *,
    system: int,
    last_trade_profitable: bool,
    today_high: float,
    today_low: float,
    direction: str,
) -> bool:
    """check_entry_signals() 를 호출하여 진입 여부를 bool 로 반환.

    Returns:
        True  -> 진입 허용 (signal list 에 해당 direction 시그널이 존재)
        False -> 스킵 (해당 direction 시그널 없음)
    """
    n_value = 2.0

    # 2행 DataFrame: yesterday(Donchian 기준) + today(가격)
    yesterday = {
        "date": pd.Timestamp("2025-03-01"),
        "high": 100.0,
        "low": 98.0,
        "close": 99.0,
        "N": n_value,
        "dc_high_20": DC_HIGH_20,
        "dc_low_20": DC_LOW_20,
        "dc_high_55": DC_HIGH_55,
        "dc_low_55": DC_LOW_55,
    }
    today = {
        "date": pd.Timestamp("2025-03-02"),
        "high": today_high,
        "low": today_low,
        "close": (today_high + today_low) / 2,
        "N": n_value,
        "dc_high_20": DC_HIGH_20,
        "dc_low_20": DC_LOW_20,
        "dc_high_55": DC_HIGH_55,
        "dc_low_55": DC_LOW_55,
    }
    df = pd.DataFrame([yesterday, today])

    # tracker mock: 수익/손실 이력 설정
    if last_trade_profitable:
        pos = _make_closed_position(SYMBOL, system=1, pnl=200.0)
        tracker = MagicMock()
        tracker.get_position_history.return_value = [pos]
    else:
        # 손실 이력이 있는 경우
        pos = _make_closed_position(SYMBOL, system=1, pnl=-100.0)
        tracker = MagicMock()
        tracker.get_position_history.return_value = [pos]

    signals = check_entry_signals(df, SYMBOL, system=system, tracker=tracker)

    matching = [s for s in signals if s["direction"] == direction]
    return len(matching) > 0


# ---------------------------------------------------------------------------
# Parametrized 동치성 시나리오
# ---------------------------------------------------------------------------

# 각 시나리오: (id, system, last_profitable, today_high, today_low, direction, expected)
EQUIVALENCE_SCENARIOS = [
    # ---------------------------------------------------------------
    # Scenario 1: System 1, 수익 후 20일만 돌파 -> 둘 다 스킵
    # ---------------------------------------------------------------
    pytest.param(
        1,      # system
        True,   # last_trade_profitable
        ABOVE_20_ONLY,   # today_high (106: 20일 돌파, 55일 미돌파)
        NEUTRAL_LOW,     # today_low (97: 이탈 없음)
        "LONG",
        False,  # expected: 스킵
        id="S1-profitable-20day_only-LONG-skip",
    ),
    # ---------------------------------------------------------------
    # Scenario 2: System 1, 수익 후 55일 돌파 -> 둘 다 진입
    # ---------------------------------------------------------------
    pytest.param(
        1,
        True,
        ABOVE_55,        # today_high (111: 55일 돌파)
        NEUTRAL_LOW,
        "LONG",
        True,   # expected: 진입 (55일 failsafe)
        id="S1-profitable-55day-LONG-entry",
    ),
    # ---------------------------------------------------------------
    # Scenario 3: System 1, 손실 후 20일 돌파 -> 둘 다 진입
    # ---------------------------------------------------------------
    pytest.param(
        1,
        False,  # last_trade_profitable = False (손실)
        ABOVE_20_ONLY,
        NEUTRAL_LOW,
        "LONG",
        True,   # expected: 진입 (손실 후 필터 미적용)
        id="S1-losing-20day-LONG-entry",
    ),
    # ---------------------------------------------------------------
    # Scenario 4: System 2, 수익 후 55일 돌파 -> 둘 다 진입
    # ---------------------------------------------------------------
    pytest.param(
        2,
        True,
        ABOVE_55,
        NEUTRAL_LOW,
        "LONG",
        True,   # expected: 진입 (System 2 필터 없음)
        id="S2-profitable-55day-LONG-entry",
    ),
    # ---------------------------------------------------------------
    # 추가 시나리오: SHORT 방향 동치성
    # ---------------------------------------------------------------
    pytest.param(
        1,
        True,
        NEUTRAL_HIGH,
        BELOW_20_ONLY,   # today_low (94: 20일 이탈, 55일 미이탈)
        "SHORT",
        False,  # expected: 스킵 (수익 후 20일만 이탈)
        id="S1-profitable-20day_only-SHORT-skip",
    ),
    pytest.param(
        1,
        True,
        NEUTRAL_HIGH,
        BELOW_55,        # today_low (89: 55일 이탈)
        "SHORT",
        True,   # expected: 진입 (55일 failsafe)
        id="S1-profitable-55day-SHORT-entry",
    ),
    pytest.param(
        1,
        False,
        NEUTRAL_HIGH,
        BELOW_20_ONLY,
        "SHORT",
        True,   # expected: 진입 (손실 후 필터 미적용)
        id="S1-losing-20day-SHORT-entry",
    ),
    pytest.param(
        2,
        True,
        NEUTRAL_HIGH,
        BELOW_55,
        "SHORT",
        True,   # expected: 진입 (System 2 필터 없음)
        id="S2-profitable-55day-SHORT-entry",
    ),
]


class TestBacktesterLiveEquivalence:
    """backtester와 live checker의 진입/스킵 판단 동치성 검증.

    어느 한쪽의 필터 로직만 수정하면 이 테스트가 실패하여
    divergence를 조기에 감지할 수 있다.
    """

    @pytest.mark.parametrize(
        "system, last_profitable, today_high, today_low, direction, expected",
        EQUIVALENCE_SCENARIOS,
    )
    def test_both_systems_agree(
        self,
        system: int,
        last_profitable: bool,
        today_high: float,
        today_low: float,
        direction: str,
        expected: bool,
    ):
        """backtester와 live checker가 동일한 판단을 내리는지 검증."""
        bt_result = backtester_decision(
            system=system,
            use_filter=True,
            last_trade_profitable=last_profitable,
            today_high=today_high,
            today_low=today_low,
            direction=direction,
        )

        live_result = live_decision(
            system=system,
            last_trade_profitable=last_profitable,
            today_high=today_high,
            today_low=today_low,
            direction=direction,
        )

        # 핵심 assertion: 두 시스템의 판단이 일치해야 한다
        assert bt_result == live_result, (
            f"DIVERGENCE DETECTED!\n"
            f"  Scenario: system={system}, profitable={last_profitable}, "
            f"direction={direction}\n"
            f"  today_high={today_high}, today_low={today_low}\n"
            f"  backtester={bt_result}, live_checker={live_result}\n"
            f"  expected={expected}\n"
            f"  -> 한쪽만 수정되었을 가능성이 있습니다."
        )

        # 추가 assertion: 기대 결과와도 일치해야 한다
        assert bt_result == expected, (
            f"backtester 결과가 기대와 다릅니다: "
            f"got={bt_result}, expected={expected}"
        )
        assert live_result == expected, (
            f"live_checker 결과가 기대와 다릅니다: "
            f"got={live_result}, expected={expected}"
        )


class TestShouldAllowEntryEquivalence:
    """_should_allow_entry() 헬퍼와 backtester 내부 로직의 동치성 검증.

    _should_allow_entry() 는 live checker 에서 추출한 헬퍼 함수이므로,
    backtester 의 인라인 필터 로직과 동일한 결과를 내야 한다.

    Note: System 1 만 backtester 와의 end-to-end 비교를 수행한다.
    System 2 의 backtester 는 entry channel 이 dc_high_55 이므로 진입 채널과
    필터 채널이 분리되지 않는다. System 2 는 _should_allow_entry() 헬퍼의
    순수 로직만 검증한다.
    """

    @pytest.mark.parametrize(
        "is_profitable, is_55day_breakout, expected",
        [
            # 수익 + 55일 미돌파 -> 스킵
            (True, False, False),
            # 수익 + 55일 돌파 -> 진입 (failsafe)
            (True, True, True),
            # 손실 + 55일 미돌파 -> 진입
            (False, False, True),
            # 손실 + 55일 돌파 -> 진입
            (False, True, True),
        ],
        ids=[
            "S1-profitable-no55-skip",
            "S1-profitable-55day-entry",
            "S1-losing-no55-entry",
            "S1-losing-55day-entry",
        ],
    )
    def test_system1_helper_matches_backtester(
        self,
        is_profitable: bool,
        is_55day_breakout: bool,
        expected: bool,
    ):
        """System 1: _should_allow_entry() 결과와 backtester 인라인 필터를 비교.

        backtester 의 인라인 로직:
          if self.config.system == 1 and self.config.use_filter:
              if self.last_trade_profitable.get(symbol, False):
                  if row["high"] <= prev_row.get("dc_high_55", float("inf")):
                      return None  # 스킵
        """
        # _should_allow_entry() 결과
        helper_result = _should_allow_entry(1, is_profitable, is_55day_breakout)
        assert helper_result == expected

        # backtester 인라인 로직 시뮬레이션 (LONG 방향)
        # System 1 entry channel 은 dc_high_20, 필터 채널은 dc_high_55
        if is_55day_breakout:
            today_high = DC_HIGH_55 + 1.0  # 55일 돌파
        else:
            today_high = DC_HIGH_20 + 1.0  # 20일만 돌파 (55일 미돌파)

        bt_result = backtester_decision(
            system=1,
            use_filter=True,
            last_trade_profitable=is_profitable,
            today_high=today_high,
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )

        assert bt_result == expected, (
            f"backtester 인라인 로직과 _should_allow_entry() 결과 불일치!\n"
            f"  _should_allow_entry(1, {is_profitable}, {is_55day_breakout}) = {helper_result}\n"
            f"  backtester(today_high={today_high}) = {bt_result}\n"
            f"  expected = {expected}"
        )

    @pytest.mark.parametrize(
        "is_profitable, is_55day_breakout",
        [
            (False, False),
            (False, True),
        ],
        ids=[
            "S2-losing-no55",
            "S2-losing-55day",
        ],
    )
    def test_system2_helper_allows_when_not_profitable(
        self,
        is_profitable: bool,
        is_55day_breakout: bool,
    ):
        """System 2: _should_allow_entry(is_profitable=False) -> True.

        System 2 의 caller (_was_last_trade_profitable) 는 sys_num != 1 이면
        항상 False 를 반환하므로, _should_allow_entry 는 is_profitable=False 로
        호출된다. 이 경우 항상 True 를 반환한다.
        """
        assert _should_allow_entry(2, is_profitable, is_55day_breakout) is True

        # backtester: System 2 entry channel 은 dc_high_55
        bt_result = backtester_decision(
            system=2,
            use_filter=True,
            last_trade_profitable=is_profitable,
            today_high=ABOVE_55,  # System 2 는 55일 채널 돌파가 필요
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        assert bt_result is True, (
            f"System 2 backtester 는 55일 돌파 시 항상 진입해야 함 "
            f"(profitable={is_profitable})"
        )

    def test_system2_filter_bypass_mechanism(self):
        """System 2 필터 우회 메커니즘의 동치성 검증.

        backtester: config.system == 2 이면 필터 분기 자체를 건너뜀
        live checker: _was_last_trade_profitable() 가 system != 1 이면 False 반환

        결과적으로 두 시스템 모두 System 2 에서는 필터를 적용하지 않는다.
        profitable=True 로 설정해도 backtester 는 System 2 이므로 필터를 건너뛴다.
        """
        # backtester: System 2 는 필터 분기에 진입하지 않으므로 profitable 무관
        bt_result = backtester_decision(
            system=2,
            use_filter=True,
            last_trade_profitable=True,  # profitable 이어도 무관
            today_high=ABOVE_55,
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        assert bt_result is True, (
            "backtester System 2: 필터 분기를 건너뛰므로 profitable 과 무관하게 진입"
        )

        # live checker: System 2 에서도 동일하게 진입
        live_result = live_decision(
            system=2,
            last_trade_profitable=True,  # live 에서는 _was_last_trade_profitable 이 False 반환
            today_high=ABOVE_55,
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        assert live_result is True, (
            "live checker System 2: _was_last_trade_profitable 이 False 반환하므로 진입"
        )

        assert bt_result == live_result, "System 2 필터 우회: 양쪽 동치"


class TestNoBreakoutBothAgree:
    """돌파/이탈 조건이 충족되지 않으면 양쪽 모두 시그널 없음 확인."""

    def test_no_breakout_no_signal_from_either(self):
        """today 가격이 채널 안에 있으면 backtester/live 모두 진입 없음."""
        bt_long = backtester_decision(
            system=1,
            use_filter=True,
            last_trade_profitable=False,
            today_high=NEUTRAL_HIGH,  # 102: 돌파 없음
            today_low=NEUTRAL_LOW,    # 97: 이탈 없음
            direction="LONG",
        )
        bt_short = backtester_decision(
            system=1,
            use_filter=True,
            last_trade_profitable=False,
            today_high=NEUTRAL_HIGH,
            today_low=NEUTRAL_LOW,
            direction="SHORT",
        )
        live_long = live_decision(
            system=1,
            last_trade_profitable=False,
            today_high=NEUTRAL_HIGH,
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        live_short = live_decision(
            system=1,
            last_trade_profitable=False,
            today_high=NEUTRAL_HIGH,
            today_low=NEUTRAL_LOW,
            direction="SHORT",
        )

        assert bt_long is False, "backtester: 돌파 없으면 LONG 시그널 없어야 함"
        assert bt_short is False, "backtester: 이탈 없으면 SHORT 시그널 없어야 함"
        assert live_long is False, "live: 돌파 없으면 LONG 시그널 없어야 함"
        assert live_short is False, "live: 이탈 없으면 SHORT 시그널 없어야 함"


class TestFilterDisabledEquivalence:
    """use_filter=False 일 때 backtester가 필터를 무시하는지,
    그리고 live checker 에서 System 2 (필터 없음)와 동일한 동작을 하는지 검증.
    """

    def test_filter_disabled_allows_entry_after_profit(self):
        """use_filter=False: 수익 후 20일 돌파도 진입 허용."""
        bt_result = backtester_decision(
            system=1,
            use_filter=False,
            last_trade_profitable=True,
            today_high=ABOVE_20_ONLY,
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        # live checker 의 System 2 는 필터 없음으로 동일 동작
        live_s2_result = live_decision(
            system=2,
            last_trade_profitable=True,
            today_high=ABOVE_55,  # System 2 는 55일 채널 사용
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )

        assert bt_result is True, "use_filter=False 일 때 backtester 진입 허용"
        assert live_s2_result is True, "System 2 는 항상 진입 허용"


class TestBoundaryEquivalence:
    """경계값에서의 동치성: 정확히 채널 값과 같을 때 양쪽 모두 같은 판단."""

    def test_exact_20day_channel_no_entry_both(self):
        """today_high == dc_high_20 -> strict > 비교이므로 양쪽 모두 진입 없음."""
        bt = backtester_decision(
            system=1,
            use_filter=True,
            last_trade_profitable=False,
            today_high=DC_HIGH_20,  # 정확히 같음
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        live = live_decision(
            system=1,
            last_trade_profitable=False,
            today_high=DC_HIGH_20,
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        assert bt == live == False, (
            "today_high == dc_high_20: 양쪽 모두 strict > 이므로 진입 없어야 함"
        )

    def test_exact_55day_channel_no_failsafe_both(self):
        """수익 후 today_high == dc_high_55 -> failsafe 비발동, 양쪽 모두 스킵."""
        # today_high 는 dc_high_55 와 같지만 20일은 돌파
        today_high = DC_HIGH_55  # 정확히 110.0 (> dc_high_20=105 이지만 == dc_high_55)
        bt = backtester_decision(
            system=1,
            use_filter=True,
            last_trade_profitable=True,
            today_high=today_high,
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        live = live_decision(
            system=1,
            last_trade_profitable=True,
            today_high=today_high,
            today_low=NEUTRAL_LOW,
            direction="LONG",
        )
        assert bt == live == False, (
            "today_high == dc_high_55: 55일 failsafe 비발동, 양쪽 모두 스킵"
        )

    def test_exact_20day_short_no_entry_both(self):
        """today_low == dc_low_20 -> strict < 비교이므로 양쪽 모두 SHORT 진입 없음."""
        bt = backtester_decision(
            system=1,
            use_filter=True,
            last_trade_profitable=False,
            today_high=NEUTRAL_HIGH,
            today_low=DC_LOW_20,  # 정확히 같음
            direction="SHORT",
        )
        live = live_decision(
            system=1,
            last_trade_profitable=False,
            today_high=NEUTRAL_HIGH,
            today_low=DC_LOW_20,
            direction="SHORT",
        )
        assert bt == live == False, (
            "today_low == dc_low_20: 양쪽 모두 strict < 이므로 SHORT 진입 없어야 함"
        )

    def test_exact_55day_short_no_failsafe_both(self):
        """수익 후 today_low == dc_low_55 -> failsafe 비발동, 양쪽 모두 SHORT 스킵."""
        today_low = DC_LOW_55  # 정확히 90.0 (< dc_low_20=95 이지만 == dc_low_55)
        bt = backtester_decision(
            system=1,
            use_filter=True,
            last_trade_profitable=True,
            today_high=NEUTRAL_HIGH,
            today_low=today_low,
            direction="SHORT",
        )
        live = live_decision(
            system=1,
            last_trade_profitable=True,
            today_high=NEUTRAL_HIGH,
            today_low=today_low,
            direction="SHORT",
        )
        assert bt == live == False, (
            "today_low == dc_low_55: 55일 failsafe 비발동, 양쪽 모두 SHORT 스킵"
        )
