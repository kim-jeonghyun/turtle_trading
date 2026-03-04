"""
포지션 동기화 검증 단위 테스트 (TDD)

KIS 잔고와 로컬 positions.json 비교 로직을 검증한다.
불일치 유형: missing_local, missing_broker, quantity_mismatch
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.position_sync import PositionSyncVerifier, SyncDiscrepancy


def _make_position(symbol: str, total_shares: int, **kwargs) -> SimpleNamespace:
    """테스트용 Position mock 생성."""
    return SimpleNamespace(
        position_id=kwargs.get("position_id", f"{symbol}_1_LONG_20260101_120000"),
        symbol=symbol,
        total_shares=total_shares,
        status="open",
    )


def _make_verifier(
    broker_positions: list[dict] | None = None,
    local_positions: list | None = None,
    api_exception: Exception | None = None,
) -> PositionSyncVerifier:
    """테스트용 PositionSyncVerifier 생성.

    Args:
        broker_positions: KIS get_balance() output1 형식의 포지션 리스트
        local_positions: PositionTracker.get_open_positions() 반환값
        api_exception: get_balance() 호출 시 발생시킬 예외
    """
    kis = AsyncMock()
    if api_exception:
        kis.get_balance.side_effect = api_exception
    else:
        balance = {"positions": broker_positions or [], "total_equity": 0, "cash": 0}
        kis.get_balance.return_value = balance

    tracker = MagicMock()
    tracker.get_open_positions.return_value = local_positions or []

    return PositionSyncVerifier(kis_client=kis, tracker=tracker)


class TestSyncNoDiscrepancy:
    """브로커와 로컬이 일치하는 경우"""

    def test_sync_no_discrepancy(self):
        """broker == local → 빈 리스트"""
        verifier = _make_verifier(
            broker_positions=[{"symbol": "005930", "quantity": 100, "name": "삼성전자"}],
            local_positions=[_make_position("005930.KS", 100)],
        )
        result = asyncio.run(verifier.verify())
        assert result == []

    def test_sync_empty_portfolio(self):
        """양쪽 모두 빈 포트폴리오 → 불일치 없음"""
        verifier = _make_verifier(
            broker_positions=[],
            local_positions=[],
        )
        result = asyncio.run(verifier.verify())
        assert result == []


class TestSyncDiscrepancies:
    """불일치 유형별 감지"""

    def test_sync_missing_local(self):
        """브로커에만 포지션 → missing_local"""
        verifier = _make_verifier(
            broker_positions=[{"symbol": "005930", "quantity": 100, "name": "삼성전자"}],
            local_positions=[],
        )
        result = asyncio.run(verifier.verify())
        assert len(result) == 1
        assert result[0].discrepancy_type == "missing_local"
        assert result[0].symbol == "005930"
        assert result[0].broker_quantity == 100
        assert result[0].local_quantity == 0

    def test_sync_missing_broker(self):
        """로컬에만 포지션 → missing_broker, is_critical=True"""
        verifier = _make_verifier(
            broker_positions=[],
            local_positions=[_make_position("005930.KS", 50)],
        )
        result = asyncio.run(verifier.verify())
        assert len(result) == 1
        assert result[0].discrepancy_type == "missing_broker"
        assert result[0].is_critical is True
        assert result[0].local_quantity == 50
        assert result[0].broker_quantity == 0

    def test_sync_quantity_mismatch(self):
        """수량 차이 → quantity_mismatch"""
        verifier = _make_verifier(
            broker_positions=[{"symbol": "005930", "quantity": 100, "name": "삼성전자"}],
            local_positions=[_make_position("005930.KS", 80)],
        )
        result = asyncio.run(verifier.verify())
        assert len(result) == 1
        assert result[0].discrepancy_type == "quantity_mismatch"
        assert result[0].broker_quantity == 100
        assert result[0].local_quantity == 80


class TestSyncMultiplePositions:
    """같은 종목 다중 포지션 합산"""

    def test_sync_multiple_positions_same_symbol(self):
        """같은 종목 2개 포지션 → total_shares 합산 후 비교"""
        verifier = _make_verifier(
            broker_positions=[{"symbol": "005930", "quantity": 150, "name": "삼성전자"}],
            local_positions=[
                _make_position("005930.KS", 100, position_id="pos_1"),
                _make_position("005930.KS", 50, position_id="pos_2"),
            ],
        )
        result = asyncio.run(verifier.verify())
        assert result == []  # 100 + 50 = 150 == broker 150


class TestSyncAPIFailure:
    """API 장애 시 Fail-Open 동작"""

    def test_sync_api_failure_fail_open(self):
        """API 예외 → 예외 전파 (스크립트에서 catch)"""
        verifier = _make_verifier(api_exception=RuntimeError("KIS API 장애"))
        with pytest.raises(RuntimeError, match="KIS API 장애"):
            asyncio.run(verifier.verify())

    def test_sync_api_empty_response_raises_error(self):
        """get_balance() → {} 반환 시 RuntimeError 발생 (false alert 방지)"""
        kis = AsyncMock()
        kis.get_balance.return_value = {}  # API 실패 시 빈 dict

        tracker = MagicMock()
        tracker.get_open_positions.return_value = [
            _make_position("005930.KS", 100)
        ]

        verifier = PositionSyncVerifier(kis_client=kis, tracker=tracker)
        with pytest.raises(RuntimeError, match="empty response"):
            asyncio.run(verifier.verify())

    @pytest.mark.asyncio
    async def test_empty_balance_raises_error(self):
        """get_balance()가 빈 dict 반환 시 RuntimeError 발생 (false alert 방지)"""
        mock_kis_client = AsyncMock()
        mock_kis_client.get_balance = AsyncMock(return_value={})

        mock_tracker = MagicMock()
        mock_tracker.get_open_positions.return_value = []

        verifier = PositionSyncVerifier(mock_kis_client, mock_tracker)

        with pytest.raises(RuntimeError, match="empty response"):
            await verifier.verify()


class TestSymbolNormalization:
    """KIS pdno(005930)와 로컬 symbol(005930.KS/.KQ) 정규화"""

    def test_sync_kr_symbol_normalization(self):
        """005930.KS (로컬) vs 005930 (KIS) → 일치"""
        verifier = _make_verifier(
            broker_positions=[{"symbol": "005930", "quantity": 100, "name": "삼성전자"}],
            local_positions=[_make_position("005930.KS", 100)],
        )
        result = asyncio.run(verifier.verify())
        assert result == []

    def test_sync_kq_symbol_normalization(self):
        """035720.KQ (로컬) vs 035720 (KIS) → 일치"""
        verifier = _make_verifier(
            broker_positions=[{"symbol": "035720", "quantity": 200, "name": "카카오"}],
            local_positions=[_make_position("035720.KQ", 200)],
        )
        result = asyncio.run(verifier.verify())
        assert result == []


class TestFormatReport:
    """보고서 포맷팅"""

    def test_format_report(self):
        """critical/non-critical 구분 표시"""
        verifier = _make_verifier()
        discrepancies = [
            SyncDiscrepancy(
                symbol="005930",
                discrepancy_type="missing_broker",
                local_quantity=50,
                broker_quantity=0,
                details="로컬 50주 추적 중, 브로커 잔고 없음 [CRITICAL]",
            ),
            SyncDiscrepancy(
                symbol="000660",
                discrepancy_type="missing_local",
                local_quantity=0,
                broker_quantity=100,
                details="브로커에 100주 보유, 로컬 추적 없음",
            ),
        ]
        report = verifier.format_report(discrepancies)
        assert "2건 불일치" in report
        assert "\U0001f534" in report  # 🔴 for critical (missing_broker)
        assert "\U0001f7e1" in report  # 🟡 for non-critical (missing_local)
        assert "005930" in report
        assert "000660" in report


class TestDiscrepancyIsCritical:
    """SyncDiscrepancy.is_critical 프로퍼티"""

    def test_discrepancy_is_critical(self):
        """missing_broker → is_critical=True, 나머지 → False"""
        missing_broker = SyncDiscrepancy(
            symbol="005930",
            discrepancy_type="missing_broker",
            local_quantity=50,
            broker_quantity=0,
            details="test",
        )
        assert missing_broker.is_critical is True

        missing_local = SyncDiscrepancy(
            symbol="005930",
            discrepancy_type="missing_local",
            local_quantity=0,
            broker_quantity=100,
            details="test",
        )
        assert missing_local.is_critical is False

        quantity_mismatch = SyncDiscrepancy(
            symbol="005930",
            discrepancy_type="quantity_mismatch",
            local_quantity=50,
            broker_quantity=100,
            details="test",
        )
        assert quantity_mismatch.is_critical is False
