"""
TradingGuard 단위 테스트.

일일 손실 서킷브레이커, 주문 크기 제한, 상태 영속화 검증.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.trading_guard import TradingGuard, TradingLimits


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state_path(tmp_path: Path) -> Path:
    return tmp_path / "trading_guard_state.json"


@pytest.fixture
def limits() -> TradingLimits:
    return TradingLimits(
        max_daily_loss_pct=0.03,
        max_order_amount=2_000_000,
        max_order_pct=0.10,
    )


@pytest.fixture
def mock_kill_switch() -> MagicMock:
    ks = MagicMock()
    ks.activate = MagicMock()
    return ks


@pytest.fixture
def guard(limits: TradingLimits, mock_kill_switch: MagicMock, tmp_state_path: Path) -> TradingGuard:
    return TradingGuard(limits=limits, kill_switch=mock_kill_switch, state_path=tmp_state_path)


# ---------------------------------------------------------------------------
# check_daily_loss — 일일 손실 체크
# ---------------------------------------------------------------------------


def test_daily_loss_under_limit(guard: TradingGuard) -> None:
    """손실이 한도 미만이면 진입 허용"""
    total_equity = 5_000_000.0
    # 한도: 5M * 3% = 150,000원. 손실 100,000원은 한도 미만
    guard._daily_realized_loss = -100_000.0

    allowed, reason = guard.check_daily_loss(total_equity)

    assert allowed is True
    assert reason == ""
    guard.kill_switch.activate.assert_not_called()


def test_daily_loss_exceeds_limit(guard: TradingGuard) -> None:
    """손실이 한도 초과 시 차단 + 킬 스위치 활성화"""
    total_equity = 5_000_000.0
    # 한도: 5M * 3% = 150,000원. 손실 200,000원은 한도 초과
    guard._daily_realized_loss = -200_000.0

    allowed, reason = guard.check_daily_loss(total_equity)

    assert allowed is False
    assert "서킷브레이커" in reason
    guard.kill_switch.activate.assert_called_once()
    call_kwargs = guard.kill_switch.activate.call_args
    assert "한도 초과" in call_kwargs[1]["reason"] or "한도 초과" in str(call_kwargs)


def test_daily_loss_exactly_at_limit_is_allowed(guard: TradingGuard) -> None:
    """손실이 정확히 한도와 같으면 허용 (초과가 아님)"""
    total_equity = 5_000_000.0
    max_loss = total_equity * 0.03  # 150,000원
    guard._daily_realized_loss = -max_loss  # 정확히 한도

    allowed, reason = guard.check_daily_loss(total_equity)

    # abs(150,000) > 150,000 은 False → 허용
    assert allowed is True


def test_daily_loss_resets_next_day(guard: TradingGuard, tmp_state_path: Path) -> None:
    """날짜 변경 시 일일 손실 카운터 리셋"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    guard._daily_realized_loss = -200_000.0
    guard._daily_reset_date = yesterday

    # record_trade_result 호출 시 날짜 체크로 리셋 발생
    guard.record_trade_result(pnl=0.0)

    today = datetime.now().strftime("%Y-%m-%d")
    assert guard._daily_reset_date == today
    assert guard._daily_realized_loss == 0.0


# ---------------------------------------------------------------------------
# check_order_size — 주문 크기 체크
# ---------------------------------------------------------------------------


def test_order_size_absolute_limit(guard: TradingGuard) -> None:
    """주문 금액이 max_order_amount 초과 시 차단"""
    total_equity = 10_000_000.0
    amount = 2_100_000.0  # 2.1M > 2M 한도

    allowed, reason = guard.check_order_size(amount, total_equity)

    assert allowed is False
    assert "주문 금액 초과" in reason


def test_order_size_percentage_limit(guard: TradingGuard) -> None:
    """주문 비율이 max_order_pct 초과 시 차단"""
    total_equity = 5_000_000.0
    # 10% 한도 = 500,000원. 주문 600,000원 < 2M이지만 비율 초과
    amount = 600_000.0

    allowed, reason = guard.check_order_size(amount, total_equity)

    assert allowed is False
    assert "주문 비율 초과" in reason


def test_order_size_within_limits(guard: TradingGuard) -> None:
    """정상 주문 (절대값 + 비율 모두 한도 이내) 허용"""
    total_equity = 5_000_000.0
    amount = 400_000.0  # 400K < 2M, 400K/5M = 8% < 10%

    allowed, reason = guard.check_order_size(amount, total_equity)

    assert allowed is True
    assert reason == ""


def test_order_size_just_under_limits(guard: TradingGuard) -> None:
    """경계값: 양쪽 한도 모두 딱 미만인 경우"""
    total_equity = 5_000_000.0
    amount = 499_999.0  # < 2M, 499999/5M = 9.99% < 10%

    allowed, reason = guard.check_order_size(amount, total_equity)

    assert allowed is True


# ---------------------------------------------------------------------------
# Entry-Only Block — SELL 주문은 가드를 우회
# ---------------------------------------------------------------------------


def test_sell_bypasses_all_guards(guard: TradingGuard) -> None:
    """SELL 주문은 TradingGuard 체크 없이 항상 허용 (Entry-Only Block)

    TradingGuard 자체는 check_daily_loss / check_order_size 만 제공.
    BUY/SELL 구분은 호출측(auto_trader.place_order)에서 처리하므로
    가드 함수가 SELL에 대해 허용 반환하는지 확인한다.
    """
    total_equity = 5_000_000.0
    # 일일 손실이 한도 초과 상태여도
    guard._daily_realized_loss = -200_000.0

    # 가드 함수를 직접 호출하지 않는 것이 SELL 시나리오지만,
    # auto_trader는 SELL에서 이 메서드를 호출하지 않는다.
    # 여기서는 가드가 항상 판단 값을 반환함을 확인.
    # SELL에서는 check_daily_loss가 호출되지 않아야 함 (auto_trader 레벨에서 보장).
    # 이 테스트는 TradingGuard의 개별 체크가 독립적으로 동작함을 확인.
    allowed_loss, _ = guard.check_daily_loss(total_equity)
    assert allowed_loss is False  # 손실 초과 상태이므로 False

    # SELL의 경우 auto_trader에서 호출 자체를 건너뛰어야 한다.
    # 이는 test_auto_trader.py에서 통합 검증.


# ---------------------------------------------------------------------------
# record_trade_result — 손실 누적
# ---------------------------------------------------------------------------


def test_record_trade_accumulates_loss(guard: TradingGuard) -> None:
    """연속 손실이 정확히 누적되는지 확인"""
    guard.record_trade_result(pnl=-50_000.0)
    guard.record_trade_result(pnl=-30_000.0)
    guard.record_trade_result(pnl=-20_000.0)

    assert guard.daily_realized_loss == pytest.approx(-100_000.0)


def test_record_trade_ignores_profit(guard: TradingGuard) -> None:
    """수익은 일일 손실 카운터에 추가되지 않음"""
    guard.record_trade_result(pnl=-50_000.0)
    guard.record_trade_result(pnl=100_000.0)  # 수익 무시

    assert guard.daily_realized_loss == pytest.approx(-50_000.0)


def test_record_trade_zero_pnl(guard: TradingGuard) -> None:
    """pnl=0은 손실도 수익도 아님 — 카운터 변화 없음"""
    guard.record_trade_result(pnl=0.0)
    assert guard.daily_realized_loss == 0.0


# ---------------------------------------------------------------------------
# 상태 영속화 — 프로세스 재시작 시뮬레이션
# ---------------------------------------------------------------------------


def test_state_persistence_across_processes(
    limits: TradingLimits, mock_kill_switch: MagicMock, tmp_state_path: Path
) -> None:
    """상태 저장 후 새 인스턴스에서 복원 확인 (프로세스 재시작 시뮬레이션)"""
    # 첫 번째 인스턴스에서 손실 기록
    guard1 = TradingGuard(limits=limits, kill_switch=mock_kill_switch, state_path=tmp_state_path)
    guard1.record_trade_result(pnl=-75_000.0)
    guard1.record_trade_result(pnl=-25_000.0)
    assert guard1.daily_realized_loss == pytest.approx(-100_000.0)

    # 두 번째 인스턴스 (새 프로세스 시뮬레이션)
    guard2 = TradingGuard(limits=limits, kill_switch=mock_kill_switch, state_path=tmp_state_path)
    assert guard2.daily_realized_loss == pytest.approx(-100_000.0)


def test_state_file_missing_initializes_zero(
    limits: TradingLimits, mock_kill_switch: MagicMock, tmp_path: Path
) -> None:
    """상태 파일 없으면 0으로 초기화 (안전한 방향)"""
    missing_path = tmp_path / "nonexistent" / "state.json"

    guard = TradingGuard(limits=limits, kill_switch=mock_kill_switch, state_path=missing_path)

    assert guard.daily_realized_loss == 0.0


def test_state_date_mismatch_resets(
    limits: TradingLimits, mock_kill_switch: MagicMock, tmp_state_path: Path
) -> None:
    """어제 날짜 파일을 오늘 로드하면 카운터 리셋"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    state_data = {
        "date": yesterday,
        "daily_realized_loss": -200_000.0,
        "last_updated": f"{yesterday}T14:30:00",
    }
    tmp_state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_state_path.write_text(json.dumps(state_data))

    guard = TradingGuard(limits=limits, kill_switch=mock_kill_switch, state_path=tmp_state_path)

    today = datetime.now().strftime("%Y-%m-%d")
    assert guard.daily_reset_date == today
    assert guard.daily_realized_loss == 0.0


def test_state_saved_after_record(
    limits: TradingLimits, mock_kill_switch: MagicMock, tmp_state_path: Path
) -> None:
    """record_trade_result 호출 후 상태 파일이 저장되는지 확인"""
    guard = TradingGuard(limits=limits, kill_switch=mock_kill_switch, state_path=tmp_state_path)
    guard.record_trade_result(pnl=-50_000.0)

    assert tmp_state_path.exists()
    saved = json.loads(tmp_state_path.read_text())
    assert saved["daily_realized_loss"] == pytest.approx(-50_000.0)
    assert "date" in saved
    assert "last_updated" in saved


# ---------------------------------------------------------------------------
# TradingLimits — 커스텀 설정
# ---------------------------------------------------------------------------


def test_custom_limits_from_config(
    mock_kill_switch: MagicMock, tmp_state_path: Path
) -> None:
    """TradingLimits 커스텀 값이 체크에 반영되는지 확인"""
    custom_limits = TradingLimits(
        max_daily_loss_pct=0.05,  # 5%
        max_order_amount=1_000_000,  # 100만원
        max_order_pct=0.05,  # 5%
    )
    guard = TradingGuard(
        limits=custom_limits, kill_switch=mock_kill_switch, state_path=tmp_state_path
    )

    total_equity = 5_000_000.0

    # 커스텀 손실 한도: 5M * 5% = 250,000원
    guard._daily_realized_loss = -200_000.0
    allowed, _ = guard.check_daily_loss(total_equity)
    assert allowed is True  # 200K < 250K

    guard._daily_realized_loss = -300_000.0
    allowed, _ = guard.check_daily_loss(total_equity)
    assert allowed is False  # 300K > 250K

    # 커스텀 주문 한도: 100만원
    allowed, reason = guard.check_order_size(1_100_000.0, total_equity)
    assert allowed is False
    assert "주문 금액 초과" in reason

    # 커스텀 비율 한도: 5%
    allowed, reason = guard.check_order_size(260_000.0, total_equity)  # 5.2% > 5%
    assert allowed is False
    assert "주문 비율 초과" in reason
