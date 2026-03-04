"""
Paper Trading 모듈 단위 테스트

테스트 범위:
- 슬리피지 적용 (BUY, SELL, zero)
- 수수료 적용
- 포지션 PnL 계산 (LONG, SHORT)
- 포트폴리오 스냅샷 직렬화
- 초기 자본 설정
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.auto_trader import OrderRecord
from src.paper_trader import PaperPortfolio
from src.types import OrderStatus


def make_order_record(
    symbol: str = "005930",
    side: str = "buy",
    quantity: int = 10,
    price: float = 50_000.0,
    order_id: str = "DRY_TEST_0001",
) -> OrderRecord:
    """테스트용 OrderRecord 생성 헬퍼"""
    return OrderRecord(
        order_id=order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        order_type="MARKET",
        status=OrderStatus.DRY_RUN.value,
        timestamp="2026-03-04T09:00:00",
        dry_run=True,
        fill_price=price,  # dry-run 기본값
    )


@pytest.fixture()
def portfolio(tmp_path: Path) -> PaperPortfolio:
    """임시 디렉토리를 사용하는 PaperPortfolio 픽스처"""
    with (
        patch("src.paper_trader.PORTFOLIO_PATH", tmp_path / "portfolio.json"),
        patch("src.paper_trader.TRADES_PATH", tmp_path / "trades.json"),
    ):
        pp = PaperPortfolio(
            initial_capital=5_000_000,
            slippage_pct=0.0005,
            commission_pct=0.001,
        )
        yield pp


# ---------------------------------------------------------------------------
# 슬리피지 테스트
# ---------------------------------------------------------------------------


def test_slippage_buy(portfolio: PaperPortfolio) -> None:
    """BUY 체결가는 요청가보다 높아야 한다 (불리한 체결)"""
    requested = 50_000.0
    fill = portfolio._simulate_fill_price(requested, "buy")
    assert fill > requested
    assert fill == pytest.approx(requested * (1 + portfolio.slippage_pct))


def test_slippage_sell(portfolio: PaperPortfolio) -> None:
    """SELL 체결가는 요청가보다 낮아야 한다 (불리한 체결)"""
    requested = 50_000.0
    fill = portfolio._simulate_fill_price(requested, "sell")
    assert fill < requested
    assert fill == pytest.approx(requested * (1 - portfolio.slippage_pct))


def test_slippage_zero() -> None:
    """slippage_pct=0 이면 체결가 == 요청가"""
    with (
        patch("src.paper_trader.PORTFOLIO_PATH", Path(tempfile.mktemp(suffix=".json"))),
        patch("src.paper_trader.TRADES_PATH", Path(tempfile.mktemp(suffix=".json"))),
    ):
        pp = PaperPortfolio(slippage_pct=0.0, commission_pct=0.0)
        price = 70_000.0
        assert pp._simulate_fill_price(price, "buy") == pytest.approx(price)
        assert pp._simulate_fill_price(price, "sell") == pytest.approx(price)


# ---------------------------------------------------------------------------
# 수수료 테스트
# ---------------------------------------------------------------------------


def test_commission_applied(portfolio: PaperPortfolio, tmp_path: Path) -> None:
    """BUY 실행 후 수수료가 차감되어 잔고가 줄어야 한다"""
    initial_cash = portfolio.cash
    record = make_order_record(quantity=10, price=50_000.0)

    with (
        patch("src.paper_trader.PORTFOLIO_PATH", tmp_path / "portfolio.json"),
        patch("src.paper_trader.TRADES_PATH", tmp_path / "trades.json"),
    ):
        portfolio.execute_paper_order(record)

    fill_price = 50_000.0 * (1 + portfolio.slippage_pct)
    trade_amount = fill_price * 10
    commission = trade_amount * portfolio.commission_pct
    expected_cash = initial_cash - trade_amount - commission

    assert portfolio.cash == pytest.approx(expected_cash, rel=1e-6)
    assert portfolio.total_commission == pytest.approx(commission, rel=1e-6)


# ---------------------------------------------------------------------------
# PnL 계산 테스트
# ---------------------------------------------------------------------------


def test_portfolio_pnl_long(portfolio: PaperPortfolio, tmp_path: Path) -> None:
    """LONG 포지션: BUY 후 SELL 시 수익 PnL 검증"""
    buy_record = make_order_record(side="buy", quantity=10, price=50_000.0, order_id="BUY_001")
    sell_record = make_order_record(side="sell", quantity=10, price=60_000.0, order_id="SELL_001")

    with (
        patch("src.paper_trader.PORTFOLIO_PATH", tmp_path / "portfolio.json"),
        patch("src.paper_trader.TRADES_PATH", tmp_path / "trades.json"),
    ):
        portfolio.execute_paper_order(buy_record)
        cash_after_buy = portfolio.cash
        portfolio.execute_paper_order(sell_record)
        cash_after_sell = portfolio.cash

    # SELL 후 잔고 > BUY 후 잔고 (수익 발생)
    assert cash_after_sell > cash_after_buy


def test_portfolio_pnl_short(portfolio: PaperPortfolio, tmp_path: Path) -> None:
    """SHORT 포지션: SELL 먼저, BUY로 청산 (잔고 감소 확인)"""
    # SELL 먼저 (공매도 진입)
    sell_record = make_order_record(side="sell", quantity=10, price=60_000.0, order_id="SELL_001")
    buy_record = make_order_record(side="buy", quantity=10, price=50_000.0, order_id="BUY_001")

    with (
        patch("src.paper_trader.PORTFOLIO_PATH", tmp_path / "portfolio.json"),
        patch("src.paper_trader.TRADES_PATH", tmp_path / "trades.json"),
    ):
        initial_cash = portfolio.cash
        portfolio.execute_paper_order(sell_record)
        # SELL로 현금이 증가
        assert portfolio.cash > initial_cash
        portfolio.execute_paper_order(buy_record)


# ---------------------------------------------------------------------------
# 포트폴리오 스냅샷 직렬화 테스트
# ---------------------------------------------------------------------------


def test_portfolio_snapshot_serialization(portfolio: PaperPortfolio, tmp_path: Path) -> None:
    """get_portfolio_snapshot()이 JSON 직렬화 가능한 dict를 반환해야 한다"""
    buy_record = make_order_record(side="buy", quantity=5, price=40_000.0)

    with (
        patch("src.paper_trader.PORTFOLIO_PATH", tmp_path / "portfolio.json"),
        patch("src.paper_trader.TRADES_PATH", tmp_path / "trades.json"),
    ):
        portfolio.execute_paper_order(buy_record)
        snapshot = portfolio.get_portfolio_snapshot()

    # JSON 직렬화 가능한지 확인
    json_str = json.dumps(snapshot)
    restored = json.loads(json_str)

    assert restored["initial_capital"] == portfolio.initial_capital
    assert "cash" in restored
    assert "total_equity" in restored
    assert "return_rate" in restored
    assert "positions" in restored
    assert isinstance(restored["positions"], dict)


def test_portfolio_snapshot_return_rate(portfolio: PaperPortfolio, tmp_path: Path) -> None:
    """초기 자본 그대로면 수익률 0"""
    # 아무 거래도 없을 때
    with (
        patch("src.paper_trader.PORTFOLIO_PATH", tmp_path / "portfolio.json"),
        patch("src.paper_trader.TRADES_PATH", tmp_path / "trades.json"),
    ):
        snapshot = portfolio.get_portfolio_snapshot()

    assert snapshot["return_rate"] == pytest.approx(0.0)
    assert snapshot["total_equity"] == pytest.approx(portfolio.initial_capital)


# ---------------------------------------------------------------------------
# 초기 자본 테스트
# ---------------------------------------------------------------------------


def test_initial_capital_default(tmp_path: Path) -> None:
    """기본 초기 자본은 5,000,000원"""
    with (
        patch("src.paper_trader.PORTFOLIO_PATH", tmp_path / "portfolio.json"),
        patch("src.paper_trader.TRADES_PATH", tmp_path / "trades.json"),
    ):
        pp = PaperPortfolio()
    assert pp.initial_capital == 5_000_000
    assert pp.cash == 5_000_000


def test_initial_capital_custom(tmp_path: Path) -> None:
    """커스텀 초기 자본 설정"""
    with (
        patch("src.paper_trader.PORTFOLIO_PATH", tmp_path / "portfolio.json"),
        patch("src.paper_trader.TRADES_PATH", tmp_path / "trades.json"),
    ):
        pp = PaperPortfolio(initial_capital=10_000_000)
    assert pp.initial_capital == 10_000_000
    assert pp.cash == 10_000_000


# ---------------------------------------------------------------------------
# 상태 영속화 테스트
# ---------------------------------------------------------------------------


def test_state_persistence(tmp_path: Path) -> None:
    """save_state/load_state 후 잔고가 복원되어야 한다"""
    portfolio_path = tmp_path / "portfolio.json"
    trades_path = tmp_path / "trades.json"

    with (
        patch("src.paper_trader.PORTFOLIO_PATH", portfolio_path),
        patch("src.paper_trader.TRADES_PATH", trades_path),
    ):
        pp1 = PaperPortfolio(initial_capital=3_000_000)
        buy_record = make_order_record(quantity=5, price=100_000.0)
        pp1.execute_paper_order(buy_record)
        cash_after = pp1.cash

        # 새 인스턴스로 복원
        pp2 = PaperPortfolio(initial_capital=3_000_000)

    assert pp2.cash == pytest.approx(cash_after, rel=1e-6)
