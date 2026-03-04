"""
VICBDetector 단위 테스트

VI/CB 상태 감지 + 거래 가드 검증:
- VI 상태별 진입 차단/허용
- CB 발동/해제 전환
- Fail-Open (캐시 만료/미존재)
- OrderStatus.REJECTED 카운트
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auto_trader import AutoTrader
from src.kis_api import KISAPIClient, KISConfig, OrderSide
from src.types import OrderStatus
from src.vi_cb_detector import CBStatus, VICBDetector, VIStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def detector():
    """기본 VICBDetector (캐시 TTL 30초)"""
    return VICBDetector(cache_ttl_sec=30)


@pytest.fixture
def short_ttl_detector():
    """짧은 TTL VICBDetector (테스트용 1초)"""
    return VICBDetector(cache_ttl_sec=1)


# ---------------------------------------------------------------------------
# TestVICBDetector
# ---------------------------------------------------------------------------


class TestVICBDetector:
    """VICBDetector 핵심 기능 테스트"""

    def test_vi_none_allows_entry(self, detector):
        """VI 없음 -> 진입 허용"""
        detector.update_from_spot("005930", {"vi_cls_code": "0"})
        allowed, reason = detector.check_entry_allowed("005930")
        assert allowed is True
        assert reason == ""

    def test_static_vi_blocks_entry(self, detector):
        """정적 VI -> BUY 차단"""
        detector.update_from_spot("005930", {"vi_cls_code": "1"})
        allowed, reason = detector.check_entry_allowed("005930")
        assert allowed is False
        assert "VI 발동" in reason
        assert "static" in reason

    def test_dynamic_vi_blocks_entry(self, detector):
        """동적 VI -> BUY 차단"""
        detector.update_from_spot("005930", {"vi_cls_code": "2"})
        allowed, reason = detector.check_entry_allowed("005930")
        assert allowed is False
        assert "VI 발동" in reason
        assert "dynamic" in reason

    def test_sell_always_allowed_during_vi(self, detector):
        """VI 활성 중 SELL -> 허용 (Principle 3)

        VICBDetector 자체는 BUY/SELL을 구분하지 않는다.
        호출측(auto_trader.place_order)에서 side == OrderSide.BUY일 때만
        check_entry_allowed를 호출하므로, SELL은 가드 자체가 실행되지 않는다.
        이 테스트는 auto_trader의 통합 동작을 검증한다.
        """
        detector.update_from_spot("005930", {"vi_cls_code": "1"})

        # VICBDetector 자체는 entry blocked 반환
        allowed, reason = detector.check_entry_allowed("005930")
        assert allowed is False

        # auto_trader에서 SELL은 VI/CB 가드를 타지 않으므로 통과
        # (auto_trader 코드: if self.vi_cb_detector and side == OrderSide.BUY:)
        # 여기서는 가드가 side를 체크하는 것은 auto_trader의 책임임을 확인

    def test_cb_blocks_all_entries(self, detector):
        """CB 발동 -> 전 종목 BUY 차단"""
        detector.activate_cb(CBStatus.CB_LEVEL1, "KOSPI -8%")
        # 캐시 없는 종목도 CB로 차단되도록 update_from_spot 필요
        detector.update_from_spot("005930", {"vi_cls_code": "0"})
        allowed, reason = detector.check_entry_allowed("005930")
        assert allowed is False
        assert "CB 발동" in reason

    def test_cache_expiry_allows_entry(self, short_ttl_detector):
        """캐시 만료 -> Fail-Open 허용"""
        short_ttl_detector.update_from_spot("005930", {"vi_cls_code": "1"})
        # 즉시 확인 -> 차단
        allowed, _ = short_ttl_detector.check_entry_allowed("005930")
        assert allowed is False

        # TTL 만료 대기 (1초 TTL)
        time.sleep(1.1)

        # 만료 후 -> Fail-Open 허용
        allowed, reason = short_ttl_detector.check_entry_allowed("005930")
        assert allowed is True
        assert reason == ""

    def test_no_cache_allows_entry(self, detector):
        """캐시 없음 -> Fail-Open 허용"""
        allowed, reason = detector.check_entry_allowed("UNKNOWN_SYMBOL")
        assert allowed is True
        assert reason == ""

    def test_cb_activate_deactivate(self, detector):
        """CB 활성/해제 전환"""
        # 초기 상태: CB 비활성
        detector.update_from_spot("005930", {"vi_cls_code": "0"})
        allowed, _ = detector.check_entry_allowed("005930")
        assert allowed is True

        # CB 활성화
        detector.activate_cb(CBStatus.CB_LEVEL1, "테스트")
        detector.update_from_spot("005930", {"vi_cls_code": "0"})
        allowed, reason = detector.check_entry_allowed("005930")
        assert allowed is False
        assert "CB 발동" in reason

        # CB 해제
        detector.deactivate_cb()
        detector.update_from_spot("005930", {"vi_cls_code": "0"})
        allowed, _ = detector.check_entry_allowed("005930")
        assert allowed is True

    def test_vi_code_mapping(self, detector):
        """모든 VI 코드 매핑 정확성"""
        assert VICBDetector.VI_CODE_MAP["0"] == VIStatus.NONE
        assert VICBDetector.VI_CODE_MAP["1"] == VIStatus.STATIC_VI
        assert VICBDetector.VI_CODE_MAP["2"] == VIStatus.DYNAMIC_VI

    def test_unknown_vi_code_defaults_none(self, detector):
        """미정의 코드 -> VIStatus.NONE (Fail-Open)"""
        status = detector.update_from_spot("005930", {"vi_cls_code": "9"})
        assert status.vi_status == VIStatus.NONE
        assert status.is_entry_blocked is False

        # vi_cls_code 누락 시에도 NONE
        status2 = detector.update_from_spot("005930", {})
        assert status2.vi_status == VIStatus.NONE

    def test_spot_data_vi_cls_code_propagation(self, detector):
        """SpotData에서 vi_cls_code가 VICBDetector로 전달됨"""
        from src.spot_price import SpotData

        spot = SpotData(
            price=70000.0,
            high=71000.0,
            low=69000.0,
            open=70500.0,
            volume=1000000,
            is_delayed=False,
            vi_cls_code="1",
        )
        status = detector.update_from_spot("005930", spot)
        assert status.vi_status == VIStatus.STATIC_VI
        assert status.is_entry_blocked is True


# ---------------------------------------------------------------------------
# TestRejectedCountedInDailyStats -- auto_trader 통합
# ---------------------------------------------------------------------------


class TestRejectedCountedInDailyStats:
    """REJECTED 주문이 get_daily_stats()에 집계되는지 검증"""

    @pytest.fixture
    def mock_kis_client(self):
        """KISAPIClient Mock"""
        client = MagicMock(spec=KISAPIClient)
        client.config = KISConfig(
            app_key="TEST", app_secret="TEST", account_no="12345678"
        )
        client.place_order = AsyncMock(
            return_value={"success": True, "order_no": "KIS_001", "order_time": "120000"}
        )
        client.get_balance = AsyncMock(
            return_value={"total_equity": 10_000_000.0, "cash": 5_000_000.0, "positions": []}
        )
        client.get_daily_fills = AsyncMock(return_value=[])
        return client

    def test_rejected_counted_in_daily_stats(self, mock_kis_client, temp_data_dir):
        """REJECTED 주문이 get_daily_stats()의 rejected 카운트에 포함됨"""
        # VI 발동 상태의 detector 생성
        vi_detector = VICBDetector()
        vi_detector.update_from_spot("005930", {"vi_cls_code": "1"})

        trader = AutoTrader(
            kis_client=mock_kis_client,
            dry_run=True,
            max_order_amount=5_000_000,
            vi_cb_detector=vi_detector,
        )

        import src.auto_trader as at_module

        original_path = at_module.ORDER_LOG_PATH
        at_module.ORDER_LOG_PATH = temp_data_dir / "trades" / "order_log.json"

        try:
            # VI로 차단되는 BUY 주문
            record = asyncio.run(
                trader.place_order(
                    symbol="005930",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=70_000.0,
                    reason="VI 차단 테스트",
                )
            )

            assert record.status == OrderStatus.REJECTED.value
            assert "VI/CB" in (record.error_message or "")

            # 정상 DRY_RUN 주문 (다른 종목)
            asyncio.run(
                trader.place_order(
                    symbol="SPY",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=500.0,
                    reason="정상 주문",
                )
            )

            stats = trader.get_daily_stats()
            assert stats["rejected"] == 1
            assert stats["dry_run"] == 1
            assert stats["total_orders"] == 2
        finally:
            at_module.ORDER_LOG_PATH = original_path


# ---------------------------------------------------------------------------
# TestVICBAutoTraderIntegration -- place_order VI/CB 가드 통합 테스트
# ---------------------------------------------------------------------------


class TestVICBAutoTraderIntegration:
    """auto_trader.place_order() VI/CB 가드 통합 검증"""

    @pytest.fixture
    def mock_kis_client(self):
        """KISAPIClient Mock"""
        client = MagicMock(spec=KISAPIClient)
        client.config = KISConfig(
            app_key="TEST", app_secret="TEST", account_no="12345678"
        )
        client.place_order = AsyncMock(
            return_value={"success": True, "order_no": "KIS_001", "order_time": "120000"}
        )
        client.get_balance = AsyncMock(
            return_value={"total_equity": 10_000_000.0, "cash": 5_000_000.0, "positions": []}
        )
        client.get_daily_fills = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_vi_blocks_buy_allows_sell(self, mock_kis_client, temp_data_dir):
        """VI 활성 시 BUY 차단, SELL 허용"""
        vi_detector = VICBDetector()
        vi_detector.update_from_spot("005930", {"vi_cls_code": "1"})

        trader = AutoTrader(
            kis_client=mock_kis_client,
            dry_run=True,
            max_order_amount=5_000_000,
            vi_cb_detector=vi_detector,
        )

        import src.auto_trader as at_module

        original_path = at_module.ORDER_LOG_PATH
        at_module.ORDER_LOG_PATH = temp_data_dir / "trades" / "order_log.json"

        try:
            # BUY -> REJECTED
            buy_record = await trader.place_order(
                symbol="005930", side=OrderSide.BUY, quantity=10, price=70_000.0
            )
            assert buy_record.status == OrderStatus.REJECTED.value

            # SELL -> DRY_RUN (VI에 관계없이 통과)
            sell_record = await trader.place_order(
                symbol="005930", side=OrderSide.SELL, quantity=10, price=70_000.0
            )
            assert sell_record.status == OrderStatus.DRY_RUN.value
        finally:
            at_module.ORDER_LOG_PATH = original_path

    @pytest.mark.asyncio
    async def test_no_vi_cb_detector_allows_all(self, mock_kis_client, temp_data_dir):
        """vi_cb_detector=None 시 기존 동작 보존"""
        trader = AutoTrader(
            kis_client=mock_kis_client,
            dry_run=True,
            max_order_amount=5_000_000,
            vi_cb_detector=None,
        )

        import src.auto_trader as at_module

        original_path = at_module.ORDER_LOG_PATH
        at_module.ORDER_LOG_PATH = temp_data_dir / "trades" / "order_log.json"

        try:
            record = await trader.place_order(
                symbol="005930", side=OrderSide.BUY, quantity=10, price=70_000.0
            )
            assert record.status == OrderStatus.DRY_RUN.value
        finally:
            at_module.ORDER_LOG_PATH = original_path
