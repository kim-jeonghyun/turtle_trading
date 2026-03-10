"""
check_positions.py 이상 거래 감지 흐름 통합 테스트

검증 항목:
- closed position → trade dict 직렬화 정확성
- 30일 룩백 필터링 (M4 fix)
- detect_anomalies + send_anomaly_alert 흐름
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.analytics import detect_anomalies
from src.position_tracker import Direction, Position


def _make_position(symbol: str, exit_date: str, pnl: float = 500.0, status: str = "closed") -> Position:
    """테스트용 Position 객체 생성"""
    return Position(
        position_id=f"{symbol}_{exit_date}",
        symbol=symbol,
        system=1,
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


def _serialize_and_filter(positions, lookback_days=30):
    """check_positions.py 섹션 5의 직렬화/필터링 로직 재현"""
    lookback_cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    closed = [
        p for p in positions if p.status == "closed" and p.exit_date and p.exit_date >= lookback_cutoff
    ]
    trade_dicts = []
    for p in closed:
        trade_dicts.append(
            {
                "symbol": p.symbol,
                "system": p.system,
                "direction": p.direction.value if hasattr(p.direction, "value") else p.direction,
                "entry_price": p.entry_price,
                "exit_price": p.exit_price,
                "stop_loss": p.stop_loss,
                "total_shares": p.total_shares,
                "pnl": p.pnl,
                "exit_date": p.exit_date,
            }
        )
    return trade_dicts


class TestAnomalyDetectionFlow:
    def test_closed_positions_serialized_correctly(self):
        """closed position → trade dict 직렬화가 정확하다"""
        recent = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        pos = _make_position("SPY", recent, pnl=500.0)
        result = _serialize_and_filter([pos])

        assert len(result) == 1
        assert result[0]["symbol"] == "SPY"
        assert result[0]["direction"] == "LONG"
        assert result[0]["pnl"] == 500.0
        assert result[0]["stop_loss"] == 96.0

    def test_old_positions_filtered_out(self):
        """exit_date가 30일 초과인 포지션은 필터링된다"""
        old_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        recent_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

        positions = [
            _make_position("GLD", old_date, pnl=-5000.0),
            _make_position("SPY", recent_date, pnl=200.0),
        ]
        result = _serialize_and_filter(positions)

        assert len(result) == 1
        assert result[0]["symbol"] == "SPY"

    def test_open_positions_excluded(self):
        """status='open'인 포지션은 제외된다"""
        recent = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        pos = _make_position("QQQ", recent, status="open")
        result = _serialize_and_filter([pos])

        assert len(result) == 0

    def test_detect_anomalies_with_large_loss(self):
        """큰 손실 포지션은 이상 거래로 감지된다"""
        recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        pos = _make_position("SPY", recent, pnl=-15000.0)
        trade_dicts = _serialize_and_filter([pos])

        anomalies = detect_anomalies(trade_dicts, account_equity=100000.0)
        assert len(anomalies) > 0

    def test_no_anomalies_with_normal_trades(self):
        """정상 거래는 이상 거래로 감지되지 않는다"""
        recent = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        pos = _make_position("GLD", recent, pnl=200.0)
        trade_dicts = _serialize_and_filter([pos])

        anomalies = detect_anomalies(trade_dicts, account_equity=100000.0)
        assert len(anomalies) == 0

    @pytest.mark.asyncio
    async def test_anomaly_alert_sent_when_detected(self):
        """이상 거래 감지 → notifier.send_anomaly_alert() 호출"""
        notifier = MagicMock()
        notifier.send_anomaly_alert = AsyncMock(return_value={})

        recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        positions = [_make_position("SPY", recent, pnl=-15000.0)]
        trade_dicts = _serialize_and_filter(positions)
        anomalies = detect_anomalies(trade_dicts, account_equity=100000.0)

        if anomalies:
            await notifier.send_anomaly_alert(anomalies)

        notifier.send_anomaly_alert.assert_awaited_once()
