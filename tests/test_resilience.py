"""
에러 처리 & 복원력 테스트
- retry_async / retry_sync 데코레이터
- NotificationManager 에스컬레이션 및 병렬 전송
- setup_structured_logging 구조화 로깅
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.utils import retry_async, retry_sync, setup_structured_logging
from src.notifier import (
    NotificationChannel,
    NotificationLevel,
    NotificationManager,
    NotificationMessage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_async(coro):
    """동기 테스트에서 코루틴 실행 헬퍼"""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# TestRetryAsync
# ---------------------------------------------------------------------------

class TestRetryAsync:
    def test_succeeds_first_try(self):
        """첫 번째 시도에서 성공 – 재시도 없음"""
        call_count = 0

        @retry_async(max_retries=3, base_delay=0.0)
        async def always_succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = run_async(always_succeeds())
        assert result == "ok"
        assert call_count == 1

    def test_retries_on_failure(self):
        """실패 후 올바른 횟수만큼 재시도"""
        call_count = 0

        @retry_async(max_retries=3, base_delay=0.0)
        async def fails_twice_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("일시적 오류")
            return "recovered"

        result = run_async(fails_twice_then_succeeds())
        assert result == "recovered"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        """최대 재시도 소진 후 예외 발생"""
        call_count = 0

        @retry_async(max_retries=2, base_delay=0.0)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("영구 오류")

        with pytest.raises(RuntimeError, match="영구 오류"):
            run_async(always_fails())
        # 최초 시도 + 재시도 2회 = 총 3번
        assert call_count == 3

    def test_exponential_backoff(self):
        """지연 시간이 지수적으로 증가하는지 확인"""
        sleep_calls = []

        @retry_async(max_retries=3, base_delay=1.0, max_delay=30.0)
        async def always_fails():
            raise RuntimeError("오류")

        async def run():
            with patch("src.utils.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                mock_sleep.side_effect = lambda d: asyncio.coroutine(lambda: sleep_calls.append(d))()
                with pytest.raises(RuntimeError):
                    await always_fails()
            return sleep_calls

        # asyncio.sleep을 직접 패치하여 호출 지연값 검증
        captured = []

        @retry_async(max_retries=3, base_delay=1.0, max_delay=30.0)
        async def always_fails_v2():
            raise RuntimeError("오류")

        async def run_v2():
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(RuntimeError):
                    await always_fails_v2()
                return [c.args[0] for c in mock_sleep.call_args_list]

        delays = run_async(run_v2())
        # 지연: 1.0, 2.0, 4.0
        assert delays == [1.0, 2.0, 4.0]

    def test_specific_exception_filter(self):
        """지정된 예외 타입만 재시도, 나머지는 즉시 전파"""
        call_count = 0

        @retry_async(max_retries=3, base_delay=0.0, exceptions=(ValueError,))
        async def raises_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("재시도 안 함")

        with pytest.raises(TypeError):
            run_async(raises_type_error())
        # TypeError는 지정된 예외 아니므로 재시도 없이 즉시 실패
        assert call_count == 1

    def test_only_retries_specified_exceptions(self):
        """ValueError는 재시도, TypeError는 재시도 안 함"""
        call_count = 0

        @retry_async(max_retries=2, base_delay=0.0, exceptions=(ValueError,))
        async def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("재시도 대상")

        with pytest.raises(ValueError):
            run_async(raises_value_error())
        assert call_count == 3  # 최초 + 재시도 2


# ---------------------------------------------------------------------------
# Fake channel for testing
# ---------------------------------------------------------------------------

class FakeChannel(NotificationChannel):
    def __init__(self, name: str, should_succeed: bool = True):
        self._name = name
        self.should_succeed = should_succeed
        self.call_count = 0
        self.messages_received = []

    async def send(self, message: NotificationMessage) -> bool:
        self.call_count += 1
        self.messages_received.append(message)
        return self.should_succeed

    def __class_getitem__(cls, item):
        return cls


# ---------------------------------------------------------------------------
# TestNotificationEscalation
# ---------------------------------------------------------------------------

class TestNotificationEscalation:
    def _make_manager(self, channels):
        manager = NotificationManager()
        for ch in channels:
            manager.add_channel(ch)
        return manager

    def test_send_all_parallel(self):
        """모든 채널이 병렬로 호출되는지 확인"""
        ch1 = FakeChannel("ch1", should_succeed=True)
        ch2 = FakeChannel("ch2", should_succeed=True)
        manager = self._make_manager([ch1, ch2])

        msg = NotificationMessage(title="테스트", body="본문", level=NotificationLevel.INFO)
        results = run_async(manager.send_all(msg))

        assert ch1.call_count == 1
        assert ch2.call_count == 1
        # 두 채널 모두 결과에 포함 (클래스 이름이 같으므로 마지막 값 덮어쓰기 방지 위해
        # FakeChannel 인스턴스 클래스명은 동일 – 실제 동작 검증에 집중)
        assert len(results) >= 1

    def test_send_all_parallel_with_distinct_channels(self):
        """서로 다른 채널 타입을 병렬로 실행"""

        class FakeChannelA(NotificationChannel):
            call_count = 0

            async def send(self, message):
                FakeChannelA.call_count += 1
                return True

        class FakeChannelB(NotificationChannel):
            call_count = 0

            async def send(self, message):
                FakeChannelB.call_count += 1
                return True

        manager = NotificationManager()
        manager.add_channel(FakeChannelA())
        manager.add_channel(FakeChannelB())

        msg = NotificationMessage(title="병렬 테스트", body="body", level=NotificationLevel.SIGNAL)
        results = run_async(manager.send_all(msg))

        assert FakeChannelA.call_count == 1
        assert FakeChannelB.call_count == 1
        assert results.get("FakeChannelA") is True
        assert results.get("FakeChannelB") is True

    def test_channel_health_tracking(self):
        """성공/실패 카운트가 올바르게 추적되는지 확인"""

        class HealthChannelA(NotificationChannel):
            async def send(self, message):
                return True

        class HealthChannelB(NotificationChannel):
            async def send(self, message):
                return False

        manager = NotificationManager()
        manager.add_channel(HealthChannelA())
        manager.add_channel(HealthChannelB())

        msg = NotificationMessage(title="상태 추적", body="body", level=NotificationLevel.INFO)
        run_async(manager.send_all(msg))
        run_async(manager.send_all(msg))

        health = manager.get_channel_health()
        assert health["HealthChannelA"]["success"] == 2
        assert health["HealthChannelA"]["failure"] == 0
        assert health["HealthChannelB"]["success"] == 0
        assert health["HealthChannelB"]["failure"] == 2

    def test_escalation_on_error_logs_critical(self):
        """ERROR 레벨에서 모든 채널 실패 시 CRITICAL 로그 발생"""

        class FailingChannel(NotificationChannel):
            async def send(self, message):
                return False

        manager = NotificationManager()
        manager.add_channel(FailingChannel())

        msg = NotificationMessage(
            title="에러 알림", body="오류 발생", level=NotificationLevel.ERROR
        )

        with patch("src.notifier.logger") as mock_logger:
            run_async(manager.send_all(msg))
            mock_logger.critical.assert_called_once()
            call_args = mock_logger.critical.call_args[0][0]
            assert "ESCALATION" in call_args or "실패" in call_args

    def test_escalation_no_critical_when_partial_success(self):
        """ERROR 레벨이라도 하나 이상 성공 시 CRITICAL 로그 없음"""

        class SucceedingChannel(NotificationChannel):
            async def send(self, message):
                return True

        class FailingChannel(NotificationChannel):
            async def send(self, message):
                return False

        manager = NotificationManager()
        manager.add_channel(SucceedingChannel())
        manager.add_channel(FailingChannel())

        msg = NotificationMessage(
            title="부분 성공", body="body", level=NotificationLevel.ERROR
        )

        with patch("src.notifier.logger") as mock_logger:
            run_async(manager.send_all(msg))
            mock_logger.critical.assert_not_called()

    def test_send_with_escalation_info_uses_first_channel(self):
        """INFO 레벨은 첫 번째 채널만 사용"""

        class ChannelFirst(NotificationChannel):
            call_count = 0

            async def send(self, message):
                ChannelFirst.call_count += 1
                return True

        class ChannelSecond(NotificationChannel):
            call_count = 0

            async def send(self, message):
                ChannelSecond.call_count += 1
                return True

        manager = NotificationManager()
        manager.add_channel(ChannelFirst())
        manager.add_channel(ChannelSecond())

        msg = NotificationMessage(title="정보", body="body", level=NotificationLevel.INFO)
        run_async(manager.send_with_escalation(msg))

        assert ChannelFirst.call_count == 1
        assert ChannelSecond.call_count == 0


# ---------------------------------------------------------------------------
# TestRetrySync
# ---------------------------------------------------------------------------

class TestRetrySync:
    def test_succeeds_first_try(self):
        call_count = 0

        @retry_sync(max_retries=3, base_delay=0.0)
        def always_succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert always_succeeds() == "ok"
        assert call_count == 1

    def test_raises_after_max_retries(self):
        call_count = 0

        @retry_sync(max_retries=2, base_delay=0.0)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("영구 오류")

        with pytest.raises(ValueError):
            always_fails()
        assert call_count == 3

    def test_exponential_backoff(self):
        """지연 시간이 지수적으로 증가하는지 확인"""
        sleep_calls = []

        @retry_sync(max_retries=3, base_delay=1.0, max_delay=30.0)
        def always_fails():
            raise RuntimeError("오류")

        with patch("src.utils.time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError):
                always_fails()
            delays = [c.args[0] for c in mock_sleep.call_args_list]

        assert delays == [1.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# TestStructuredLogging
# ---------------------------------------------------------------------------

class TestStructuredLogging:
    def test_creates_log_directory(self, tmp_path):
        """로그 디렉토리가 없으면 자동 생성"""
        log_dir = str(tmp_path / "nested" / "logs")
        log = setup_structured_logging("test_dir_creation", log_dir=log_dir)
        assert Path(log_dir).exists()
        # 핸들러 정리
        for h in log.handlers[:]:
            h.close()
            log.removeHandler(h)

    def test_log_file_created(self, tmp_path):
        """로그 파일이 실제로 생성되는지 확인"""
        log_dir = str(tmp_path / "logs")
        log = setup_structured_logging("test_file_created", log_dir=log_dir)
        log.info("테스트 로그 메시지")
        # 파일 핸들러를 닫아 버퍼 플러시
        for h in log.handlers[:]:
            h.flush()
            h.close()
            log.removeHandler(h)
        log_file = Path(log_dir) / "test_file_created.log"
        assert log_file.exists()

    def test_console_and_file_handlers(self, tmp_path):
        """콘솔 핸들러와 파일 핸들러 모두 붙어있는지 확인"""
        import logging.handlers as lh

        log_dir = str(tmp_path / "logs")
        log = setup_structured_logging("test_handlers", log_dir=log_dir)

        handler_types = [type(h) for h in log.handlers]
        assert logging.StreamHandler in handler_types
        assert lh.TimedRotatingFileHandler in handler_types

        for h in log.handlers[:]:
            h.close()
            log.removeHandler(h)

    def test_returns_logger_instance(self, tmp_path):
        """반환값이 logging.Logger 인스턴스인지 확인"""
        log_dir = str(tmp_path / "logs")
        log = setup_structured_logging("test_instance", log_dir=log_dir)
        assert isinstance(log, logging.Logger)
        for h in log.handlers[:]:
            h.close()
            log.removeHandler(h)

    def test_no_duplicate_handlers_on_repeated_call(self, tmp_path):
        """같은 이름으로 두 번 호출해도 핸들러가 중복되지 않음"""
        log_dir = str(tmp_path / "logs")
        log1 = setup_structured_logging("test_no_dup", log_dir=log_dir)
        handler_count_1 = len(log1.handlers)
        log2 = setup_structured_logging("test_no_dup", log_dir=log_dir)
        handler_count_2 = len(log2.handlers)
        # 이미 핸들러가 있으므로 두 번째 호출에서 추가되지 않아야 함
        assert handler_count_2 == handler_count_1
        for h in log1.handlers[:]:
            h.close()
            log1.removeHandler(h)
