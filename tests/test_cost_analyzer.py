"""
CostAnalyzer 단위 테스트

테스트 범위:
- 슬리피지 계산: 요청 가격 vs 체결 가격 (BUY 양수, SELL 음수)
- 수수료 계산: fill_amount * rate
- 다건 누적 비용 추적
- 이중 예산 점검: 자산 임계 초과 → (False, 사유)
- 이중 예산 점검: 수익 임계 초과 → (False, 사유)
- 두 임계 모두 이내 → (True, "")
- realized_profit <= 0 → 수익 임계 스킵, 자산 임계만 적용
- realized_profit = 0 → 수익 임계 스킵
- 빈 비용 이력 → 모두 0
- 비용 영속성 (저장 후 재로드)
"""

from pathlib import Path

import pytest

from src.cost_analyzer import CostAnalyzer, TradeCost


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def analyzer(tmp_path: Path) -> CostAnalyzer:
    """임시 경로를 사용하는 CostAnalyzer 픽스처."""
    return CostAnalyzer(commission_rate=0.00015, cost_log_path=tmp_path / "cost_log.json")


# ---------------------------------------------------------------------------
# 슬리피지 계산
# ---------------------------------------------------------------------------


def test_slippage_buy_positive(analyzer: CostAnalyzer) -> None:
    """BUY: 체결가 > 요청가 → 슬리피지 양수."""
    cost = analyzer.analyze_order(
        order_id="O001",
        symbol="005930",
        requested_price=50_000.0,
        fill_price=50_100.0,
        quantity=10,
    )
    assert cost.slippage == pytest.approx(100.0)
    assert cost.slippage_pct == pytest.approx(100.0 / 50_000.0)


def test_slippage_sell_negative(analyzer: CostAnalyzer) -> None:
    """SELL: 체결가 < 요청가 → 슬리피지 음수."""
    cost = analyzer.analyze_order(
        order_id="O002",
        symbol="005930",
        requested_price=50_000.0,
        fill_price=49_900.0,
        quantity=10,
    )
    assert cost.slippage == pytest.approx(-100.0)
    assert cost.slippage_pct == pytest.approx(-100.0 / 50_000.0)


def test_slippage_zero(analyzer: CostAnalyzer) -> None:
    """요청가 = 체결가 → 슬리피지 0."""
    cost = analyzer.analyze_order(
        order_id="O003",
        symbol="005930",
        requested_price=50_000.0,
        fill_price=50_000.0,
        quantity=10,
    )
    assert cost.slippage == pytest.approx(0.0)
    assert cost.slippage_pct == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 수수료 계산
# ---------------------------------------------------------------------------


def test_commission_calculation(analyzer: CostAnalyzer) -> None:
    """수수료 = fill_amount * commission_rate."""
    fill_price = 50_000.0
    quantity = 10
    cost = analyzer.analyze_order(
        order_id="O004",
        symbol="005930",
        requested_price=50_000.0,
        fill_price=fill_price,
        quantity=quantity,
    )
    expected_commission = fill_price * quantity * 0.00015
    assert cost.commission == pytest.approx(expected_commission)


def test_total_cost_combines_slippage_and_commission(analyzer: CostAnalyzer) -> None:
    """total_cost = abs(slippage * qty) + commission."""
    cost = analyzer.analyze_order(
        order_id="O005",
        symbol="005930",
        requested_price=50_000.0,
        fill_price=50_200.0,
        quantity=5,
    )
    expected_slippage_cost = abs(200.0 * 5)
    expected_commission = 50_200.0 * 5 * 0.00015
    assert cost.total_cost == pytest.approx(expected_slippage_cost + expected_commission)


# ---------------------------------------------------------------------------
# 누적 비용 추적
# ---------------------------------------------------------------------------


def test_cumulative_costs_multiple_orders(analyzer: CostAnalyzer) -> None:
    """다건 주문 후 누적 통계 집계."""
    analyzer.analyze_order("O1", "005930", 50_000.0, 50_100.0, 10)
    analyzer.analyze_order("O2", "000660", 80_000.0, 79_900.0, 5)
    analyzer.analyze_order("O3", "005380", 200_000.0, 200_000.0, 3)

    result = analyzer.get_cumulative_costs()

    assert result["trade_count"] == 3
    assert result["total_slippage"] > 0
    assert result["total_commission"] > 0
    assert result["total_cost"] > 0
    assert 0.0 <= result["avg_slippage_pct"]


def test_empty_cost_history(analyzer: CostAnalyzer) -> None:
    """비용 이력 없음 → 모두 0."""
    result = analyzer.get_cumulative_costs()
    assert result["total_slippage"] == 0.0
    assert result["total_commission"] == 0.0
    assert result["total_cost"] == 0.0
    assert result["avg_slippage_pct"] == 0.0
    assert result["trade_count"] == 0


# ---------------------------------------------------------------------------
# 이중 예산 점검
# ---------------------------------------------------------------------------


def test_budget_within_limits(analyzer: CostAnalyzer) -> None:
    """두 임계 모두 이내 → (True, "")."""
    # 소액 비용만 기록
    analyzer.analyze_order("O1", "005930", 50_000.0, 50_050.0, 1)

    ok, reason = analyzer.check_budget_limit(
        total_equity=100_000_000.0,   # 1억
        realized_profit=10_000_000.0, # 1천만 수익
    )
    assert ok is True
    assert reason == ""


def test_budget_equity_threshold_exceeded(analyzer: CostAnalyzer) -> None:
    """누적 비용이 자산 임계 초과 → (False, 사유 포함)."""
    # 자산 대비 0.2% 초과하는 비용 수동 주입
    analyzer._costs = []
    # total_equity=1_000_000, equity_threshold=0.002 → limit=2000원
    # total_cost가 2001원 이상이 되도록 주문 생성
    cost = analyzer.analyze_order(
        order_id="O_BIG",
        symbol="005930",
        requested_price=10_000.0,
        fill_price=10_500.0,  # slippage=500 * 10 = 5000원
        quantity=10,
    )
    assert cost.total_cost > 2000  # 검사 조건 확인

    ok, reason = analyzer.check_budget_limit(
        total_equity=1_000_000.0,
        realized_profit=500_000.0,
        equity_threshold_pct=0.002,
        profit_threshold_pct=0.15,
    )
    assert ok is False
    assert "자산 기준" in reason


def test_budget_profit_threshold_exceeded(analyzer: CostAnalyzer) -> None:
    """수익 임계 초과 → (False, 수익 기준 사유 포함)."""
    # realized_profit=10_000, profit_threshold=0.15 → limit=1500원
    # equity=100_000_000 (자산 임계=200,000원 — 자산 임계는 통과)
    # total_cost > 1500원이 되도록 설정
    analyzer.analyze_order(
        order_id="O_PROFIT",
        symbol="005930",
        requested_price=10_000.0,
        fill_price=10_200.0,  # slippage=200 * 10 = 2000원
        quantity=10,
    )

    ok, reason = analyzer.check_budget_limit(
        total_equity=100_000_000.0,  # 자산 임계=200,000원 → 통과
        realized_profit=10_000.0,    # 수익 임계=1,500원 → 초과
        equity_threshold_pct=0.002,
        profit_threshold_pct=0.15,
    )
    assert ok is False
    assert "수익 기준" in reason


def test_budget_skip_profit_check_when_no_profit(analyzer: CostAnalyzer) -> None:
    """realized_profit <= 0 → 수익 임계 스킵, 자산 임계만 적용."""
    analyzer.analyze_order("O1", "005930", 10_000.0, 10_200.0, 10)

    # 수익 = 0 → 수익 임계 스킵, 자산(100억) 임계는 통과
    ok, reason = analyzer.check_budget_limit(
        total_equity=10_000_000_000.0,  # 100억 — 자산 임계 확실히 통과
        realized_profit=0.0,
    )
    assert ok is True
    assert reason == ""


def test_budget_skip_profit_check_when_negative_profit(analyzer: CostAnalyzer) -> None:
    """realized_profit < 0 → 수익 임계 스킵, 자산 임계만 적용."""
    analyzer.analyze_order("O1", "005930", 10_000.0, 10_200.0, 10)

    ok, reason = analyzer.check_budget_limit(
        total_equity=10_000_000_000.0,
        realized_profit=-500_000.0,  # 손실 상태
    )
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# 비용 영속성 (저장/재로드)
# ---------------------------------------------------------------------------


def test_cost_persistence(tmp_path: Path) -> None:
    """비용 데이터 저장 후 새 인스턴스에서 재로드."""
    log_path = tmp_path / "cost_log.json"

    # 저장
    a1 = CostAnalyzer(cost_log_path=log_path)
    a1.analyze_order("O1", "005930", 50_000.0, 50_100.0, 10)
    a1.analyze_order("O2", "000660", 80_000.0, 79_900.0, 5)

    # 새 인스턴스로 재로드
    a2 = CostAnalyzer(cost_log_path=log_path)
    result = a2.get_cumulative_costs()

    assert result["trade_count"] == 2
    assert result["total_cost"] > 0


# ---------------------------------------------------------------------------
# 입력 검증 (C2)
# ---------------------------------------------------------------------------


def test_analyze_order_rejects_zero_quantity(analyzer: CostAnalyzer) -> None:
    """quantity=0 → ValueError."""
    with pytest.raises(ValueError, match="quantity"):
        analyzer.analyze_order("O_BAD", "005930", 50_000.0, 50_000.0, 0)


def test_analyze_order_rejects_negative_quantity(analyzer: CostAnalyzer) -> None:
    """quantity<0 → ValueError."""
    with pytest.raises(ValueError, match="quantity"):
        analyzer.analyze_order("O_BAD", "005930", 50_000.0, 50_000.0, -1)


def test_analyze_order_rejects_zero_requested_price(analyzer: CostAnalyzer) -> None:
    """requested_price=0 → ValueError."""
    with pytest.raises(ValueError, match="requested_price"):
        analyzer.analyze_order("O_BAD", "005930", 0.0, 50_000.0, 10)


def test_analyze_order_rejects_negative_requested_price(analyzer: CostAnalyzer) -> None:
    """requested_price<0 → ValueError."""
    with pytest.raises(ValueError, match="requested_price"):
        analyzer.analyze_order("O_BAD", "005930", -100.0, 50_000.0, 10)


# ---------------------------------------------------------------------------
# since 필터 (H5 / C1)
# ---------------------------------------------------------------------------


def test_since_filter_excludes_old_records(analyzer: CostAnalyzer) -> None:
    """since 날짜 이전 기록은 집계에서 제외된다."""
    # 과거 타임스탬프를 가진 레코드를 직접 주입
    from src.cost_analyzer import TradeCost

    old_cost = TradeCost(
        order_id="OLD",
        symbol="005930",
        requested_price=50_000.0,
        fill_price=50_100.0,
        quantity=10,
        slippage=100.0,
        slippage_pct=0.002,
        commission=75.0,
        total_cost=1075.0,
        timestamp="2026-01-01T10:00:00",
    )
    analyzer._costs = [old_cost]

    # since=2026-03-01 → 1월 기록은 제외
    result = analyzer.get_cumulative_costs(since="2026-03-01")
    assert result["trade_count"] == 0
    assert result["total_cost"] == 0.0


def test_since_filter_includes_matching_records(analyzer: CostAnalyzer) -> None:
    """since 날짜 이후 기록은 집계에 포함된다."""
    from src.cost_analyzer import TradeCost

    recent_cost = TradeCost(
        order_id="NEW",
        symbol="005930",
        requested_price=50_000.0,
        fill_price=50_100.0,
        quantity=10,
        slippage=100.0,
        slippage_pct=0.002,
        commission=75.0,
        total_cost=1075.0,
        timestamp="2026-03-04T10:00:00",
    )
    analyzer._costs = [recent_cost]

    result = analyzer.get_cumulative_costs(since="2026-03-01")
    assert result["trade_count"] == 1
    assert result["total_cost"] == pytest.approx(1075.0)


def test_check_budget_limit_with_since_ignores_old_costs(analyzer: CostAnalyzer) -> None:
    """check_budget_limit(since=...) → 지정 날짜 이전 비용 무시."""
    from src.cost_analyzer import TradeCost

    old_cost = TradeCost(
        order_id="OLD_BIG",
        symbol="005930",
        requested_price=10_000.0,
        fill_price=10_500.0,
        quantity=10,
        slippage=500.0,
        slippage_pct=0.05,
        commission=15.75,
        total_cost=5015.75,  # 자산 임계(2000원)를 초과하는 금액
        timestamp="2026-01-01T10:00:00",
    )
    analyzer._costs = [old_cost]

    # since=2026-03-01 → 1월 기록 제외 → 비용 없음 → 임계 통과
    ok, reason = analyzer.check_budget_limit(
        total_equity=1_000_000.0,
        realized_profit=500_000.0,
        since="2026-03-01",
    )
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# quantity 필드 영속성 (H4)
# ---------------------------------------------------------------------------


def test_quantity_persisted_in_trade_cost(tmp_path: Path) -> None:
    """quantity 필드가 저장 후 재로드 시 보존된다."""
    log_path = tmp_path / "cost_log.json"

    a1 = CostAnalyzer(cost_log_path=log_path)
    a1.analyze_order("O1", "005930", 50_000.0, 50_100.0, 7)

    a2 = CostAnalyzer(cost_log_path=log_path)
    assert len(a2._costs) == 1
    assert a2._costs[0].quantity == 7


def test_from_dict_handles_missing_quantity() -> None:
    """구버전 레코드(quantity 없음) → quantity=0 기본값 처리."""
    from src.cost_analyzer import TradeCost

    d = {
        "order_id": "OLD",
        "symbol": "005930",
        "requested_price": 50_000.0,
        "fill_price": 50_100.0,
        "slippage": 100.0,
        "slippage_pct": 0.002,
        "commission": 75.0,
        "total_cost": 1075.0,
        "timestamp": "2026-01-01T10:00:00",
    }
    cost = TradeCost.from_dict(d)
    assert cost.quantity == 0
