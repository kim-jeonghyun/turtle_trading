"""
monitor_positions.py 리팩토링 통합 테스트
"""

import asyncio
import fcntl
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.monitor_positions import (
    acquire_lock,
    calculate_unrealized_pnl,
    check_stop_loss_intraday,
    monitor_positions,
)
from src.types import Direction


def _make_lock_fd():
    """fcntl.flock 호환 mock file descriptor 생성."""
    fd = MagicMock()
    fd.fileno.return_value = 999
    return fd


def _make_position(
    position_id="pos_1",
    symbol="AAPL",
    direction=Direction.LONG,
    entry_price=100.0,
    stop_loss=90.0,
    total_shares=10,
    **kwargs,
):
    """테스트용 Position mock 생성 (SimpleNamespace — 속성 오타 시 AttributeError)."""
    return SimpleNamespace(
        position_id=position_id,
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        total_shares=total_shares,
        system=kwargs.get("system", 1),
        units=kwargs.get("units", 1),
        max_units=kwargs.get("max_units", 4),
        entry_date=kwargs.get("entry_date", "2026-01-01"),
        entry_n=kwargs.get("entry_n", 5.0),
    )


class TestStopLossCheck:
    """장중 스톱로스 체크 테스트"""

    def test_stop_loss_long_triggered(self):
        """LONG: spot['low'] <= stop -> True"""
        pos = _make_position(direction=Direction.LONG, stop_loss=90.0)
        assert check_stop_loss_intraday(pos, {"low": 89.0, "high": 95.0}) is True

    def test_stop_loss_short_triggered(self):
        """SHORT: spot['high'] >= stop -> True"""
        pos = _make_position(direction=Direction.SHORT, stop_loss=110.0)
        assert check_stop_loss_intraday(pos, {"low": 105.0, "high": 111.0}) is True

    def test_stop_loss_not_triggered(self):
        """가격 정상 -> False"""
        pos = _make_position(direction=Direction.LONG, stop_loss=90.0)
        assert check_stop_loss_intraday(pos, {"low": 95.0, "high": 105.0}) is False

    def test_stop_loss_dedup(self, tmp_path):
        """이미 알림된 포지션 -> 재알림 차단"""
        from src.monitor_state import MonitorState

        state = MonitorState(state_file=tmp_path / "state.json")
        state.mark_stop_loss_alerted("pos_1")
        assert state.is_stop_loss_alerted("pos_1") is True

    def test_stop_loss_at_boundary(self):
        """low == stop_loss (경계값 동등) -> 발동"""
        pos = _make_position(direction=Direction.LONG, stop_loss=90.0)
        assert check_stop_loss_intraday(pos, {"low": 90.0, "high": 95.0}) is True

    def test_stop_loss_short_at_boundary(self):
        """SHORT: high == stop_loss (경계값 동등) -> 발동"""
        pos = _make_position(direction=Direction.SHORT, stop_loss=110.0)
        assert check_stop_loss_intraday(pos, {"low": 105.0, "high": 110.0}) is True

    async def test_stop_loss_triggers_notification(self):
        """스톱로스 이탈 → notifier.send_message 호출 (ERROR 레벨)"""
        from src.notifier import NotificationLevel

        pos = _make_position(
            direction=Direction.LONG,
            entry_price=100.0,
            stop_loss=90.0,
            total_shares=10,
        )
        tracker = MagicMock()
        tracker.get_open_positions.return_value = [pos]

        notifier = AsyncMock()
        spot_fetcher = AsyncMock()
        spot_fetcher.fetch_spot_price.return_value = {
            "price": 88.0,
            "high": 95.0,
            "low": 85.0,  # 85 <= 90 (stop_loss) → 발동
        }
        state = MagicMock()
        state.is_stop_loss_alerted.return_value = False

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=notifier),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.SpotPriceFetcher", return_value=spot_fetcher),
            patch("scripts.monitor_positions.is_market_open", return_value=True),
            patch("scripts.monitor_positions.infer_market", return_value="US"),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = _make_lock_fd()
            mock_state_cls.load.return_value = state
            state.cleanup_closed_positions = MagicMock()
            state.save = MagicMock()
            state.can_send_warning.return_value = False

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            # 알림 발송 확인: 정확히 1회, ERROR 레벨
            notifier.send_message.assert_called_once()
            msg = notifier.send_message.call_args[0][0]
            assert msg.level == NotificationLevel.ERROR
            assert "STOP LOSS" in msg.title
            # MonitorState에 알림 기록 확인
            state.mark_stop_loss_alerted.assert_called_once_with("pos_1")

    async def test_stop_loss_recovery_reset_integration(self):
        """스톱로스 알림 → 가격 회복 → reset 확인 (메인 루프)"""
        pos = _make_position(
            direction=Direction.LONG,
            entry_price=100.0,
            stop_loss=90.0,
            total_shares=10,
        )
        tracker = MagicMock()
        tracker.get_open_positions.return_value = [pos]

        notifier = AsyncMock()
        spot_fetcher = AsyncMock()
        # 가격 회복: low=95 > stop=90 → 스톱로스 미이탈
        spot_fetcher.fetch_spot_price.return_value = {
            "price": 100.0,
            "high": 105.0,
            "low": 95.0,
        }
        state = MagicMock()
        # 이전에 스톱로스 알림 발송됨
        state.is_stop_loss_alerted.return_value = True
        state.can_send_warning.return_value = False

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=notifier),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.SpotPriceFetcher", return_value=spot_fetcher),
            patch("scripts.monitor_positions.is_market_open", return_value=True),
            patch("scripts.monitor_positions.infer_market", return_value="US"),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = MagicMock()
            mock_lock.return_value.fileno.return_value = 999
            mock_state_cls.load.return_value = state
            state.cleanup_closed_positions = MagicMock()
            state.save = MagicMock()

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            # 가격 회복 → reset 호출
            state.reset_stop_loss_alert.assert_called_once_with("pos_1")
            # 알림 미발송 (회복이므로)
            notifier.send_message.assert_not_called()


class TestPnlWarning:
    """P&L 경고 테스트"""

    def test_pnl_warning_triggered(self):
        """P&L < -threshold -> 경고"""
        pos = _make_position(entry_price=100.0, total_shares=10)
        pnl_dollar, pnl_pct = calculate_unrealized_pnl(pos, 90.0)
        assert pnl_pct < -0.05  # -10% < -5%

    def test_pnl_warning_cooldown(self, tmp_path):
        """쿨다운 이내 -> 경고 차단"""
        from src.monitor_state import MonitorState

        state = MonitorState(state_file=tmp_path / "state.json")
        state.update_warning("pos_1")
        assert state.can_send_warning("pos_1", cooldown_minutes=60) is False

    def test_pnl_short_direction(self):
        """SHORT: entry=100, current=110 -> pnl_dollar=-100, pnl_pct=-10%"""
        pos = _make_position(direction=Direction.SHORT, entry_price=100.0, total_shares=10)
        pnl_dollar, pnl_pct = calculate_unrealized_pnl(pos, 110.0)
        assert pnl_dollar == pytest.approx(-100.0)
        assert pnl_pct == pytest.approx(-0.10)

    def test_pnl_zero_entry_price_guard(self):
        """entry_price=0 -> (0.0, 0.0) 반환, ZeroDivisionError 방지"""
        pos = _make_position(entry_price=0.0, total_shares=10)
        pnl_dollar, pnl_pct = calculate_unrealized_pnl(pos, 100.0)
        assert pnl_dollar == 0.0
        assert pnl_pct == 0.0

    def test_pnl_threshold_boundary(self):
        """pnl_pct == -threshold -> 경고 발송 (<=)"""
        pos = _make_position(entry_price=100.0, total_shares=10)
        # -5% exactly
        pnl_dollar, pnl_pct = calculate_unrealized_pnl(pos, 95.0)
        assert pnl_pct <= -0.05

    async def test_pnl_warning_triggers_notification(self):
        """PnL 경고 → notifier.send_message 호출 (WARNING 레벨)"""
        from src.notifier import NotificationLevel

        pos = _make_position(
            direction=Direction.LONG,
            entry_price=100.0,
            stop_loss=80.0,
            total_shares=10,
        )
        tracker = MagicMock()
        tracker.get_open_positions.return_value = [pos]

        notifier = AsyncMock()
        spot_fetcher = AsyncMock()
        spot_fetcher.fetch_spot_price.return_value = {
            "price": 90.0,  # -10% → threshold 5% 초과
            "high": 101.0,
            "low": 89.0,
        }
        state = MagicMock()
        state.is_stop_loss_alerted.return_value = False
        state.can_send_warning.return_value = True

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=notifier),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.SpotPriceFetcher", return_value=spot_fetcher),
            patch("scripts.monitor_positions.is_market_open", return_value=True),
            patch("scripts.monitor_positions.infer_market", return_value="US"),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = MagicMock()
            mock_lock.return_value.fileno.return_value = 999
            mock_state_cls.load.return_value = state
            state.cleanup_closed_positions = MagicMock()
            state.save = MagicMock()

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            # 알림 발송 확인: stop_loss 미이탈 + PnL 경고
            # stop_loss=80이고 low=89이므로 스톱로스 미발동
            # PnL = -10% > -5% threshold → 경고
            assert notifier.send_message.call_count == 1
            msg = notifier.send_message.call_args[0][0]
            assert msg.level == NotificationLevel.WARNING
            assert "UNREALIZED LOSS" in msg.title
            state.update_warning.assert_called_once_with("pos_1")


class TestMarketGate:
    """마켓 시간 게이트 테스트"""

    async def test_market_closed_skip(self, tmp_path):
        """장외 시간 -> 가격 조회 skip"""
        pos = _make_position(symbol="AAPL")
        tracker = MagicMock()
        tracker.get_open_positions.return_value = [pos]

        notifier = AsyncMock()
        spot_fetcher = AsyncMock()
        state = MagicMock()

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=notifier),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.SpotPriceFetcher", return_value=spot_fetcher),
            patch("scripts.monitor_positions.is_market_open", return_value=False),
            patch("scripts.monitor_positions.infer_market", return_value="US"),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = _make_lock_fd()
            mock_state_cls.load.return_value = state
            state.cleanup_closed_positions = MagicMock()
            state.save = MagicMock()

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            spot_fetcher.fetch_spot_price.assert_not_called()

    async def test_crypto_always_monitored(self, tmp_path):
        """CRYPTO -> 항상 실행 (is_market_open 무시)"""
        pos = _make_position(symbol="BTC-USD", stop_loss=40000.0)
        tracker = MagicMock()
        tracker.get_open_positions.return_value = [pos]

        notifier = AsyncMock()
        spot_fetcher = AsyncMock()
        spot_fetcher.fetch_spot_price.return_value = {
            "price": 45000.0,
            "high": 46000.0,
            "low": 44000.0,
        }
        state = MagicMock()
        state.is_stop_loss_alerted.return_value = False

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=notifier),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.SpotPriceFetcher", return_value=spot_fetcher),
            patch("scripts.monitor_positions.is_market_open", return_value=False),
            patch("scripts.monitor_positions.infer_market", return_value="CRYPTO"),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = _make_lock_fd()
            mock_state_cls.load.return_value = state
            state.cleanup_closed_positions = MagicMock()
            state.save = MagicMock()
            state.can_send_warning.return_value = False

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            spot_fetcher.fetch_spot_price.assert_called_once_with("BTC-USD")

    async def test_no_positions_early_exit(self):
        """포지션 없음 -> 조기 종료"""
        tracker = MagicMock()
        tracker.get_open_positions.return_value = []

        spot_fetcher = AsyncMock()

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=AsyncMock()),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.SpotPriceFetcher", return_value=spot_fetcher),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = _make_lock_fd()
            mock_state_cls.load.return_value = MagicMock()

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            spot_fetcher.fetch_spot_price.assert_not_called()


class TestSafety:
    """안전 장치 테스트"""

    async def test_spot_price_failure_skip(self):
        """가격 조회 실패 -> skip"""
        pos = _make_position()
        tracker = MagicMock()
        tracker.get_open_positions.return_value = [pos]

        notifier = AsyncMock()
        spot_fetcher = AsyncMock()
        spot_fetcher.fetch_spot_price.return_value = None  # failure
        state = MagicMock()

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=notifier),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.SpotPriceFetcher", return_value=spot_fetcher),
            patch("scripts.monitor_positions.is_market_open", return_value=True),
            patch("scripts.monitor_positions.infer_market", return_value="US"),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = _make_lock_fd()
            mock_state_cls.load.return_value = state
            state.cleanup_closed_positions = MagicMock()
            state.save = MagicMock()

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            notifier.send_message.assert_not_called()

    def test_lock_prevents_concurrent(self, tmp_path):
        """LOCK_NB 실패 -> sys.exit(0)"""
        lock_file = tmp_path / ".monitor.lock"

        with patch("scripts.monitor_positions.LOCK_FILE", lock_file):
            # Acquire lock first
            fd1 = open(lock_file, "w")
            fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)

            try:
                # Second acquire should fail
                with pytest.raises(SystemExit) as exc_info:
                    acquire_lock()
                assert exc_info.value.code == 0
            finally:
                fcntl.flock(fd1, fcntl.LOCK_UN)
                fd1.close()

    async def test_position_load_error(self):
        """포지션 로드 예외 -> 에러 로그 후 종료"""
        tracker = MagicMock()
        tracker.get_open_positions.side_effect = Exception("file corrupt")

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=AsyncMock()),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = _make_lock_fd()
            mock_state_cls.load.return_value = MagicMock()

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            # Should not raise -- exception is caught
            await monitor_positions(args)

    async def test_state_saved_after_partial(self):
        """일부 실패 후에도 state.save() 호출 확인"""
        pos1 = _make_position(position_id="pos_1", symbol="AAPL")
        pos2 = _make_position(position_id="pos_2", symbol="GOOGL")
        tracker = MagicMock()
        tracker.get_open_positions.return_value = [pos1, pos2]

        notifier = AsyncMock()
        spot_fetcher = AsyncMock()
        # First succeeds, second fails
        spot_fetcher.fetch_spot_price.side_effect = [
            {"price": 100.0, "high": 105.0, "low": 95.0},
            None,
        ]
        state = MagicMock()
        state.is_stop_loss_alerted.return_value = False
        state.can_send_warning.return_value = False

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.PositionTracker", return_value=tracker),
            patch("scripts.monitor_positions.setup_notifier", return_value=notifier),
            patch("scripts.monitor_positions.load_config", return_value={}),
            patch("scripts.monitor_positions.MonitorState") as mock_state_cls,
            patch("scripts.monitor_positions.create_kis_client", return_value=None),
            patch("scripts.monitor_positions.SpotPriceFetcher", return_value=spot_fetcher),
            patch("scripts.monitor_positions.is_market_open", return_value=True),
            patch("scripts.monitor_positions.infer_market", return_value="US"),
            patch("scripts.monitor_positions.acquire_lock") as mock_lock,
        ):
            mock_lock.return_value = _make_lock_fd()
            mock_state_cls.load.return_value = state
            state.cleanup_closed_positions = MagicMock()

            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            state.save.assert_called_once()

    async def test_timeout_releases_lock(self):
        """asyncio.timeout → finally에서 lock 해제"""
        lock_fd = MagicMock()
        lock_fd.fileno.return_value = 999

        with (
            patch("scripts.monitor_positions.fcntl"),
            patch("scripts.monitor_positions.acquire_lock", return_value=lock_fd),
            patch("scripts.monitor_positions.load_config", side_effect=asyncio.TimeoutError),
        ):
            args = MagicMock()
            args.threshold = 0.05
            args.warning_cooldown = 60

            await monitor_positions(args)

            # finally 블록에서 lock 해제 확인
            lock_fd.close.assert_called_once()
