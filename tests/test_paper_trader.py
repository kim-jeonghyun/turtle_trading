"""
paper_trader.py 단위 테스트
- 매수/매도 주문 실행
- 슬리피지 방향 검증
- 수수료 공제 검증
- 피라미딩 평균 단가 계산
- 포트폴리오 스냅샷
- 상태 영속성 (저장/로드)
- PAPER_SLIPPAGE_PCT 환경변수 오버라이드
"""

import pytest

from src.paper_trader import PaperPortfolio

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def portfolio(tmp_path, monkeypatch):
    """임시 디렉터리를 사용하는 PaperPortfolio (상태 격리)"""
    paper_dir = tmp_path / "paper_trading"
    monkeypatch.setattr("src.paper_trader.PAPER_TRADING_DIR", paper_dir)
    monkeypatch.setattr("src.paper_trader.PORTFOLIO_PATH", paper_dir / "portfolio.json")
    monkeypatch.setattr("src.paper_trader.TRADES_PATH", paper_dir / "trades.json")
    return PaperPortfolio(
        initial_capital=10_000_000,
        slippage_pct=0.001,
        commission_pct=0.001,
    )


# ---------------------------------------------------------------------------
# 매수 주문
# ---------------------------------------------------------------------------


def test_execute_buy_order(portfolio):
    """매수 주문 후 현금이 줄고 포지션이 생성된다."""
    initial_cash = portfolio.cash
    record = portfolio.execute_paper_order(
        order_id="TEST_001",
        symbol="005930",
        side="buy",
        quantity=10,
        requested_price=70_000,
    )
    assert record.side == "buy"
    assert record.quantity == 10
    assert "005930" in portfolio.positions
    pos = portfolio.positions["005930"]
    assert pos.quantity == 10
    # 슬리피지가 적용된 fill_price로 체결
    expected_fill = 70_000 * (1 + 0.001)
    expected_cost = expected_fill * 10 * (1 + 0.001)
    assert portfolio.cash == pytest.approx(initial_cash - expected_cost, rel=1e-6)


# ---------------------------------------------------------------------------
# 매도 주문 (청산)
# ---------------------------------------------------------------------------


def test_execute_sell_order(portfolio):
    """매수 후 매도하면 포지션이 청산되고 PnL이 기록된다."""
    portfolio.execute_paper_order("BUY_001", "000660", "buy", 5, 100_000)
    assert "000660" in portfolio.positions

    record = portfolio.execute_paper_order("SELL_001", "000660", "sell", 5, 110_000)
    assert record.side == "sell"
    assert record.pnl != 0.0
    assert "000660" not in portfolio.positions


# ---------------------------------------------------------------------------
# 슬리피지 방향
# ---------------------------------------------------------------------------


def test_slippage_buy_higher(portfolio):
    """BUY 체결가는 요청가보다 높아야 한다."""
    record = portfolio.execute_paper_order("S1", "005930", "buy", 1, 50_000)
    assert record.fill_price > record.requested_price


def test_slippage_sell_lower(portfolio):
    """SELL 체결가는 요청가보다 낮아야 한다."""
    # 먼저 매수
    portfolio.execute_paper_order("B1", "005930", "buy", 1, 50_000)
    record = portfolio.execute_paper_order("S1", "005930", "sell", 1, 50_000)
    assert record.fill_price < record.requested_price


def test_slippage_zero(tmp_path, monkeypatch):
    """slippage_pct=0 이면 fill_price == requested_price"""
    paper_dir = tmp_path / "paper_trading_zero"
    monkeypatch.setattr("src.paper_trader.PAPER_TRADING_DIR", paper_dir)
    monkeypatch.setattr("src.paper_trader.PORTFOLIO_PATH", paper_dir / "portfolio.json")
    monkeypatch.setattr("src.paper_trader.TRADES_PATH", paper_dir / "trades.json")
    p = PaperPortfolio(initial_capital=1_000_000, slippage_pct=0.0, commission_pct=0.0)
    record = p.execute_paper_order("Z1", "TEST", "buy", 1, 10_000)
    assert record.fill_price == pytest.approx(10_000.0)
    assert record.slippage == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 수수료
# ---------------------------------------------------------------------------


def test_commission_deducted(tmp_path, monkeypatch):
    """commission_pct > 0 이면 현금이 추가로 감소한다."""
    paper_dir = tmp_path / "paper_comm"
    monkeypatch.setattr("src.paper_trader.PAPER_TRADING_DIR", paper_dir)
    monkeypatch.setattr("src.paper_trader.PORTFOLIO_PATH", paper_dir / "portfolio.json")
    monkeypatch.setattr("src.paper_trader.TRADES_PATH", paper_dir / "trades.json")
    # slippage_pct=0 으로 고정, commission만 확인
    p = PaperPortfolio(initial_capital=1_000_000, slippage_pct=0.0, commission_pct=0.001)
    initial_cash = p.cash
    record = p.execute_paper_order("C1", "TEST", "buy", 10, 10_000)
    expected_commission = 10_000 * 10 * 0.001
    assert record.commission == pytest.approx(expected_commission, rel=1e-6)
    # 현금 = initial - (fill_price * qty) - commission
    expected_cash = initial_cash - (10_000 * 10) - expected_commission
    assert p.cash == pytest.approx(expected_cash, rel=1e-6)


# ---------------------------------------------------------------------------
# 피라미딩 평균 단가
# ---------------------------------------------------------------------------


def test_pyramid_buy_avg_price(portfolio):
    """동일 종목 여러 번 매수 시 평균 단가가 올바르게 계산된다."""
    portfolio.execute_paper_order("B1", "035420", "buy", 10, 100_000)
    portfolio.execute_paper_order("B2", "035420", "buy", 10, 120_000)

    pos = portfolio.positions["035420"]
    assert pos.quantity == 20
    # fill_price = requested * (1 + slippage)
    fp1 = 100_000 * 1.001
    fp2 = 120_000 * 1.001
    expected_avg = (fp1 * 10 + fp2 * 10) / 20
    assert pos.avg_price == pytest.approx(expected_avg, rel=1e-6)


# ---------------------------------------------------------------------------
# 포트폴리오 스냅샷
# ---------------------------------------------------------------------------


def test_portfolio_snapshot(portfolio):
    """스냅샷이 정확한 필드와 값을 반환한다."""
    portfolio.execute_paper_order("B1", "005930", "buy", 5, 70_000)
    snap = portfolio.get_portfolio_snapshot()

    assert "cash" in snap
    assert "total_equity" in snap
    assert "total_pnl" in snap
    assert "return_pct" in snap
    assert "trade_count" in snap
    assert "total_slippage" in snap
    assert "total_commission" in snap
    assert snap["trade_count"] == 1
    assert snap["total_commission"] > 0
    # total_equity = cash + position_value
    assert snap["total_equity"] == pytest.approx(snap["cash"] + snap["total_position_value"], rel=1e-6)


# ---------------------------------------------------------------------------
# 영속성 (저장/로드)
# ---------------------------------------------------------------------------


def test_portfolio_persistence(tmp_path, monkeypatch):
    """저장 후 새 인스턴스에서 로드해도 상태가 유지된다."""
    paper_dir = tmp_path / "paper_persist"
    monkeypatch.setattr("src.paper_trader.PAPER_TRADING_DIR", paper_dir)
    portfolio_path = paper_dir / "portfolio.json"
    trades_path = paper_dir / "trades.json"
    monkeypatch.setattr("src.paper_trader.PORTFOLIO_PATH", portfolio_path)
    monkeypatch.setattr("src.paper_trader.TRADES_PATH", trades_path)

    p1 = PaperPortfolio(initial_capital=5_000_000, slippage_pct=0.0, commission_pct=0.0)
    p1.execute_paper_order("B1", "005930", "buy", 3, 80_000)
    saved_cash = p1.cash
    saved_qty = p1.positions["005930"].quantity

    # 새 인스턴스 생성 — 같은 경로에서 로드
    p2 = PaperPortfolio(initial_capital=5_000_000, slippage_pct=0.0, commission_pct=0.0)
    assert p2.cash == pytest.approx(saved_cash, rel=1e-6)
    assert "005930" in p2.positions
    assert p2.positions["005930"].quantity == saved_qty
    assert len(p2.trades) == 1


# ---------------------------------------------------------------------------
# 환경변수 슬리피지 오버라이드
# ---------------------------------------------------------------------------


def test_env_slippage_override(tmp_path, monkeypatch):
    """PAPER_SLIPPAGE_PCT 환경변수가 slippage_pct를 덮어쓴다."""
    paper_dir = tmp_path / "paper_env"
    monkeypatch.setattr("src.paper_trader.PAPER_TRADING_DIR", paper_dir)
    monkeypatch.setattr("src.paper_trader.PORTFOLIO_PATH", paper_dir / "portfolio.json")
    monkeypatch.setattr("src.paper_trader.TRADES_PATH", paper_dir / "trades.json")
    monkeypatch.setenv("PAPER_SLIPPAGE_PCT", "0.002")

    # slippage_pct=None → 환경변수에서 읽음
    p = PaperPortfolio(initial_capital=1_000_000, slippage_pct=None, commission_pct=0.0)
    assert p.slippage_pct == pytest.approx(0.002)
    record = p.execute_paper_order("E1", "TEST", "buy", 1, 10_000)
    assert record.fill_price == pytest.approx(10_000 * 1.002)
