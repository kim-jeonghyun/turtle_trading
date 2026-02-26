"""
risk_manager.py 단위 테스트
- 4개 리스크 제한 경계값 테스트
"""

import pytest

from src.risk_manager import (
    PortfolioRiskManager,
    RiskLimits,
)
from src.types import AssetGroup, Direction


@pytest.fixture
def risk_manager():
    symbol_groups = {
        "SPY": AssetGroup.US_EQUITY,
        "QQQ": AssetGroup.US_EQUITY,
        "AAPL": AssetGroup.US_EQUITY,
        "NVDA": AssetGroup.US_EQUITY,
        "TSLA": AssetGroup.US_EQUITY,
        "MSFT": AssetGroup.US_EQUITY,
        "AMZN": AssetGroup.US_EQUITY,
        "005930.KS": AssetGroup.KR_EQUITY,
        "000660.KS": AssetGroup.KR_EQUITY,
        "BTC-USD": AssetGroup.CRYPTO,
    }
    return PortfolioRiskManager(symbol_groups=symbol_groups)


class TestSingleMarketLimit:
    """단일 종목: 4 Units"""

    def test_within_limit(self, risk_manager):
        ok, msg = risk_manager.can_add_position("SPY", 3, 2.0, Direction.LONG)
        assert ok is True

    def test_at_limit(self, risk_manager):
        risk_manager.add_position("SPY", 3, 2.0, Direction.LONG)
        ok, msg = risk_manager.can_add_position("SPY", 1, 2.0, Direction.LONG)
        assert ok is True

    def test_exceeds_limit(self, risk_manager):
        risk_manager.add_position("SPY", 4, 2.0, Direction.LONG)
        ok, msg = risk_manager.can_add_position("SPY", 1, 2.0, Direction.LONG)
        assert ok is False
        assert "단일종목" in msg


class TestCorrelatedGroupLimit:
    """상관 그룹: 6 Units"""

    def test_within_group_limit(self, risk_manager):
        # SPY: 3 * 1.5 = 4.5 N exposure
        # QQQ: 3 * 1.5 = 4.5 N exposure
        # Total: 9.0 N exposure (< 10.0 limit)
        risk_manager.add_position("SPY", 3, 1.5, Direction.LONG)
        ok, msg = risk_manager.can_add_position("QQQ", 3, 1.5, Direction.LONG)
        assert ok is True

    def test_exceeds_group_limit(self, risk_manager):
        risk_manager.add_position("SPY", 3, 1.5, Direction.LONG)
        risk_manager.add_position("QQQ", 3, 1.5, Direction.LONG)
        ok, msg = risk_manager.can_add_position("AAPL", 1, 1.5, Direction.LONG)
        assert ok is False
        assert "그룹" in msg

    def test_different_groups_independent(self, risk_manager):
        # SPY: 4 * 1.0 = 4.0 N exposure
        # 005930.KS: 4 * 1.0 = 4.0 N exposure
        # Total: 8.0 N exposure (< 10.0 limit)
        risk_manager.add_position("SPY", 4, 1.0, Direction.LONG)
        # 다른 그룹은 영향 없음
        ok, msg = risk_manager.can_add_position("005930.KS", 4, 1.0, Direction.LONG)
        assert ok is True


class TestDirectionLimit:
    """단일 방향: 12 Units"""

    def test_within_direction_limit(self, risk_manager):
        """방향 한도 내 (총 9 units long, N 노출 = 9*1.0 = 9.0)"""
        # n_value를 1.0으로 낮춰서 N 노출이 방향 한도를 넘지 않도록
        risk_manager.add_position("SPY", 3, 1.0, Direction.LONG)
        risk_manager.add_position("005930.KS", 3, 1.0, Direction.LONG)
        risk_manager.add_position("BTC-USD", 3, 1.0, Direction.LONG)
        # 총 9 units long, N=9*1.0=9.0 (< 10), 각 그룹 3 (< 6)
        ok, msg = risk_manager.can_add_position("AAPL", 1, 1.0, Direction.LONG)
        # AAPL은 US_EQUITY 그룹에서 SPY(3)+AAPL(1)=4 < 6, 방향 10 < 12, N=9+1=10 <= 10
        assert ok is True

    def test_exceeds_direction_limit(self):
        """방향 한도 초과 테스트 (N 노출 한도를 높여 방향 한도만 테스트)"""
        symbol_groups = {
            "SPY": AssetGroup.US_EQUITY,
            "AAPL": AssetGroup.US_EQUITY,
            "005930.KS": AssetGroup.KR_EQUITY,
            "000660.KS": AssetGroup.KR_EQUITY,
            "BTC-USD": AssetGroup.CRYPTO,
            "ETH-USD": AssetGroup.CRYPTO,
        }
        limits = RiskLimits(
            max_units_per_market=4,
            max_units_correlated=6,
            max_units_direction=12,
            max_total_n_exposure=50.0,  # N 한도를 높여서 방향 한도만 테스트
        )
        rm = PortfolioRiskManager(limits=limits, symbol_groups=symbol_groups)
        # 12 units long 추가 (각 그룹 4 units = 그룹 한도 내)
        rm.add_position("SPY", 4, 1.0, Direction.LONG)
        rm.add_position("005930.KS", 4, 1.0, Direction.LONG)
        rm.add_position("BTC-USD", 4, 1.0, Direction.LONG)
        ok, msg = rm.can_add_position("AAPL", 1, 1.0, Direction.LONG)
        # 방향 13 > 12 이므로 실패
        assert ok is False


class TestTotalNExposure:
    """전체 N 노출: <= 10"""

    def test_within_n_limit(self, risk_manager):
        # N exposure = n_value * units
        # SPY: 2.0 * 2 = 4.0
        # 005930.KS: 2.0 * 2 = 4.0
        # Total so far: 8.0
        risk_manager.add_position("SPY", 2, 2.0, Direction.LONG)
        risk_manager.add_position("005930.KS", 2, 2.0, Direction.LONG)
        # BTC-USD: 2.0 * 1 = 2.0, total would be 10.0 (exactly at limit)
        ok, msg = risk_manager.can_add_position("BTC-USD", 1, 2.0, Direction.LONG)
        assert ok is True

    def test_exceeds_n_limit(self, risk_manager):
        # SPY: 2.5 * 2 = 5.0
        # 005930.KS: 2.5 * 2 = 5.0
        # Total so far: 10.0 (at limit)
        risk_manager.add_position("SPY", 2, 2.5, Direction.LONG)
        risk_manager.add_position("005930.KS", 2, 2.5, Direction.LONG)
        # BTC-USD: 2.0 * 1 = 2.0, total would be 12.0 > 10.0
        ok, msg = risk_manager.can_add_position("BTC-USD", 1, 2.0, Direction.LONG)
        assert ok is False
        assert "N 노출" in msg


class TestRemovePosition:
    def test_remove_frees_capacity(self, risk_manager):
        risk_manager.add_position("SPY", 4, 2.0, Direction.LONG)
        risk_manager.remove_position("SPY", 4, Direction.LONG, n_value=2.0)
        ok, msg = risk_manager.can_add_position("SPY", 4, 2.0, Direction.LONG)
        assert ok is True

    def test_remove_short_position(self, risk_manager):
        """SHORT 포지션 제거 시 short_units 및 N 노출이 감소해야 한다 (line 101)"""
        risk_manager.add_position("BTC-USD", 2, 3.0, Direction.SHORT)
        assert risk_manager.state.short_units == 2
        risk_manager.remove_position("BTC-USD", 2, Direction.SHORT, n_value=3.0)
        assert risk_manager.state.short_units == 0
        assert risk_manager.state.total_n_exposure == 0.0

    def test_remove_position_verifies_all_state_fields(self, risk_manager):
        """remove_position 후 모든 상태 필드가 올바르게 감소해야 한다"""
        group = AssetGroup.US_EQUITY  # SPY의 그룹
        risk_manager.add_position("SPY", 3, 2.0, Direction.LONG)

        # 사전 상태 확인
        assert risk_manager.state.units_by_symbol["SPY"] == 3
        assert risk_manager.state.units_by_group[group] == 3
        assert risk_manager.state.long_units == 3
        assert risk_manager.state.total_n_exposure == 6.0

        risk_manager.remove_position("SPY", 2, Direction.LONG, n_value=2.0)

        # 모든 필드가 올바르게 감소했는지 검증
        assert risk_manager.state.units_by_symbol["SPY"] == 1
        assert risk_manager.state.units_by_group[group] == 1
        assert risk_manager.state.long_units == 1
        assert risk_manager.state.total_n_exposure == pytest.approx(2.0)

    def test_remove_position_underflow_guard(self, risk_manager):
        """추가한 수량보다 많은 수량을 제거해도 모든 상태 필드가 0으로 바닥 처리된다"""
        group = AssetGroup.US_EQUITY  # SPY의 그룹
        risk_manager.add_position("SPY", 2, 1.5, Direction.LONG)

        # 추가한 2 units보다 더 많은 5 units 제거 시도
        risk_manager.remove_position("SPY", 5, Direction.LONG, n_value=1.5)

        # 음수가 아닌 0으로 바닥 처리되어야 한다
        assert risk_manager.state.units_by_symbol["SPY"] == 0
        assert risk_manager.state.units_by_group[group] == 0
        assert risk_manager.state.long_units == 0
        assert risk_manager.state.total_n_exposure == 0.0

    def test_risk_summary(self, risk_manager):
        # SPY: 3 units * 2.0 N = 6.0 N exposure
        # BTC-USD: 2 units * 3.0 N = 6.0 N exposure
        # Total N exposure: 12.0
        risk_manager.add_position("SPY", 3, 2.0, Direction.LONG)
        risk_manager.add_position("BTC-USD", 2, 3.0, Direction.SHORT)
        summary = risk_manager.get_risk_summary()
        assert summary["long_units"] == 3
        assert summary["short_units"] == 2
        assert summary["positions_count"] == 2
        assert summary["total_n_exposure"] == 12.0


class TestInputValidation:
    """유효하지 않은 입력에 대한 검증 (lines 43, 45, 76, 78)"""

    def test_can_add_position_negative_n_value(self, risk_manager):
        """can_add_position: n_value가 음수이면 False 반환 (line 43)"""
        ok, msg = risk_manager.can_add_position("SPY", 1, -1.0, Direction.LONG)
        assert ok is False
        assert "음수" in msg

    def test_can_add_position_zero_units(self, risk_manager):
        """can_add_position: units가 0이면 False 반환 (line 45)"""
        ok, msg = risk_manager.can_add_position("SPY", 0, 2.0, Direction.LONG)
        assert ok is False
        assert "0 이하" in msg

    def test_can_add_position_negative_units(self, risk_manager):
        """can_add_position: units가 음수이면 False 반환 (line 45)"""
        ok, msg = risk_manager.can_add_position("SPY", -1, 2.0, Direction.LONG)
        assert ok is False
        assert "0 이하" in msg

    def test_add_position_negative_n_value_raises(self, risk_manager):
        """add_position: n_value가 음수이면 ValueError 발생 (line 76)"""
        with pytest.raises(ValueError, match="n_value must be non-negative"):
            risk_manager.add_position("SPY", 1, -0.5, Direction.LONG)

    def test_add_position_zero_units_raises(self, risk_manager):
        """add_position: units가 0이면 ValueError 발생 (line 78)"""
        with pytest.raises(ValueError, match="units must be positive"):
            risk_manager.add_position("SPY", 0, 2.0, Direction.LONG)

    def test_add_position_negative_units_raises(self, risk_manager):
        """add_position: units가 음수이면 ValueError 발생 (line 78)"""
        with pytest.raises(ValueError, match="units must be positive"):
            risk_manager.add_position("SPY", -2, 2.0, Direction.LONG)

    def test_add_position_raises_no_state_mutation(self, risk_manager):
        """add_position이 ValueError를 발생시킨 후 상태가 전혀 변경되지 않아야 한다 (원자성 보장)"""
        group = AssetGroup.US_EQUITY  # SPY의 그룹

        # 사전에 유효한 포지션 하나 추가해 초기 상태를 비어있지 않게 설정
        risk_manager.add_position("SPY", 1, 1.0, Direction.LONG)

        # 변경 전 상태 스냅샷
        prev_symbol_units = risk_manager.state.units_by_symbol.get("SPY", 0)
        prev_group_units = risk_manager.state.units_by_group.get(group, 0)
        prev_long_units = risk_manager.state.long_units
        prev_short_units = risk_manager.state.short_units
        prev_n_exposure = risk_manager.state.total_n_exposure

        # 음수 n_value로 ValueError 유발
        with pytest.raises(ValueError):
            risk_manager.add_position("SPY", 1, -0.5, Direction.LONG)

        # 예외 발생 후 상태가 변경되지 않았는지 검증
        assert risk_manager.state.units_by_symbol.get("SPY", 0) == prev_symbol_units
        assert risk_manager.state.units_by_group.get(group, 0) == prev_group_units
        assert risk_manager.state.long_units == prev_long_units
        assert risk_manager.state.short_units == prev_short_units
        assert risk_manager.state.total_n_exposure == pytest.approx(prev_n_exposure)


class TestShortDirectionLimit:
    """숏 방향 한도: 12 Units (lines 64-65)"""

    def test_exceeds_short_direction_limit(self):
        """숏 방향 한도 초과 시 False 반환 (lines 64-65)"""
        symbol_groups = {
            "SPY": AssetGroup.US_EQUITY,
            "005930.KS": AssetGroup.KR_EQUITY,
            "BTC-USD": AssetGroup.CRYPTO,
            "AAPL": AssetGroup.US_EQUITY,
        }
        limits = RiskLimits(
            max_units_per_market=4,
            max_units_correlated=6,
            max_units_direction=12,
            max_total_n_exposure=50.0,
        )
        rm = PortfolioRiskManager(limits=limits, symbol_groups=symbol_groups)
        # 12 units short 추가 (각 그룹 4 units = 그룹 한도 내)
        rm.add_position("SPY", 4, 1.0, Direction.SHORT)
        rm.add_position("005930.KS", 4, 1.0, Direction.SHORT)
        rm.add_position("BTC-USD", 4, 1.0, Direction.SHORT)
        ok, msg = rm.can_add_position("AAPL", 1, 1.0, Direction.SHORT)
        assert ok is False
        assert "숏" in msg

    def test_within_short_direction_limit(self, risk_manager):
        """숏 방향 한도 내에서 포지션 추가 허용"""
        risk_manager.add_position("BTC-USD", 2, 1.0, Direction.SHORT)
        ok, msg = risk_manager.can_add_position("005930.KS", 2, 1.0, Direction.SHORT)
        assert ok is True
