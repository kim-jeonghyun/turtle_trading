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
        "AAPL": AssetGroup.US_TECH,
        "NVDA": AssetGroup.US_TECH,
        "TSLA": AssetGroup.US_TECH,
        "MSFT": AssetGroup.US_TECH,
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
        # AMZN is US_EQUITY (same group as SPY/QQQ) → 6+1=7 > 6 group limit
        ok, msg = risk_manager.can_add_position("AMZN", 1, 1.5, Direction.LONG)
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
        # AAPL은 US_TECH 그룹에서 AAPL(1) < 6, 방향 10 < 12, N=9+1=10 <= 10
        assert ok is True

    def test_exceeds_direction_limit(self):
        """방향 한도 초과 테스트 (N 노출 한도를 높여 방향 한도만 테스트)"""
        symbol_groups = {
            "SPY": AssetGroup.US_EQUITY,
            "AAPL": AssetGroup.US_TECH,
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

    def test_remove_overremoval_preserves_other_symbols(self, risk_manager):
        """한 종목을 과다 제거해도 다른 종목의 공유 상태 기여분이 보존된다"""
        group = AssetGroup.US_EQUITY
        risk_manager.add_position("SPY", 2, 1.5, Direction.LONG)
        risk_manager.add_position("QQQ", 2, 1.5, Direction.LONG)

        risk_manager.remove_position("SPY", 5, Direction.LONG, n_value=1.5)

        assert risk_manager.state.units_by_symbol["SPY"] == 0
        assert risk_manager.state.units_by_symbol["QQQ"] == 2
        assert risk_manager.state.units_by_group[group] == 2
        assert risk_manager.state.long_units == 2
        assert risk_manager.state.total_n_exposure == pytest.approx(3.0)

    def test_remove_overremoval_cross_group_isolation(self, risk_manager):
        """과다 제거 시 다른 그룹의 units_by_group은 영향 없음"""
        risk_manager.add_position("SPY", 2, 1.0, Direction.LONG)
        risk_manager.add_position("005930.KS", 2, 1.0, Direction.LONG)

        risk_manager.remove_position("SPY", 5, Direction.LONG, n_value=1.0)

        assert risk_manager.state.units_by_group[AssetGroup.US_EQUITY] == 0
        assert risk_manager.state.units_by_group[AssetGroup.KR_EQUITY] == 2
        assert risk_manager.state.long_units == 2
        assert risk_manager.state.total_n_exposure == pytest.approx(2.0)

    def test_remove_nonexistent_symbol_is_noop(self, risk_manager):
        """보유하지 않은 종목을 제거해도 상태가 변하지 않는다"""
        risk_manager.add_position("SPY", 2, 1.5, Direction.LONG)

        risk_manager.remove_position("AAPL", 3, Direction.LONG, n_value=1.5)

        assert risk_manager.state.units_by_symbol.get("AAPL", 0) == 0
        assert risk_manager.state.units_by_symbol["SPY"] == 2
        assert risk_manager.state.long_units == 2
        assert risk_manager.state.total_n_exposure == pytest.approx(3.0)

    def test_remove_double_removal_second_is_noop(self, risk_manager):
        """이미 제거된 포지션을 다시 제거해도 상태가 변하지 않는다"""
        risk_manager.add_position("SPY", 2, 1.5, Direction.LONG)

        risk_manager.remove_position("SPY", 2, Direction.LONG, n_value=1.5)
        assert risk_manager.state.units_by_symbol["SPY"] == 0
        assert risk_manager.state.total_n_exposure == pytest.approx(0.0)

        risk_manager.remove_position("SPY", 2, Direction.LONG, n_value=1.5)
        assert risk_manager.state.units_by_symbol["SPY"] == 0
        assert risk_manager.state.long_units == 0
        assert risk_manager.state.total_n_exposure == pytest.approx(0.0)

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

    def test_remove_position_negative_units_raises(self, risk_manager):
        """remove_position: units가 음수이면 ValueError 발생"""
        risk_manager.add_position("SPY", 2, 1.5, Direction.LONG)
        with pytest.raises(ValueError, match="units must be positive"):
            risk_manager.remove_position("SPY", -1, Direction.LONG, n_value=1.5)

    def test_remove_position_negative_n_value_raises(self, risk_manager):
        """remove_position: n_value가 음수이면 ValueError 발생"""
        risk_manager.add_position("SPY", 2, 1.5, Direction.LONG)
        with pytest.raises(ValueError, match="n_value must be non-negative"):
            risk_manager.remove_position("SPY", 1, Direction.LONG, n_value=-1.0)

    def test_remove_position_zero_units_raises(self, risk_manager):
        """remove_position: units가 0이면 ValueError 발생 (add_position 대칭)"""
        risk_manager.add_position("SPY", 2, 1.5, Direction.LONG)
        with pytest.raises(ValueError, match="units must be positive"):
            risk_manager.remove_position("SPY", 0, Direction.LONG, n_value=1.5)

    def test_remove_position_raises_no_state_mutation(self, risk_manager):
        """remove_position이 ValueError 발생 시 상태가 변경되지 않아야 한다 (원자성 보장)"""
        risk_manager.add_position("SPY", 2, 1.5, Direction.LONG)

        prev_symbol = risk_manager.state.units_by_symbol.get("SPY", 0)
        prev_long = risk_manager.state.long_units
        prev_n = risk_manager.state.total_n_exposure

        with pytest.raises(ValueError):
            risk_manager.remove_position("SPY", -1, Direction.LONG, n_value=1.5)

        assert risk_manager.state.units_by_symbol.get("SPY", 0) == prev_symbol
        assert risk_manager.state.long_units == prev_long
        assert risk_manager.state.total_n_exposure == pytest.approx(prev_n)


class TestExpandedUniverseRiskLimits:
    """확장 유니버스의 상관군 한도 검증"""

    def test_independent_groups_have_separate_limits(self):
        """비상관 자산군은 독립적 한도를 가진다"""
        symbol_groups = {
            "SPY": AssetGroup.US_EQUITY,
            "EWJ": AssetGroup.ASIA_EQUITY,
            "MCHI": AssetGroup.CHINA_EQUITY,
            "VGK": AssetGroup.EU_EQUITY,
            "USO": AssetGroup.COMMODITY_ENERGY,
            "DBA": AssetGroup.COMMODITY_AGRI,
            "VNQ": AssetGroup.REIT,
            "DBMF": AssetGroup.ALTERNATIVES,
            "BITO": AssetGroup.CRYPTO,
            "UUP": AssetGroup.CURRENCY,
        }
        rm = PortfolioRiskManager(symbol_groups=symbol_groups)

        for symbol in symbol_groups:
            ok, msg = rm.can_add_position(symbol, 1, 0.5, Direction.LONG)
            assert ok, f"{symbol} should be allowed: {msg}"
            rm.add_position(symbol, 1, 0.5, Direction.LONG)

        assert rm.state.long_units == 10

    def test_correlated_group_limit_enforced(self):
        """같은 상관군 내 종목은 6 unit 한도 공유"""
        symbol_groups = {
            "EWJ": AssetGroup.ASIA_EQUITY,
            "EWT": AssetGroup.ASIA_EQUITY,
            "EWA": AssetGroup.ASIA_EQUITY,
            "VNM": AssetGroup.ASIA_EQUITY,
            "EEM": AssetGroup.ASIA_EQUITY,
            "INDA": AssetGroup.ASIA_EQUITY,
        }
        rm = PortfolioRiskManager(symbol_groups=symbol_groups)

        for sym in list(symbol_groups.keys())[:6]:
            rm.add_position(sym, 1, 0.1, Direction.LONG)

        ok, msg = rm.can_add_position("EWJ", 1, 0.1, Direction.LONG)
        assert not ok
        assert "그룹" in msg

    def test_n_exposure_cap_with_many_groups(self):
        """N-exposure 10.0 캡은 다수 그룹에서도 작동"""
        symbol_groups = {
            "SPY": AssetGroup.US_EQUITY,
            "EWJ": AssetGroup.ASIA_EQUITY,
            "GLD": AssetGroup.COMMODITY,
            "TLT": AssetGroup.BOND,
            "VNQ": AssetGroup.REIT,
        }
        rm = PortfolioRiskManager(symbol_groups=symbol_groups)

        # 4 symbols × 1 unit × n_value=2.5 = 10.0 → exactly at limit
        for sym in list(symbol_groups.keys())[:4]:
            rm.add_position(sym, 1, 2.5, Direction.LONG)

        # 5th would exceed N-exposure
        ok, msg = rm.can_add_position("VNQ", 1, 2.5, Direction.LONG)
        assert not ok
        assert "N 노출" in msg


class TestSingleSymbolGroupBoundary:
    """단일 심볼 그룹(VGK, COPX 등)에서 per-market 4유닛 한도와 그룹 6유닛 한도 상호작용"""

    def test_single_symbol_group_capped_at_market_limit(self):
        """단일 심볼 그룹에서는 per-market 4유닛이 그룹 6유닛보다 먼저 제한"""
        symbol_groups = {"VGK": AssetGroup.EU_EQUITY}
        rm = PortfolioRiskManager(symbol_groups=symbol_groups)

        for _ in range(4):
            rm.add_position("VGK", 1, 0.5, Direction.LONG)

        # 5th unit blocked by per-market limit (4), not group limit (6)
        ok, msg = rm.can_add_position("VGK", 1, 0.5, Direction.LONG)
        assert not ok
        assert "단일종목" in msg

    def test_multi_symbol_group_reaches_group_limit(self):
        """다중 심볼 그룹에서 개별 종목은 4유닛 이내지만 그룹 합계 6유닛 초과"""
        symbol_groups = {
            "USO": AssetGroup.COMMODITY_ENERGY,
            "UNG": AssetGroup.COMMODITY_ENERGY,
        }
        rm = PortfolioRiskManager(symbol_groups=symbol_groups)

        rm.add_position("USO", 4, 0.5, Direction.LONG)  # 4 units (at market limit)
        rm.add_position("UNG", 2, 0.5, Direction.LONG)  # 2 units (group total: 6)

        # USO already at per-market limit
        ok, msg = rm.can_add_position("USO", 1, 0.5, Direction.LONG)
        assert not ok
        assert "단일종목" in msg

        # UNG blocked by group limit (6 total)
        ok, msg = rm.can_add_position("UNG", 1, 0.5, Direction.LONG)
        assert not ok
        assert "그룹" in msg

    def test_direction_limit_binds_across_many_single_symbol_groups(self):
        """다수 단일 심볼 그룹 동시 시그널 시 12유닛 방향 한도 도달"""
        symbol_groups = {
            "VGK": AssetGroup.EU_EQUITY,
            "COPX": AssetGroup.COMMODITY,
            "DBA": AssetGroup.COMMODITY_AGRI,
            "VNQ": AssetGroup.REIT,
            "DBMF": AssetGroup.ALTERNATIVES,
        }
        limits = RiskLimits(max_total_n_exposure=50.0)  # relax N cap
        rm = PortfolioRiskManager(limits=limits, symbol_groups=symbol_groups)

        # 5 symbols × 2 units = 10 long units
        for sym in symbol_groups:
            rm.add_position(sym, 2, 0.1, Direction.LONG)

        assert rm.state.long_units == 10

        # Add 2 more → 12 (at direction limit)
        rm.add_position("VGK", 2, 0.1, Direction.LONG)  # VGK: 4 (at market limit)
        assert rm.state.long_units == 12

        # 13th unit blocked by direction limit
        ok, msg = rm.can_add_position("COPX", 1, 0.1, Direction.LONG)
        assert not ok
        assert "롱" in msg


class TestRealConfigGroupMapping:
    """실제 correlation_groups.yaml → setup_risk_manager() 매핑 통합 검증"""

    def test_representative_symbols_mapped_correctly(self):
        """대표 심볼들이 실제 config 로드 시 기대 AssetGroup으로 매핑되는지 검증"""
        from src.script_helpers import setup_risk_manager

        rm = setup_risk_manager()

        expected = {
            "SPY": AssetGroup.US_EQUITY,
            "AAPL": AssetGroup.US_TECH,
            "EWJ": AssetGroup.ASIA_EQUITY,
            "MCHI": AssetGroup.CHINA_EQUITY,
            "VGK": AssetGroup.EU_EQUITY,
            "USO": AssetGroup.COMMODITY_ENERGY,
            "DBA": AssetGroup.COMMODITY_AGRI,
            "UUP": AssetGroup.CURRENCY,
            "VNQ": AssetGroup.REIT,
            "DBMF": AssetGroup.ALTERNATIVES,
            "BITO": AssetGroup.CRYPTO,
            "COPX": AssetGroup.COMMODITY,
            "TLT": AssetGroup.BOND,
            "SH": AssetGroup.INVERSE,
        }

        for symbol, expected_group in expected.items():
            actual = rm.symbol_groups.get(symbol)
            assert actual == expected_group, (
                f"{symbol}: expected {expected_group}, got {actual}"
            )


class TestShortDirectionLimit:
    """숏 방향 한도: 12 Units (lines 64-65)"""

    def test_exceeds_short_direction_limit(self):
        """숏 방향 한도 초과 시 False 반환 (lines 64-65)"""
        symbol_groups = {
            "SPY": AssetGroup.US_EQUITY,
            "005930.KS": AssetGroup.KR_EQUITY,
            "BTC-USD": AssetGroup.CRYPTO,
            "AAPL": AssetGroup.US_TECH,
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
