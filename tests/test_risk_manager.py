"""
risk_manager.py 단위 테스트
- 4개 리스크 제한 경계값 테스트
"""

import pytest
from src.risk_manager import (
    PortfolioRiskManager,
    RiskLimits,
    AssetGroup,
    Direction
)


@pytest.fixture
def risk_manager():
    symbol_groups = {
        'SPY': AssetGroup.US_EQUITY,
        'QQQ': AssetGroup.US_EQUITY,
        'AAPL': AssetGroup.US_EQUITY,
        'NVDA': AssetGroup.US_EQUITY,
        'TSLA': AssetGroup.US_EQUITY,
        'MSFT': AssetGroup.US_EQUITY,
        'AMZN': AssetGroup.US_EQUITY,
        '005930.KS': AssetGroup.KR_EQUITY,
        '000660.KS': AssetGroup.KR_EQUITY,
        'BTC-USD': AssetGroup.CRYPTO,
    }
    return PortfolioRiskManager(symbol_groups=symbol_groups)


class TestSingleMarketLimit:
    """단일 종목: 4 Units"""

    def test_within_limit(self, risk_manager):
        ok, msg = risk_manager.can_add_position('SPY', 3, 2.0, Direction.LONG)
        assert ok is True

    def test_at_limit(self, risk_manager):
        risk_manager.add_position('SPY', 3, 2.0, Direction.LONG)
        ok, msg = risk_manager.can_add_position('SPY', 1, 2.0, Direction.LONG)
        assert ok is True

    def test_exceeds_limit(self, risk_manager):
        risk_manager.add_position('SPY', 4, 2.0, Direction.LONG)
        ok, msg = risk_manager.can_add_position('SPY', 1, 2.0, Direction.LONG)
        assert ok is False
        assert "단일종목" in msg


class TestCorrelatedGroupLimit:
    """상관 그룹: 6 Units"""

    def test_within_group_limit(self, risk_manager):
        risk_manager.add_position('SPY', 3, 2.0, Direction.LONG)
        ok, msg = risk_manager.can_add_position('QQQ', 3, 2.0, Direction.LONG)
        assert ok is True

    def test_exceeds_group_limit(self, risk_manager):
        risk_manager.add_position('SPY', 3, 2.0, Direction.LONG)
        risk_manager.add_position('QQQ', 3, 2.0, Direction.LONG)
        ok, msg = risk_manager.can_add_position('AAPL', 1, 2.0, Direction.LONG)
        assert ok is False
        assert "그룹" in msg

    def test_different_groups_independent(self, risk_manager):
        risk_manager.add_position('SPY', 4, 2.0, Direction.LONG)
        # 다른 그룹은 영향 없음
        ok, msg = risk_manager.can_add_position('005930.KS', 4, 2.0, Direction.LONG)
        assert ok is True


class TestDirectionLimit:
    """단일 방향: 12 Units"""

    def test_within_direction_limit(self, risk_manager):
        """방향 한도 내 (총 9 units long, N 노출도 10 이하)"""
        risk_manager.add_position('SPY', 3, 2.0, Direction.LONG)
        risk_manager.add_position('005930.KS', 3, 2.0, Direction.LONG)
        risk_manager.add_position('BTC-USD', 3, 2.0, Direction.LONG)
        # 총 9 units long, N=9 (< 10), 각 그룹 3 (< 6)
        ok, msg = risk_manager.can_add_position('AAPL', 1, 2.0, Direction.LONG)
        # AAPL은 US_EQUITY 그룹에서 SPY(3)+AAPL(1)=4 < 6, 방향 10 < 12, N=10 <= 10
        assert ok is True

    def test_exceeds_direction_limit(self):
        """방향 한도 초과 테스트 (N 노출 한도를 높여 방향 한도만 테스트)"""
        symbol_groups = {
            'SPY': AssetGroup.US_EQUITY,
            'AAPL': AssetGroup.US_EQUITY,
            '005930.KS': AssetGroup.KR_EQUITY,
            '000660.KS': AssetGroup.KR_EQUITY,
            'BTC-USD': AssetGroup.CRYPTO,
            'ETH-USD': AssetGroup.CRYPTO,
        }
        limits = RiskLimits(
            max_units_per_market=4,
            max_units_correlated=6,
            max_units_direction=12,
            max_total_n_exposure=20.0  # N 한도를 높여서 방향 한도만 테스트
        )
        rm = PortfolioRiskManager(limits=limits, symbol_groups=symbol_groups)
        # 12 units long 추가 (각 그룹 4 units = 그룹 한도 내)
        rm.add_position('SPY', 4, 2.0, Direction.LONG)
        rm.add_position('005930.KS', 4, 2.0, Direction.LONG)
        rm.add_position('BTC-USD', 4, 2.0, Direction.LONG)
        ok, msg = rm.can_add_position('AAPL', 1, 2.0, Direction.LONG)
        # 방향 13 > 12 이므로 실패
        assert ok is False


class TestTotalNExposure:
    """전체 N 노출: <= 10"""

    def test_within_n_limit(self, risk_manager):
        risk_manager.add_position('SPY', 4, 2.0, Direction.LONG)
        risk_manager.add_position('005930.KS', 4, 2.0, Direction.LONG)
        ok, msg = risk_manager.can_add_position('BTC-USD', 2, 2.0, Direction.LONG)
        assert ok is True

    def test_exceeds_n_limit(self, risk_manager):
        risk_manager.add_position('SPY', 4, 2.0, Direction.LONG)
        risk_manager.add_position('005930.KS', 4, 2.0, Direction.LONG)
        risk_manager.add_position('BTC-USD', 2, 2.0, Direction.LONG)
        ok, msg = risk_manager.can_add_position('AAPL', 1, 2.0, Direction.LONG)
        # total would be 11 > 10
        assert ok is False


class TestRemovePosition:
    def test_remove_frees_capacity(self, risk_manager):
        risk_manager.add_position('SPY', 4, 2.0, Direction.LONG)
        risk_manager.remove_position('SPY', 4, Direction.LONG)
        ok, msg = risk_manager.can_add_position('SPY', 4, 2.0, Direction.LONG)
        assert ok is True

    def test_risk_summary(self, risk_manager):
        risk_manager.add_position('SPY', 3, 2.0, Direction.LONG)
        risk_manager.add_position('BTC-USD', 2, 3.0, Direction.SHORT)
        summary = risk_manager.get_risk_summary()
        assert summary['long_units'] == 3
        assert summary['short_units'] == 2
        assert summary['positions_count'] == 2
