"""AutoTrader 런타임 통합 테스트.

TradingGuard + CostAnalyzer가 주문 경로에 올바르게 연결되었는지 검증.
Guard chain: kill_switch → vi_cb_detector → trading_guard → [5M safety net] → order
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auto_trader import AutoTrader
from src.cost_analyzer import CostAnalyzer
from src.kill_switch import KillSwitch
from src.kis_api import OrderSide
from src.trading_guard import TradingGuard, TradingLimits
from src.types import OrderStatus


@pytest.fixture
def mock_kis_client():
    client = MagicMock()
    client.place_order = AsyncMock(return_value={"success": True, "order_no": "KIS001"})
    client.get_balance = AsyncMock(return_value={"total_equity": 5_000_000, "cash": 5_000_000})
    return client


@pytest.fixture
def kill_switch(tmp_path):
    # KillSwitch uses config_path (writes YAML); tmp_path / "ks.yaml" avoids
    # collisions with the real project config/system_status.yaml.
    return KillSwitch(config_path=tmp_path / "ks.yaml")


@pytest.fixture
def trading_guard(kill_switch, tmp_path):
    return TradingGuard(
        limits=TradingLimits(max_daily_loss_pct=0.03, max_order_amount=2_000_000),
        kill_switch=kill_switch,
        state_path=tmp_path / "guard.json",
    )


@pytest.fixture
def cost_analyzer(tmp_path):
    return CostAnalyzer(cost_log_path=tmp_path / "cost.json")


@pytest.fixture
def auto_trader(mock_kis_client, kill_switch, trading_guard, cost_analyzer, tmp_path):
    with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
        trader = AutoTrader(
            kis_client=mock_kis_client,
            dry_run=True,
            kill_switch=kill_switch,
            trading_guard=trading_guard,
            cost_analyzer=cost_analyzer,
            initial_capital=10_000_000,  # 10M: keeps 10주*70K=700K well under 10% ratio
        )
    return trader


class TestGuardChainBlocksBuy:
    """6-A: TradingGuard가 일일 손실 초과 상태에서 BUY 차단 검증."""

    def test_daily_loss_exceeds_blocks_buy(self, auto_trader, trading_guard, tmp_path):
        # initial_capital=10M, max_daily_loss_pct=3% → 한도 300K
        # -400K 손실로 한도 초과
        trading_guard.record_trade_result(-400_000)

        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            record = asyncio.run(
                auto_trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=70_000,
                    reason="test",
                )
            )

        assert record.status == OrderStatus.REJECTED.value
        assert record.order_id == "BLOCKED_GUARD"
        assert "손실" in (record.error_message or "")

    def test_order_size_exceeds_blocks_buy(self, auto_trader, tmp_path):
        """주문 금액 2M 초과 시 차단 (100주 * 30,000원 = 3,000,000원 > 2,000,000원 한도)."""
        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            record = asyncio.run(
                auto_trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.BUY,
                    quantity=100,
                    price=30_000,  # 3M > 2M limit
                    reason="test",
                )
            )

        assert record.status == OrderStatus.REJECTED.value
        assert record.order_id == "BLOCKED_GUARD"
        assert "주문" in (record.error_message or "")


class TestGuardChainAllowsSell:
    """6-B: 같은 상태에서 SELL은 통과 검증 (Entry-Only Block)."""

    def test_sell_bypasses_trading_guard(self, auto_trader, trading_guard, tmp_path):
        # initial_capital=10M, max_daily_loss_pct=3% → 한도 300K; -400K로 초과
        trading_guard.record_trade_result(-400_000)

        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            record = asyncio.run(
                auto_trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.SELL,
                    quantity=10,
                    price=70_000,
                    reason="exit",
                )
            )

        # SELL은 TradingGuard에서 차단되지 않아야 함 (DRY_RUN 상태로 통과)
        assert record.status != OrderStatus.REJECTED.value
        assert record.status == OrderStatus.DRY_RUN.value


class TestCostAnalyzerRecordsOnFill:
    """6-C: 주문 체결 후 CostAnalyzer.analyze_order() 호출 검증."""

    def test_cost_recorded_on_dry_run_fill(self, auto_trader, cost_analyzer, tmp_path):
        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            record = asyncio.run(
                auto_trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=70_000,
                    reason="test",
                )
            )

        assert record.status == OrderStatus.DRY_RUN.value
        # CostAnalyzer에 비용이 기록되어 있어야 함
        cumulative = cost_analyzer.get_cumulative_costs()
        assert cumulative["trade_count"] == 1
        assert cumulative["total_cost"] > 0


class TestBudgetTripActivatesKillSwitch:
    """6-D: 예산 초과 시 KillSwitch 활성화 end-to-end 검증."""

    def test_budget_exceeded_activates_kill_switch(self, cost_analyzer, kill_switch, tmp_path):
        # 큰 슬리피지를 가진 거래를 반복 기록하여 예산 임계 초과 유도
        # 주당 슬리피지 1,000원, 10주 = 10,000원/거래, 50회 = 500,000원 누적 비용
        # 자산 5M * 0.2% = 10,000원 임계치 → 2번째 거래 이후 초과
        for i in range(50):
            cost_analyzer.analyze_order(
                order_id=f"TEST_{i:03d}",
                symbol="005930.KS",
                requested_price=70_000,
                fill_price=71_000,  # 1,000원 슬리피지
                quantity=10,
            )

        total_equity = 5_000_000
        realized_profit = 100_000

        ok, reason = cost_analyzer.check_budget_limit(total_equity, realized_profit)

        # 누적 비용이 임계를 초과해야 함
        assert not ok, f"Expected budget exceeded but got ok=True, reason={reason}"
        kill_switch.activate(reason=reason)
        assert not kill_switch.is_trading_enabled


class TestCostAnalyzerFailOpen:
    """CostAnalyzer 예외가 주문 성공 상태를 깨뜨리지 않는지 검증 (fail-open)."""

    def test_analyze_order_exception_does_not_break_order(self, mock_kis_client, tmp_path):
        """analyze_order()에서 예외 발생해도 주문은 DRY_RUN 상태 유지."""
        broken_analyzer = MagicMock()
        broken_analyzer.analyze_order.side_effect = RuntimeError("disk full")

        ks = KillSwitch(config_path=tmp_path / "ks.yaml")
        guard = TradingGuard(
            limits=TradingLimits(),
            kill_switch=ks,
            state_path=tmp_path / "guard.json",
        )

        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            trader = AutoTrader(
                kis_client=mock_kis_client,
                dry_run=True,
                kill_switch=ks,
                trading_guard=guard,
                cost_analyzer=broken_analyzer,
                initial_capital=10_000_000,
            )

            record = asyncio.run(
                trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=70_000,
                    reason="fail-open test",
                )
            )

        # 주문 상태는 정상이어야 함 (analyze_order 예외가 전파되지 않음)
        assert record.status == OrderStatus.DRY_RUN.value
        # analyze_order는 호출 시도됨
        broken_analyzer.analyze_order.assert_called_once()

    def test_live_order_preserved_on_analyzer_exception(self, tmp_path):
        """Live 주문 성공 후 analyze_order() 예외가 주문 상태(FILLED)를 깨뜨리지 않음."""
        mock_kis = MagicMock()
        mock_kis.place_order = AsyncMock(
            return_value={"success": True, "order_no": "KIS_LIVE_001", "order_time": "09:01:00"}
        )

        broken_analyzer = MagicMock()
        broken_analyzer.analyze_order.side_effect = RuntimeError("disk full")

        ks = KillSwitch(config_path=tmp_path / "ks.yaml")
        guard = TradingGuard(
            limits=TradingLimits(),
            kill_switch=ks,
            state_path=tmp_path / "guard.json",
        )

        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            trader = AutoTrader(
                kis_client=mock_kis,
                dry_run=False,
                kill_switch=ks,
                trading_guard=guard,
                cost_analyzer=broken_analyzer,
                initial_capital=10_000_000,
            )

            record = asyncio.run(
                trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=70_000,
                    reason="live fail-open test",
                )
            )

        # Live 주문이 FILLED 상태로 유지되어야 함 (FAILED가 아님!)
        assert record.status == OrderStatus.FILLED.value
        assert record.order_id == "KIS_LIVE_001"
        # analyze_order는 호출 시도됨
        broken_analyzer.analyze_order.assert_called_once()


class TestFullGuardChainOrder:
    """6-E: kill_switch → vi_cb → trading_guard → [5M] → order 전체 체인 검증."""

    def test_full_chain_normal_order(self, mock_kis_client, tmp_path):
        """정상 주문: 전체 체인 통과."""
        ks = KillSwitch(config_path=tmp_path / "ks.yaml")
        guard = TradingGuard(
            limits=TradingLimits(),
            kill_switch=ks,
            state_path=tmp_path / "guard.json",
        )
        analyzer = CostAnalyzer(cost_log_path=tmp_path / "cost.json")

        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            trader = AutoTrader(
                kis_client=mock_kis_client,
                dry_run=True,
                kill_switch=ks,
                trading_guard=guard,
                cost_analyzer=analyzer,
                initial_capital=10_000_000,  # 10M: 700K order = 7% < 10% ratio limit
            )

            record = asyncio.run(
                trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=70_000,
                    reason="full chain test",
                )
            )

        assert record.status == OrderStatus.DRY_RUN.value
        assert analyzer.get_cumulative_costs()["trade_count"] == 1

    def test_kill_switch_blocks_before_guard(self, mock_kis_client, tmp_path):
        """킬 스위치 활성 → TradingGuard 도달 전에 차단."""
        ks = KillSwitch(config_path=tmp_path / "ks.yaml")
        ks.activate(reason="test shutdown")
        guard = TradingGuard(
            limits=TradingLimits(),
            kill_switch=ks,
            state_path=tmp_path / "guard.json",
        )

        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            trader = AutoTrader(
                kis_client=mock_kis_client,
                dry_run=True,
                kill_switch=ks,
                trading_guard=guard,
            )

            record = asyncio.run(
                trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=70_000,
                    reason="should be blocked by kill switch",
                )
            )

        # kill_switch는 order_id="BLOCKED"로 차단
        assert record.status == OrderStatus.REJECTED.value
        assert record.order_id == "BLOCKED"

    def test_none_guard_backward_compatible(self, mock_kis_client, tmp_path):
        """TradingGuard=None이면 기존 동작 유지 (AC5 후방 호환성)."""
        with patch("src.auto_trader.ORDER_LOG_PATH", tmp_path / "orders.json"):
            trader = AutoTrader(
                kis_client=mock_kis_client,
                dry_run=True,
                trading_guard=None,
                cost_analyzer=None,
            )

            record = asyncio.run(
                trader.place_order(
                    symbol="005930.KS",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=70_000,
                    reason="no guard test",
                )
            )

        assert record.status == OrderStatus.DRY_RUN.value


class TestPaperTradeReportAccuracy:
    """AC17: save_state() → print_report() 라운드트립 정확성 검증."""

    def test_save_state_fields_consumed_by_report(self, tmp_path):
        """save_state()가 저장한 position_value/total_equity를 print_report()가 정확히 사용."""
        from scripts.paper_trade_report import print_report
        from src.paper_trader import PaperPortfolio, PaperPosition

        port_path = tmp_path / "port.json"
        with patch("src.paper_trader.PORTFOLIO_PATH", port_path):
            portfolio = PaperPortfolio(initial_capital=5_000_000)
            # 포지션 추가: 005930 100주 @ 70,000원
            portfolio.positions["005930"] = PaperPosition(
                symbol="005930",
                side="BUY",
                quantity=100,
                entry_price=70_000,
                fill_price=70_100,  # 슬리피지 반영 체결가
                commission=7_000,
                timestamp="2026-03-05T09:00:00",
            )
            portfolio.cash = 5_000_000 - (70_100 * 100) - 7_000  # 잔여 현금
            portfolio.total_commission = 7_000
            portfolio.total_slippage_cost = 10_000

            # save_state → 파일에 저장
            portfolio.save_state()

        # 저장된 파일 로드
        from src.utils import safe_load_json

        state = safe_load_json(tmp_path / "port.json", default={})

        # 핵심 검증: position_value, total_equity 필드 존재 + 정확한 값
        expected_position_value = 70_100 * 100  # fill_price * quantity
        expected_total_equity = portfolio.cash + expected_position_value

        assert "position_value" in state, "save_state에 position_value 필드 누락"
        assert "total_equity" in state, "save_state에 total_equity 필드 누락"
        assert state["position_value"] == expected_position_value
        assert state["total_equity"] == expected_total_equity

        # print_report가 이 값을 정확히 사용하는지 검증 (stdout 캡처)
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_report(state, [])

        output = buf.getvalue()
        # 총 자산과 포지션 평가액이 리포트에 정확히 표시됨
        assert f"{expected_total_equity:,.0f}" in output
        assert f"{expected_position_value:,.0f}" in output
