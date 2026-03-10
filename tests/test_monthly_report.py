"""monthly_report.py 단위 테스트"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.monthly_report import (
    filter_trades_for_month,
    format_report,
    generate_report,
    get_month_boundaries,
    get_per_symbol_pnl,
    get_previous_month,
    parse_month,
)
from src.position_tracker import Direction, Position

# ── 헬퍼 ────────────────────────────────────────────────────────────────────


def make_position(
    symbol: str,
    pnl: float,
    exit_date: str,
    system: int = 1,
    status: str = "closed",
) -> Position:
    """테스트용 Position 객체 생성"""
    return Position(
        position_id=f"{symbol}_{exit_date}",
        symbol=symbol,
        system=system,
        direction=Direction.LONG,
        entry_date="2026-01-01",
        entry_price=100.0,
        entry_n=2.0,
        units=1,
        max_units=4,
        shares_per_unit=10,
        total_shares=10,
        stop_loss=96.0,
        pyramid_level=0,
        exit_period=10,
        status=status,
        last_update=exit_date,
        exit_date=exit_date,
        exit_price=100.0 + pnl / 10,
        exit_reason="stop",
        pnl=pnl,
        pnl_pct=pnl / 1000,
        r_multiple=pnl / 20,
    )


def make_mock_tracker(positions: list) -> MagicMock:
    tracker = MagicMock()
    tracker.get_all_positions.return_value = positions
    return tracker


def make_mock_data_store() -> MagicMock:
    return MagicMock()


# ── test_parse_month_default ─────────────────────────────────────────────────


def test_parse_month_default():
    """--month 미지정 시 이전 달 반환"""
    result = get_previous_month()
    year, month = parse_month(result)

    today = datetime.now()
    expected_month = today.month - 1 if today.month > 1 else 12
    expected_year = today.year if today.month > 1 else today.year - 1

    assert month == expected_month
    assert year == expected_year


def test_parse_month_january_wraps_to_december():
    """1월일 때 이전 달은 작년 12월"""
    with patch("scripts.monthly_report.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 1, 15)
        mock_dt.strptime = datetime.strptime
        result = get_previous_month()
    assert result == "2025-12"


# ── test_parse_month_explicit ─────────────────────────────────────────────────


def test_parse_month_explicit():
    """--month 2026-02 → 올바른 파싱"""
    year, month = parse_month("2026-02")
    assert year == 2026
    assert month == 2


def test_parse_month_invalid_raises():
    """잘못된 형식은 ValueError"""
    with pytest.raises(ValueError):
        parse_month("2026/02")


def test_parse_month_invalid_date_raises():
    """존재하지 않는 달은 ValueError"""
    with pytest.raises(ValueError):
        parse_month("2026-13")


# ── test_generate_report_with_trades ────────────────────────────────────────


def test_generate_report_with_trades():
    """거래가 있을 때 리포트 딕셔너리에 필수 키 존재"""
    positions = [
        make_position("SPY", 500.0, "2026-02-10"),
        make_position("QQQ", -200.0, "2026-02-15"),
        make_position("GLD", 300.0, "2026-02-20", system=2),
    ]
    tracker = make_mock_tracker(positions)
    data_store = make_mock_data_store()

    report = generate_report("2026-02", tracker, data_store)

    assert report["month"] == "2026-02"
    assert report["trade_count"] == 3
    assert "total_pnl" in report
    assert "win_rate" in report
    assert "profit_factor" in report
    assert "r_distribution" in report
    assert "system_comparison" in report
    assert "drawdown_info" in report
    assert "top5_symbols" in report
    assert "bottom5_symbols" in report
    assert "prev_month" in report
    assert "mom_change_pct" in report

    assert report["total_pnl"] == pytest.approx(600.0, rel=1e-3)
    assert 0.0 <= report["win_rate"] <= 1.0


# ── test_generate_report_empty_month ────────────────────────────────────────


def test_generate_report_empty_month():
    """해당 월 거래 없을 때 제로값으로 에러 없이 처리"""
    tracker = make_mock_tracker([])
    data_store = make_mock_data_store()

    report = generate_report("2026-02", tracker, data_store)

    assert report["trade_count"] == 0
    assert report["total_pnl"] == 0.0
    assert report["win_rate"] == 0.0
    assert report["profit_factor"] == 0.0
    assert report["top5_symbols"] == []
    assert report["bottom5_symbols"] == []
    # ZeroDivisionError 없이 처리 — mom_change_pct은 None
    assert report["mom_change_pct"] is None


# ── test_format_report_contains_sections ─────────────────────────────────────


def test_format_report_contains_sections():
    """포맷된 문자열에 필수 섹션 포함"""
    positions = [
        make_position("SPY", 400.0, "2026-02-05"),
        make_position("GLD", -100.0, "2026-02-10"),
    ]
    tracker = make_mock_tracker(positions)
    data_store = make_mock_data_store()

    report = generate_report("2026-02", tracker, data_store)
    text = format_report(report)

    assert "월별 수익률" in text
    assert "승률" in text
    assert "최대 낙폭" in text
    assert "전략 기여도" in text
    assert "심볼별 손익" in text
    assert "R-배수 분포" in text
    assert "2026-02" in text


def test_format_report_empty_shows_no_data():
    """빈 리포트가 에러 없이 포맷되고 '없음' 안내 포함"""
    tracker = make_mock_tracker([])
    data_store = make_mock_data_store()

    report = generate_report("2026-02", tracker, data_store)
    text = format_report(report)

    assert "2026-02" in text
    assert "청산 거래 없음" in text or "데이터 없음" in text


# ── test_month_boundary_filtering ───────────────────────────────────────────


def test_month_boundary_filtering_includes_first_and_last_day():
    """월 경계(첫날·마지막날) 거래 포함"""
    positions = [
        make_position("A", 100.0, "2026-02-01"),  # 첫날 — 포함
        make_position("B", 200.0, "2026-02-28"),  # 마지막날 — 포함
        make_position("C", 300.0, "2026-01-31"),  # 전달 — 제외
        make_position("D", 400.0, "2026-03-01"),  # 다음달 — 제외
    ]
    tracker = make_mock_tracker(positions)

    trades = filter_trades_for_month(tracker, "2026-02")

    symbols = [t["symbol"] for t in trades]
    assert "A" in symbols
    assert "B" in symbols
    assert "C" not in symbols
    assert "D" not in symbols
    assert len(trades) == 2


def test_month_boundary_open_positions_excluded():
    """open 상태 포지션은 청산 날짜가 있어도 제외"""
    positions = [
        make_position("X", 500.0, "2026-02-15", status="open"),
    ]
    tracker = make_mock_tracker(positions)

    trades = filter_trades_for_month(tracker, "2026-02")
    assert len(trades) == 0


def test_get_per_symbol_pnl_aggregates():
    """같은 심볼의 여러 거래 합산"""
    trades = [
        {"symbol": "SPY", "pnl": 100.0},
        {"symbol": "SPY", "pnl": 200.0},
        {"symbol": "GLD", "pnl": -50.0},
    ]
    result = get_per_symbol_pnl(trades)
    assert result["SPY"] == pytest.approx(300.0)
    assert result["GLD"] == pytest.approx(-50.0)


def test_get_month_boundaries():
    """월 경계 계산 검증"""
    from datetime import date

    first, last = get_month_boundaries("2026-02")
    assert first == date(2026, 2, 1)
    assert last == date(2026, 2, 28)

    first_dec, last_dec = get_month_boundaries("2025-12")
    assert first_dec == date(2025, 12, 1)
    assert last_dec == date(2025, 12, 31)
