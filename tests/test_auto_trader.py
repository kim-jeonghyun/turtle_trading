"""
auto_trader.py 단위 테스트
- Dry-run 모드 검증
- 주문 금액 한도
- OrderRecord 생성
- 주문 로깅
- Live 모드 KIS API 위임
- 일별 통계
- CLI 인수 파싱
"""

import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.auto_trader import AutoTrader, OrderRecord
from src.types import OrderStatus
from src.kis_api import KISAPIClient, KISConfig, OrderSide, OrderType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_kis_config():
    """테스트용 KIS 설정 (모의 자격증명)"""
    return KISConfig(
        app_key="TEST_APP_KEY",
        app_secret="TEST_APP_SECRET",
        account_no="12345678",
        account_suffix="01",
        is_real=False
    )


@pytest.fixture
def mock_kis_client(mock_kis_config):
    """KISAPIClient Mock"""
    client = MagicMock(spec=KISAPIClient)
    client.config = mock_kis_config
    # place_order를 AsyncMock으로 설정
    client.place_order = AsyncMock(return_value={
        "success": True,
        "order_no": "KIS_ORDER_001",
        "order_time": "120000"
    })
    client.get_balance = AsyncMock(return_value={
        "total_equity": 10_000_000.0,
        "cash": 5_000_000.0,
        "positions": []
    })
    return client


@pytest.fixture
def dry_run_trader(mock_kis_client, temp_data_dir):
    """Dry-run AutoTrader (기본 모드)"""
    trader = AutoTrader(
        kis_client=mock_kis_client,
        dry_run=True,
        max_order_amount=5_000_000
    )
    # 테스트용 임시 경로 패치
    import src.auto_trader as at_module
    original_path = at_module.ORDER_LOG_PATH
    at_module.ORDER_LOG_PATH = temp_data_dir / "trades" / "order_log.json"
    yield trader
    at_module.ORDER_LOG_PATH = original_path


@pytest.fixture
def live_trader(mock_kis_client, temp_data_dir):
    """Live AutoTrader"""
    trader = AutoTrader(
        kis_client=mock_kis_client,
        dry_run=False,
        max_order_amount=5_000_000
    )
    import src.auto_trader as at_module
    original_path = at_module.ORDER_LOG_PATH
    at_module.ORDER_LOG_PATH = temp_data_dir / "trades" / "order_log.json"
    yield trader
    at_module.ORDER_LOG_PATH = original_path


# ---------------------------------------------------------------------------
# TestAutoTrader
# ---------------------------------------------------------------------------

class TestAutoTrader:

    def test_dry_run_does_not_call_api(self, dry_run_trader, mock_kis_client):
        """dry_run=True 시 KIS API가 절대 호출되지 않아야 한다"""
        record = asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=10,
                price=500.0,
                order_type=OrderType.LIMIT,
                reason="Test dry-run"
            )
        )

        # KIS place_order가 호출되지 않았는지 확인
        mock_kis_client.place_order.assert_not_called()

        # 상태는 DRY_RUN이어야 함
        assert record.status == OrderStatus.DRY_RUN.value
        assert record.dry_run is True

    def test_order_amount_limit(self, dry_run_trader):
        """주문 금액이 한도를 초과하면 FAILED 상태로 반환되어야 한다"""
        # max_order_amount = 5_000_000
        # 10,000주 * 1,000원 = 10,000,000원 (한도 초과)
        record = asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="TEST",
                side=OrderSide.BUY,
                quantity=10_000,
                price=1_000.0,
                order_type=OrderType.MARKET,
                reason="금액 초과 테스트"
            )
        )

        assert record.status == OrderStatus.FAILED.value
        assert record.error_message is not None
        assert "초과" in record.error_message

    def test_order_amount_within_limit(self, dry_run_trader):
        """주문 금액이 한도 내일 때 정상 처리되어야 한다"""
        # 100주 * 10,000원 = 1,000,000원 (한도 내)
        record = asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100,
                price=10_000.0,
                order_type=OrderType.LIMIT,
                reason="한도 내 주문"
            )
        )

        assert record.status == OrderStatus.DRY_RUN.value
        assert record.error_message is None

    def test_order_record_creation(self, dry_run_trader):
        """OrderRecord가 모든 필수 필드를 포함해야 한다"""
        record = asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="AAPL",
                side=OrderSide.SELL,
                quantity=5,
                price=180.0,
                order_type=OrderType.MARKET,
                reason="System 1 청산"
            )
        )

        # 모든 필수 필드 존재 확인
        assert record.order_id is not None and record.order_id != ""
        assert record.symbol == "AAPL"
        assert record.side == "sell"
        assert record.quantity == 5
        assert record.price == 180.0
        assert record.order_type == "MARKET"
        assert record.status is not None
        assert record.timestamp is not None
        assert isinstance(record.dry_run, bool)
        assert record.reason == "System 1 청산"

    def test_order_record_has_optional_fields(self, dry_run_trader):
        """OrderRecord의 선택적 필드가 올바른 타입이어야 한다"""
        record = asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="QQQ",
                side=OrderSide.BUY,
                quantity=20,
                price=400.0
            )
        )

        # Dry-run에서는 fill_price와 fill_time이 채워져야 함
        assert record.fill_price is not None
        assert record.fill_time is not None
        # error_message는 없어야 함
        assert record.error_message is None

    def test_order_logging(self, dry_run_trader, temp_data_dir):
        """주문이 JSON 파일에 로깅되어야 한다"""
        import src.auto_trader as at_module
        log_path = at_module.ORDER_LOG_PATH

        # 주문 실행
        asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=10,
                price=500.0,
                reason="로깅 테스트"
            )
        )

        # 파일 존재 확인
        assert log_path.exists(), f"주문 로그 파일이 생성되지 않음: {log_path}"

        # JSON 파싱 가능한지 확인
        with open(log_path, 'r', encoding='utf-8') as f:
            orders = json.load(f)

        assert isinstance(orders, list)
        assert len(orders) == 1
        assert orders[0]["symbol"] == "SPY"
        assert orders[0]["quantity"] == 10

    def test_multiple_orders_logging(self, dry_run_trader):
        """여러 주문이 누적 로깅되어야 한다"""
        symbols = ["SPY", "QQQ", "AAPL"]
        for symbol in symbols:
            asyncio.get_event_loop().run_until_complete(
                dry_run_trader.place_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=10,
                    price=100.0
                )
            )

        history = dry_run_trader.get_order_history()
        assert len(history) == 3
        logged_symbols = [o["symbol"] for o in history]
        assert set(logged_symbols) == set(symbols)

    def test_live_order_delegates_to_kis(self, live_trader, mock_kis_client):
        """live 모드에서 KIS API place_order가 호출되어야 한다"""
        record = asyncio.get_event_loop().run_until_complete(
            live_trader.place_order(
                symbol="005930",
                side=OrderSide.BUY,
                quantity=5,
                price=70_000.0,
                order_type=OrderType.LIMIT,
                reason="Live 주문 테스트"
            )
        )

        # KIS API가 호출되었는지 확인
        mock_kis_client.place_order.assert_called_once()
        call_kwargs = mock_kis_client.place_order.call_args

        # 올바른 인수로 호출되었는지 확인
        assert call_kwargs[1]["symbol"] == "005930" or call_kwargs[0][0] == "005930"

        # 상태는 FILLED이어야 함 (mock이 success=True 반환)
        assert record.status == OrderStatus.FILLED.value
        assert record.dry_run is False

    def test_live_order_handles_failure(self, live_trader, mock_kis_client):
        """Live 주문 실패 시 FAILED 상태를 반환해야 한다"""
        # mock에서 실패 응답 설정
        mock_kis_client.place_order = AsyncMock(return_value={
            "success": False,
            "message": "잔고 부족"
        })

        record = asyncio.get_event_loop().run_until_complete(
            live_trader.place_order(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=10,
                price=500.0,
                reason="실패 테스트"
            )
        )

        assert record.status == OrderStatus.FAILED.value
        assert "잔고 부족" in (record.error_message or "")

    def test_live_order_handles_exception(self, live_trader, mock_kis_client):
        """Live 주문 예외 발생 시 FAILED 상태를 반환해야 한다"""
        mock_kis_client.place_order = AsyncMock(side_effect=ConnectionError("네트워크 오류"))

        record = asyncio.get_event_loop().run_until_complete(
            live_trader.place_order(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=10,
                price=500.0
            )
        )

        assert record.status == OrderStatus.FAILED.value
        assert "네트워크 오류" in (record.error_message or "")

    def test_daily_stats(self, dry_run_trader):
        """일별 통계가 올바르게 계산되어야 한다"""
        # 3개 주문 실행
        for i in range(3):
            asyncio.get_event_loop().run_until_complete(
                dry_run_trader.place_order(
                    symbol="SPY",
                    side=OrderSide.BUY,
                    quantity=10,
                    price=100.0
                )
            )

        # 1개 실패 주문 (금액 초과)
        asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="TEST",
                side=OrderSide.BUY,
                quantity=100_000,
                price=1_000.0
            )
        )

        stats = dry_run_trader.get_daily_stats()

        assert stats["total_orders"] == 4
        assert stats["dry_run"] == 3
        assert stats["failed"] == 1
        assert stats["filled"] == 0
        assert stats["date"] == datetime.now().strftime("%Y-%m-%d")

    def test_daily_stats_total_amount(self, dry_run_trader):
        """일별 통계의 총 주문 금액이 올바르게 계산되어야 한다"""
        asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=100,
                price=500.0  # 50,000원
            )
        )
        asyncio.get_event_loop().run_until_complete(
            dry_run_trader.place_order(
                symbol="QQQ",
                side=OrderSide.BUY,
                quantity=50,
                price=400.0  # 20,000원
            )
        )

        stats = dry_run_trader.get_daily_stats()
        # 총 70,000원
        assert stats["total_amount"] == pytest.approx(50_000 + 20_000)

    def test_get_order_history_empty(self, dry_run_trader):
        """주문 이력이 없을 때 빈 리스트 반환"""
        history = dry_run_trader.get_order_history()
        assert history == []

    def test_get_account_summary_dry_run(self, dry_run_trader):
        """dry_run 모드에서 계좌 요약 시 더미 데이터 반환"""
        account = asyncio.get_event_loop().run_until_complete(
            dry_run_trader.get_account_summary()
        )

        assert account["dry_run"] is True
        assert "total_equity" in account
        assert "positions" in account

    def test_get_account_summary_live(self, live_trader, mock_kis_client):
        """live 모드에서 계좌 요약 시 KIS API 호출"""
        account = asyncio.get_event_loop().run_until_complete(
            live_trader.get_account_summary()
        )

        mock_kis_client.get_balance.assert_called_once()
        assert account["dry_run"] is False
        assert account["total_equity"] == 10_000_000.0

    def test_order_id_is_unique(self, dry_run_trader):
        """각 주문의 ID가 고유해야 한다"""
        records = []
        for _ in range(5):
            record = asyncio.get_event_loop().run_until_complete(
                dry_run_trader.place_order(
                    symbol="SPY",
                    side=OrderSide.BUY,
                    quantity=1,
                    price=100.0
                )
            )
            records.append(record)

        order_ids = [r.order_id for r in records]
        assert len(set(order_ids)) == 5, "주문 ID가 중복됨"

    def test_check_order_status_dry_run(self, dry_run_trader):
        """dry_run 모드에서 주문 상태 조회 시 dry_run 응답 반환"""
        result = asyncio.get_event_loop().run_until_complete(
            dry_run_trader.check_order_status("SOME_ORDER_NO")
        )

        assert result["status"] == "dry_run"


# ---------------------------------------------------------------------------
# TestAutoTradeCLI
# ---------------------------------------------------------------------------

class TestAutoTradeCLI:

    def test_default_is_dry_run(self):
        """--live 플래그 없이 실행 시 dry_run=True가 기본값이어야 한다"""
        import sys
        # 인수 없이 파싱
        sys.argv = ["auto_trade.py"]

        from scripts.auto_trade import parse_args
        args = parse_args()

        assert args.live is False, "--live 미사용 시 dry-run이어야 함"

    def test_parse_args_live_flag(self):
        """--live 플래그 파싱 테스트"""
        import sys
        sys.argv = ["auto_trade.py", "--live"]

        from scripts.auto_trade import parse_args
        args = parse_args()

        assert args.live is True

    def test_parse_args_symbols(self):
        """--symbols 인수 파싱 테스트"""
        import sys
        sys.argv = ["auto_trade.py", "--symbols", "SPY", "QQQ", "AAPL"]

        from scripts.auto_trade import parse_args
        args = parse_args()

        assert args.symbols == ["SPY", "QQQ", "AAPL"]

    def test_parse_args_max_amount(self):
        """--max-amount 인수 파싱 테스트"""
        import sys
        sys.argv = ["auto_trade.py", "--max-amount", "1000000"]

        from scripts.auto_trade import parse_args
        args = parse_args()

        assert args.max_amount == 1_000_000.0

    def test_parse_args_system(self):
        """--system 인수 파싱 테스트"""
        import sys
        sys.argv = ["auto_trade.py", "--system", "2"]

        from scripts.auto_trade import parse_args
        args = parse_args()

        assert args.system == 2

    def test_parse_args_verbose(self):
        """--verbose 인수 파싱 테스트"""
        import sys
        sys.argv = ["auto_trade.py", "--verbose"]

        from scripts.auto_trade import parse_args
        args = parse_args()

        assert args.verbose is True

    def test_parse_args_defaults(self):
        """기본값 검증"""
        import sys
        sys.argv = ["auto_trade.py"]

        from scripts.auto_trade import parse_args, DEFAULT_MAX_AMOUNT
        args = parse_args()

        assert args.live is False
        assert args.max_amount == DEFAULT_MAX_AMOUNT
        assert args.symbols is None
        assert args.system is None
        assert args.verbose is False

    def test_parse_args_combined(self):
        """복합 인수 파싱 테스트"""
        import sys
        sys.argv = [
            "auto_trade.py",
            "--live",
            "--symbols", "005930.KS",
            "--system", "1",
            "--max-amount", "2000000",
            "--verbose"
        ]

        from scripts.auto_trade import parse_args
        args = parse_args()

        assert args.live is True
        assert args.symbols == ["005930.KS"]
        assert args.system == 1
        assert args.max_amount == 2_000_000.0
        assert args.verbose is True
