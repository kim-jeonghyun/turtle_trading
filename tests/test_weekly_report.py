"""scripts/weekly_report.py 단위 테스트"""

from scripts.weekly_report import (
    format_performance_stats,
    get_weekly_performance_stats,
)
from src.position_tracker import Position
from src.types import Direction


def make_closed_position(
    symbol: str,
    pnl: float,
    exit_date: str,
    system: int = 1,
) -> Position:
    """테스트용 청산 Position 객체"""
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
        status="closed",
        last_update=exit_date,
        exit_date=exit_date,
        exit_price=100.0 + pnl / 10,
        exit_reason="exit_signal",
        pnl=pnl,
        pnl_pct=pnl / 1000,
        r_multiple=pnl / 40,
    )


class TestWeeklyPerformanceStats:
    def test_weekly_report_includes_performance_stats(self):
        """주간 성과 통계에 win_rate, avg_r, total_pnl, profit_factor 포함"""
        trades = [
            make_closed_position("SPY", 200.0, "2026-03-10"),
            make_closed_position("QQQ", -100.0, "2026-03-09"),
            make_closed_position("IWM", 150.0, "2026-03-08"),
        ]

        stats = get_weekly_performance_stats(trades)

        assert "win_rate" in stats
        assert "avg_r" in stats
        assert "total_pnl" in stats
        assert "profit_factor" in stats
        # 3건 중 2건 승리 = 2/3
        assert abs(stats["win_rate"] - 2 / 3) < 0.01
        assert stats["total_pnl"] == 250.0
        assert stats["profit_factor"] > 0

    def test_weekly_report_empty_trades(self):
        """거래가 없으면 모든 통계가 0"""
        stats = get_weekly_performance_stats([])

        assert stats["win_rate"] == 0.0
        assert stats["avg_r"] == 0.0
        assert stats["total_pnl"] == 0.0
        assert stats["profit_factor"] == 0.0


class TestFormatPerformanceStats:
    def test_format_with_data(self):
        """통계가 있으면 승률/R/PnL/PF 포맷"""
        stats = {
            "win_rate": 0.65,
            "avg_r": 1.5,
            "total_pnl": 2500.0,
            "profit_factor": 2.1,
        }
        result = format_performance_stats(stats)
        assert "65.0%" in result
        assert "1.50" in result
        assert "$+2,500" in result
        assert "2.10" in result

    def test_format_empty(self):
        """거래 없으면 '없음' 메시지"""
        stats = {"win_rate": 0, "avg_r": 0, "total_pnl": 0, "profit_factor": 0}
        result = format_performance_stats(stats)
        assert "청산 거래 없음" in result
