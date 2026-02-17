#!/usr/bin/env python3
"""
통합 포지션 & 시그널 체크 스크립트
- 신규 진입 시그널
- 오픈 포지션 청산 시그널
- 피라미딩 기회
- 스톱로스 체크
"""

import sys
import os
import asyncio
import fcntl
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_fetcher import DataFetcher
from src.data_store import ParquetDataStore
from src.indicators import add_turtle_indicators
from src.position_tracker import PositionTracker, SignalType
from src.notifier import (
    NotificationManager,
    TelegramChannel,
    NotificationMessage,
    NotificationLevel
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

LOCK_FILE = Path(__file__).parent.parent / "data" / ".check_positions.lock"


def acquire_lock():
    """중복 실행 방지를 위한 파일 잠금"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
        return fd
    except IOError:
        fd.close()
        logger.warning("이미 다른 인스턴스가 실행 중입니다. 종료합니다.")
        return None


def release_lock(fd):
    """파일 잠금 해제"""
    if fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        except Exception:
            pass


def load_config():
    """환경 변수에서 설정 로드"""
    import os
    from dotenv import load_dotenv
    load_dotenv()

    return {
        "telegram_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
    }


def setup_notifier(config: dict) -> NotificationManager:
    """알림 채널 설정"""
    notifier = NotificationManager()

    if config.get("telegram_token") and config.get("telegram_chat_id"):
        notifier.add_channel(TelegramChannel(
            config["telegram_token"],
            config["telegram_chat_id"]
        ))
        logger.info("Telegram 채널 활성화")

    return notifier


def check_entry_signals(df, symbol: str, system: int = 1) -> list:
    """진입 시그널 확인"""
    signals = []
    if len(df) < 2:
        return signals

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    # System 1: 20일, System 2: 55일
    if system == 1:
        high_col = "dc_high_20"
    else:
        high_col = "dc_high_55"

    # 롱 진입 시그널
    if today["high"] > yesterday[high_col]:
        signals.append({
            "symbol": symbol,
            "type": SignalType.ENTRY_LONG.value,
            "system": system,
            "direction": "LONG",
            "price": yesterday[high_col],
            "current": today["close"],
            "n": today["N"],
            "stop_loss": yesterday[high_col] - (2 * today["N"]),
            "date": today["date"].strftime('%Y-%m-%d'),
            "message": f"System {system} 롱 진입: {yesterday[high_col]:.2f} 돌파"
        })

    return signals


def check_exit_signals(df, position, system: int = 1) -> Optional[dict]:
    """청산 시그널 확인"""
    if len(df) < 2:
        return None

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    # System 1: 10일 저가, System 2: 20일 저가
    if system == 1:
        low_col = "dc_low_10"
    else:
        low_col = "dc_low_20"

    # 롱 포지션 청산 (저가 이탈)
    if position.direction == "LONG" and today["low"] < yesterday[low_col]:
        return {
            "symbol": position.symbol,
            "type": SignalType.EXIT_LONG.value,
            "system": system,
            "position_id": position.position_id,
            "price": yesterday[low_col],
            "current": today["close"],
            "n": today["N"],
            "date": today["date"].strftime('%Y-%m-%d'),
            "message": f"System {system} 롱 청산: {yesterday[low_col]:.2f} 이탈"
        }

    return None


async def main():
    lock_fd = acquire_lock()
    if lock_fd is None:
        return

    try:
        await _run_checks()
    finally:
        release_lock(lock_fd)


async def _run_checks():
    logger.info("=== 통합 포지션 & 시그널 체크 시작 ===")

    config = load_config()
    notifier = setup_notifier(config)
    data_fetcher = DataFetcher()
    data_store = ParquetDataStore()
    tracker = PositionTracker()

    # 테스트용 종목 리스트
    test_symbols = [
        'SPY', 'QQQ', 'AAPL', 'NVDA', 'TSLA',  # 미국
        ('005930.KS', '삼성전자'),
        ('000660.KS', 'SK하이닉스'),
        ('035420.KS', 'NAVER')
    ]

    # 1. 오픈 포지션 체크 (청산 & 피라미딩)
    open_positions = tracker.get_open_positions()
    logger.info(f"오픈 포지션: {len(open_positions)}개")

    for pos in open_positions:
        try:
            logger.info(f"체크: {pos.symbol} (System {pos.system})")

            # 데이터 페칭
            df = data_fetcher.fetch(pos.symbol, period="6mo")
            if df.empty:
                continue

            df = add_turtle_indicators(df)
            if len(df) < 2:
                continue

            today = df.iloc[-1]

            # 스톱로스 체크
            if pos.direction == "LONG" and today["low"] <= pos.stop_loss:
                logger.warning(f"스톱로스 발동: {pos.symbol} @ {today['low']}")
                tracker.close_position(pos.position_id, pos.stop_loss, "Stop Loss")
                await notifier.send_signal(
                    symbol=pos.symbol,
                    action="🛑 STOP LOSS",
                    price=pos.stop_loss,
                    quantity=pos.total_shares,
                    reason=f"스톱로스 발동 (진입가: {pos.entry_price:,.0f})"
                )
                continue

            # 청산 시그널 체크
            exit_signal = check_exit_signals(df, pos, pos.system)
            if exit_signal:
                logger.info(f"청산 시그널: {pos.symbol}")
                tracker.close_position(
                    pos.position_id,
                    exit_signal['price'],
                    exit_signal['message']
                )
                await notifier.send_signal(
                    symbol=pos.symbol,
                    action=f"EXIT System {pos.system}",
                    price=exit_signal['price'],
                    quantity=pos.total_shares,
                    reason=exit_signal['message']
                )
                data_store.save_signal(exit_signal)
                continue

            # 피라미딩 기회 체크
            if tracker.should_pyramid(pos, today["close"]):
                logger.info(f"피라미딩 기회: {pos.symbol}")
                await notifier.send_signal(
                    symbol=pos.symbol,
                    action=f"📈 PYRAMID System {pos.system}",
                    price=today["close"],
                    quantity=0,
                    reason=f"0.5N 상승 (Level {pos.units} → {pos.units + 1})"
                )

        except Exception as e:
            logger.error(f"{pos.symbol} 처리 오류: {e}")

    # 2. 신규 진입 시그널 체크
    all_signals = []

    for item in test_symbols:
        if isinstance(item, tuple):
            symbol, name = item
        else:
            symbol = name = item

        try:
            logger.info(f"시그널 체크: {name}")

            # 이미 오픈 포지션이 있는지 확인
            existing = tracker.get_open_positions(symbol)
            if existing:
                logger.info(f"이미 포지션 보유 중: {symbol}")
                continue

            # 데이터 페칭
            df = data_fetcher.fetch(symbol, period="6mo")
            if df.empty:
                continue

            df = add_turtle_indicators(df)

            # System 1 & 2 시그널 체크
            signals_s1 = check_entry_signals(df, symbol, system=1)
            signals_s2 = check_entry_signals(df, symbol, system=2)

            all_signals.extend(signals_s1)
            all_signals.extend(signals_s2)

        except Exception as e:
            logger.error(f"{symbol} 처리 오류: {e}")

    # 3. 신규 시그널 알림
    if all_signals:
        logger.info(f"신규 시그널: {len(all_signals)}개")

        for signal in all_signals:
            # 시그널 저장
            data_store.save_signal({
                **signal,
                "timestamp": datetime.now().isoformat()
            })

            # 알림 전송
            await notifier.send_signal(
                symbol=signal["symbol"],
                action=f"System {signal['system']} {signal['direction']}",
                price=signal["price"],
                quantity=0,
                reason=signal["message"] + f" (N={signal['n']:.2f}, SL={signal['stop_loss']:.2f})"
            )

    else:
        logger.info("신규 시그널 없음")

    # 4. 요약 리포트
    summary = tracker.get_summary()
    logger.info(f"포지션 요약: {summary}")

    logger.info("=== 체크 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
