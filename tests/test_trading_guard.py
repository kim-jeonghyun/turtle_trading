"""Trading Guard 단위 테스트 -- 일일 손실 CB + 주문 크기 제한."""

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.kill_switch import KillSwitch
from src.trading_guard import TradingGuard, TradingLimits

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kill_switch(tmp_path):
    """KillSwitch mock -- activate() 호출 추적용"""
    config_path = tmp_path / "system_status.yaml"
    ks = KillSwitch(config_path=config_path)
    return ks


@pytest.fixture
def default_limits():
    return TradingLimits()


@pytest.fixture
def guard(tmp_path, mock_kill_switch, default_limits):
    """기본 TradingGuard 인스턴스 (tmp_path 사용)"""
    state_path = tmp_path / "guard_state.json"
    return TradingGuard(
        limits=default_limits,
        kill_switch=mock_kill_switch,
        state_path=state_path,
    )


# ---------------------------------------------------------------------------
# Daily Loss Tests
# ---------------------------------------------------------------------------


class TestDailyLoss:
    def test_daily_loss_under_limit(self, guard):
        """손실 < 한도 -> 허용"""
        equity = 10_000_000  # 1000만원
        guard._daily_realized_loss = -200_000  # -20만원 (한도: 30만원)
        ok, reason = guard.check_daily_loss(equity)
        assert ok is True
        assert reason == ""

    def test_daily_loss_exceeds_limit(self, guard, mock_kill_switch):
        """손실 > 한도 -> 차단 + 킬 스위치 활성화"""
        equity = 10_000_000  # 1000만원, 한도 = 30만원
        guard._daily_realized_loss = -400_000  # -40만원 > 30만원

        ok, reason = guard.check_daily_loss(equity)
        assert ok is False
        assert "서킷브레이커" in reason
        # 킬 스위치가 활성화되었는지 확인
        assert not mock_kill_switch.is_trading_enabled

    def test_daily_loss_resets_next_day(self, tmp_path, mock_kill_switch, default_limits):
        """날짜 변경 시 카운터 리셋"""
        state_path = tmp_path / "guard_state.json"
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        # 어제 날짜의 상태 파일 작성
        state_path.write_text(
            json.dumps(
                {
                    "date": yesterday,
                    "daily_realized_loss": -500_000,
                }
            )
        )

        guard = TradingGuard(
            limits=default_limits,
            kill_switch=mock_kill_switch,
            state_path=state_path,
        )
        # 날짜가 다르므로 리셋되어야 함
        assert guard._daily_realized_loss == 0.0
        assert guard._daily_reset_date == datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Order Size Tests
# ---------------------------------------------------------------------------


class TestOrderSize:
    def test_order_size_absolute_limit(self, guard):
        """금액 > max_order_amount -> 차단"""
        ok, reason = guard.check_order_size(3_000_000, 50_000_000)
        assert ok is False
        assert "주문 금액 초과" in reason

    def test_order_size_percentage_limit(self, guard):
        """금액 > equity * max_order_pct -> 차단"""
        # equity 10M, 10% = 1M, 주문 1.5M (절대한도 2M 이내이지만 비율 초과)
        ok, reason = guard.check_order_size(1_500_000, 10_000_000)
        assert ok is False
        assert "주문 비율 초과" in reason

    def test_order_size_within_limits(self, guard):
        """정상 범위 주문 -> 허용"""
        # equity 50M, 10% = 5M, 주문 1M (절대한도 2M 이내, 비율도 OK)
        ok, reason = guard.check_order_size(1_000_000, 50_000_000)
        assert ok is True
        assert reason == ""


# ---------------------------------------------------------------------------
# Trade Recording Tests
# ---------------------------------------------------------------------------


class TestRecordTrade:
    def test_record_trade_accumulates_loss(self, guard):
        """손실 거래가 누적되는지 확인"""
        guard.record_trade_result(-100_000)
        guard.record_trade_result(-50_000)
        assert guard._daily_realized_loss == -150_000

    def test_record_trade_profit_not_offset(self, guard):
        """수익은 손실 카운터에서 상계하지 않음"""
        guard.record_trade_result(-100_000)
        guard.record_trade_result(200_000)  # 수익 -- 상계 안 됨
        assert guard._daily_realized_loss == -100_000

    def test_record_trade_resets_on_new_day(self, guard):
        """날짜 변경 시 record_trade_result에서 리셋"""
        guard._daily_realized_loss = -500_000
        guard._daily_reset_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        guard.record_trade_result(-10_000)
        # 날짜 변경 후 -10_000만 반영
        assert guard._daily_realized_loss == -10_000


# ---------------------------------------------------------------------------
# State Persistence Tests
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_state_persistence_across_processes(self, tmp_path, mock_kill_switch, default_limits):
        """상태 저장 후 새 인스턴스에서 복원"""
        state_path = tmp_path / "guard_state.json"
        guard1 = TradingGuard(
            limits=default_limits,
            kill_switch=mock_kill_switch,
            state_path=state_path,
        )
        guard1.record_trade_result(-200_000)

        # 새 인스턴스 생성 -- 상태가 복원되어야 함
        guard2 = TradingGuard(
            limits=default_limits,
            kill_switch=mock_kill_switch,
            state_path=state_path,
        )
        assert guard2._daily_realized_loss == -200_000

    def test_state_file_missing_initializes_zero(self, tmp_path, mock_kill_switch, default_limits):
        """파일 없음 -> 0에서 시작"""
        state_path = tmp_path / "nonexistent_state.json"
        guard = TradingGuard(
            limits=default_limits,
            kill_switch=mock_kill_switch,
            state_path=state_path,
        )
        assert guard._daily_realized_loss == 0.0

    def test_state_date_mismatch_resets(self, tmp_path, mock_kill_switch, default_limits):
        """어제 날짜 파일 -> 오늘 리셋"""
        state_path = tmp_path / "guard_state.json"
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        state_path.write_text(json.dumps({"date": yesterday, "daily_realized_loss": -999_999}))

        guard = TradingGuard(
            limits=default_limits,
            kill_switch=mock_kill_switch,
            state_path=state_path,
        )
        assert guard._daily_realized_loss == 0.0


# ---------------------------------------------------------------------------
# Custom Limits Tests
# ---------------------------------------------------------------------------


class TestCustomLimits:
    def test_custom_limits_from_config(self, tmp_path, mock_kill_switch):
        """커스텀 TradingLimits 값 적용"""
        custom = TradingLimits(
            max_daily_loss_pct=0.05,
            max_order_amount=5_000_000,
            max_order_pct=0.20,
        )
        state_path = tmp_path / "guard_state.json"
        guard = TradingGuard(
            limits=custom,
            kill_switch=mock_kill_switch,
            state_path=state_path,
        )

        # 커스텀 한도 적용 확인: 4M 주문은 기본 2M 초과하지만 커스텀 5M 이내
        ok, reason = guard.check_order_size(4_000_000, 50_000_000)
        assert ok is True


# ---------------------------------------------------------------------------
# AutoTrader Integration Tests
# ---------------------------------------------------------------------------


class TestAutoTraderIntegration:
    """AutoTrader와 TradingGuard 연동 테스트"""

    def _make_trader(self, tmp_path, guard=None, dry_run=True):
        """테스트용 AutoTrader 생성"""
        from src.auto_trader import AutoTrader

        kis_client = MagicMock()
        trader = AutoTrader(
            kis_client=kis_client,
            dry_run=dry_run,
            trading_guard=guard,
            initial_capital=10_000_000,
        )
        return trader

    def test_sell_bypasses_all_guards(self, tmp_path, guard):
        """SELL 주문은 trading guard 적용 안 됨"""
        from src.kis_api import OrderSide

        # 손실 한도 초과 상태로 설정
        guard._daily_realized_loss = -999_999_999

        trader = self._make_trader(tmp_path, guard=guard)
        result = asyncio.run(
            trader.place_order(
                symbol="005930",
                side=OrderSide.SELL,
                quantity=10,
                price=70_000,
            )
        )
        # SELL은 가드 무시 -- dry_run 성공
        assert result.status == "dry_run"

    def test_guard_chain_order(self, tmp_path, mock_kill_switch, default_limits):
        """kill_switch -> vi_cb -> trading_guard 순서 확인"""
        from src.kis_api import OrderSide

        state_path = tmp_path / "guard_state.json"
        guard = TradingGuard(
            limits=default_limits,
            kill_switch=mock_kill_switch,
            state_path=state_path,
        )

        # 킬 스위치 활성화
        mock_kill_switch.activate(reason="테스트")

        trader = self._make_trader(tmp_path, guard=guard)
        trader.kill_switch = mock_kill_switch

        result = asyncio.run(
            trader.place_order(
                symbol="005930",
                side=OrderSide.BUY,
                quantity=10,
                price=70_000,
            )
        )
        # 킬 스위치가 먼저 차단 (trading_guard 아닌 kill_switch 사유)
        assert result.status == "rejected"
        assert "킬 스위치" in (result.reason or "")

    def test_defense_in_depth_both_layers(self, tmp_path, mock_kill_switch):
        """2M 비즈니스 가드와 5M 시스템 안전망 동시 동작"""
        from src.kis_api import OrderSide

        state_path = tmp_path / "guard_state.json"
        limits = TradingLimits(max_order_amount=2_000_000)
        guard = TradingGuard(
            limits=limits,
            kill_switch=mock_kill_switch,
            state_path=state_path,
        )

        # 비즈니스 가드 (2M) 테스트: 2.5M 주문
        trader = self._make_trader(tmp_path, guard=guard)
        result = asyncio.run(
            trader.place_order(
                symbol="005930",
                side=OrderSide.BUY,
                quantity=50,
                price=50_000,  # 2.5M
            )
        )
        assert result.status == "rejected"
        assert "주문 금액 초과" in (result.error_message or "")

        # 시스템 안전망 (5M) 테스트: guard 없이 6M 주문
        trader_no_guard = self._make_trader(tmp_path, guard=None)
        result2 = asyncio.run(
            trader_no_guard.place_order(
                symbol="005930",
                side=OrderSide.BUY,
                quantity=100,
                price=60_000,  # 6M
            )
        )
        assert result2.status == "failed"
        assert "주문 금액 초과" in (result2.error_message or "")


# ---------------------------------------------------------------------------
# Equity Cache Tests
# ---------------------------------------------------------------------------


class TestEquityCache:
    def test_equity_cache_dry_run(self, tmp_path):
        """dry_run 모드에서 initial_capital 반환"""
        from src.auto_trader import AutoTrader

        kis_client = MagicMock()
        trader = AutoTrader(
            kis_client=kis_client,
            dry_run=True,
            initial_capital=20_000_000,
        )

        equity = asyncio.run(trader._get_equity())
        assert equity == 20_000_000
        # 캐싱 확인
        assert trader._cached_equity == 20_000_000

    def test_equity_cache_live_mode(self, tmp_path):
        """live 모드에서 KIS API 호출 후 캐싱"""
        from src.auto_trader import AutoTrader

        kis_client = MagicMock()
        kis_client.get_balance = AsyncMock(
            return_value={"total_equity": 15_000_000, "cash": 5_000_000, "positions": []}
        )

        trader = AutoTrader(
            kis_client=kis_client,
            dry_run=False,
            initial_capital=10_000_000,
        )

        equity = asyncio.run(trader._get_equity())
        assert equity == 15_000_000

        # 두 번째 호출은 캐시에서 반환 (API 호출 1회만)
        equity2 = asyncio.run(trader._get_equity())
        assert equity2 == 15_000_000
        kis_client.get_balance.assert_awaited_once()

    def test_equity_cache_reset(self, tmp_path):
        """캐시 리셋 후 재조회"""
        from src.auto_trader import AutoTrader

        kis_client = MagicMock()
        trader = AutoTrader(
            kis_client=kis_client,
            dry_run=True,
            initial_capital=20_000_000,
        )

        asyncio.run(trader._get_equity())
        assert trader._cached_equity == 20_000_000

        trader.reset_equity_cache()
        assert trader._cached_equity is None
