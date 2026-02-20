#!/usr/bin/env python3
"""
통합 포지션 & 시그널 체크 스크립트
- 신규 진입 시그널
- 오픈 포지션 청산 시그널
- 피라미딩 기회
- 스톱로스 체크
"""

import asyncio
import fcntl
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from src.data_fetcher import DataFetcher
from src.data_store import ParquetDataStore
from src.indicators import add_turtle_indicators
from src.inverse_filter import InverseETFFilter
from src.market_calendar import get_market_status, infer_market, should_check_signals
from src.notifier import NotificationManager, TelegramChannel
from src.position_tracker import PositionTracker
from src.risk_manager import PortfolioRiskManager
from src.types import AssetGroup, Direction, SignalType
from src.universe_manager import UniverseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

LOCK_FILE = Path(__file__).parent.parent / "data" / ".check_positions.lock"


def acquire_lock():
    """중복 실행 방지를 위한 파일 잠금"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK_FILE, "w")
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
        notifier.add_channel(TelegramChannel(config["telegram_token"], config["telegram_chat_id"]))
        logger.info("Telegram 채널 활성화")

    return notifier


def setup_risk_manager() -> PortfolioRiskManager:
    """리스크 매니저 설정"""
    config_path = Path(__file__).parent.parent / "config" / "correlation_groups.yaml"
    symbol_groups = {}

    if not config_path.exists():
        logger.warning(f"상관그룹 설정 파일 없음: {config_path}. 기본 그룹으로 운영합니다.")
        return PortfolioRiskManager(symbol_groups=symbol_groups)

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        if not config or "groups" not in config:
            logger.warning("상관그룹 설정이 비어있습니다.")
            return PortfolioRiskManager(symbol_groups=symbol_groups)

        group_mapping = {
            "kr_equity": AssetGroup.KR_EQUITY,
            "us_equity": AssetGroup.US_EQUITY,
            "us_etf": AssetGroup.US_EQUITY,
            "us_tech": AssetGroup.US_EQUITY,
            "crypto": AssetGroup.CRYPTO,
            "commodity": AssetGroup.COMMODITY,
            "bond": AssetGroup.BOND,
            "inverse": AssetGroup.INVERSE,
        }

        for group_name, symbols in config.get("groups", {}).items():
            asset_group = group_mapping.get(group_name, AssetGroup.US_EQUITY)
            for symbol in symbols:
                symbol_groups[symbol] = asset_group

        logger.info(f"상관그룹 설정 로드: {len(symbol_groups)}개 심볼")

    except yaml.YAMLError as e:
        logger.error(f"상관그룹 YAML 파싱 오류: {e}. 기본 그룹으로 운영합니다.")

    return PortfolioRiskManager(symbol_groups=symbol_groups)


def is_korean_market(symbol: str) -> bool:
    """한국 시장 종목 여부 (공매도 제한)"""
    return symbol.endswith(".KS") or symbol.endswith(".KQ")


def _should_allow_entry(system: int, is_profitable: bool, is_55day_breakout: bool) -> bool:
    """System 1 필터 판단 (LONG/SHORT 공용)

    Curtis Faith 원칙:
    - System 2는 필터 없음 → 항상 진입 허용
    - 직전 거래가 손실이면 진입 허용
    - 직전 거래가 수익이면 20일 돌파 스킵, 단 55일 돌파는 failsafe 진입 허용
    """
    if system != 1:
        return True  # System 2는 필터 없음
    if not is_profitable:
        return True
    if is_55day_breakout:
        return True  # 55일 failsafe override
    return False


def check_entry_signals(df, symbol: str, system: int = 1, tracker: "PositionTracker" = None) -> list:
    """진입 시그널 확인"""
    signals = []
    if len(df) < 2:
        return signals

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    # System 1 필터: 직전 거래가 수익이면 스킵 (Curtis Faith 원칙)
    # System 2는 필터 없음
    def _was_last_trade_profitable(sym: str, sys_num: int) -> bool:
        if tracker is None or sys_num != 1:
            return False
        history = tracker.get_position_history(sym)
        # System 1에서 청산된 거래만 필터링
        closed_s1 = [p for p in history if p.system == 1 and p.status == "closed"]
        if not closed_s1:
            return False
        last_trade = max(closed_s1, key=lambda p: p.exit_date or "")
        return (last_trade.pnl or 0) > 0

    # System 1: 20일, System 2: 55일
    if system == 1:
        high_col = "dc_high_20"
    else:
        high_col = "dc_high_55"

    # 롱 진입 시그널
    if today["high"] > yesterday[high_col]:
        is_profitable = _was_last_trade_profitable(symbol, system)
        is_55day_long = today["high"] > yesterday.get("dc_high_55", float("inf"))
        allow_entry = _should_allow_entry(system, is_profitable, is_55day_long)

        if is_profitable:
            if allow_entry:
                logger.info(f"System 1 필터: {symbol} 55일 failsafe override → 롱 진입 허용")
            else:
                logger.info(f"System 1 필터: {symbol} 직전 거래 수익 → 롱 진입 스킵")

        if allow_entry:
            signals.append(
                {
                    "symbol": symbol,
                    "type": SignalType.ENTRY_LONG.value,
                    "system": system,
                    "direction": "LONG",
                    "price": yesterday[high_col],
                    "current": today["close"],
                    "n": today["N"],
                    "stop_loss": yesterday[high_col] - (2 * today["N"]),
                    "date": today["date"].strftime("%Y-%m-%d"),
                    "message": f"System {system} 롱 진입: {yesterday[high_col]:.2f} 돌파",
                }
            )

    # 숏 진입 시그널 (미국 시장만 — 한국은 공매도 제한)
    if not is_korean_market(symbol):
        if system == 1:
            short_low_col = "dc_low_20"
        else:
            short_low_col = "dc_low_55"

        if today["low"] < yesterday[short_low_col]:
            is_profitable = _was_last_trade_profitable(symbol, system)
            is_55day_short = today["low"] < yesterday.get("dc_low_55", 0)
            allow_short_entry = _should_allow_entry(system, is_profitable, is_55day_short)

            if is_profitable:
                if allow_short_entry:
                    logger.info(f"System 1 필터: {symbol} 55일 failsafe override → 숏 진입 허용")
                else:
                    logger.info(f"System 1 필터: {symbol} 직전 거래 수익 → 숏 진입 스킵")

            if allow_short_entry:
                signals.append(
                    {
                        "symbol": symbol,
                        "type": SignalType.ENTRY_SHORT.value,
                        "system": system,
                        "direction": "SHORT",
                        "price": yesterday[short_low_col],
                        "current": today["close"],
                        "n": today["N"],
                        "stop_loss": yesterday[short_low_col] + (2 * today["N"]),  # 숏 스톱은 위로
                        "date": today["date"].strftime("%Y-%m-%d"),
                        "message": f"System {system} 숏 진입: {yesterday[short_low_col]:.2f} 이탈",
                    }
                )

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
            "date": today["date"].strftime("%Y-%m-%d"),
            "message": f"System {system} 롱 청산: {yesterday[low_col]:.2f} 이탈",
        }

    # 숏 포지션 청산 (고가 돌파)
    if position.direction == "SHORT":
        if system == 1:
            short_high_col = "dc_high_10"
        else:
            short_high_col = "dc_high_20"

        if today["high"] > yesterday[short_high_col]:
            return {
                "symbol": position.symbol,
                "type": SignalType.EXIT_SHORT.value,
                "system": system,
                "position_id": position.position_id,
                "price": yesterday[short_high_col],
                "current": today["close"],
                "n": today["N"],
                "date": today["date"].strftime("%Y-%m-%d"),
                "message": f"System {system} 숏 청산: {yesterday[short_high_col]:.2f} 돌파",
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

    # Log market status
    for market in ["KR", "US"]:
        logger.info(get_market_status(market))

    config = load_config()
    notifier = setup_notifier(config)
    data_fetcher = DataFetcher()
    data_store = ParquetDataStore()
    tracker = PositionTracker()
    risk_manager = setup_risk_manager()

    # 유니버스 매니저에서 심볼 로드
    universe_yaml = Path(__file__).parent.parent / "config" / "universe.yaml"
    if universe_yaml.exists():
        universe = UniverseManager(yaml_path=str(universe_yaml))
    else:
        universe = UniverseManager()  # defaults

    all_symbols_list = []
    for symbol in universe.get_enabled_symbols():
        asset = universe.assets.get(symbol)
        if asset and asset.name != symbol:
            all_symbols_list.append((symbol, asset.name))
        else:
            all_symbols_list.append(symbol)

    # 1. 오픈 포지션 체크 (청산 & 피라미딩)
    open_positions = tracker.get_open_positions()
    logger.info(f"오픈 포지션: {len(open_positions)}개")

    # Load current open positions into risk manager
    for pos in open_positions:
        direction = Direction.LONG if pos.direction == "LONG" else Direction.SHORT
        risk_manager.add_position(pos.symbol, pos.units, pos.entry_n, direction)

    # Inverse ETF 필터 초기화
    inverse_filter = InverseETFFilter()

    # 오픈 포지션 중 inverse ETF를 필터에 등록
    for pos in open_positions:
        if inverse_filter.is_inverse_etf(pos.symbol):
            inverse_filter.on_entry(
                pos.symbol,
                entry_date=datetime.strptime(pos.entry_date, "%Y-%m-%d")
                if isinstance(pos.entry_date, str)
                else pos.entry_date,
                inverse_price=pos.entry_price,
                underlying_price=pos.entry_price,  # 진입 시점 기초자산 가격은 근사값 사용
            )
            # 보유일은 inverse_filter가 entry_date 기반으로 자동 계산

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

            # 스톱로스 체크 — 현재 포지션 단위로 직접 비교
            # LONG: today["low"]으로 체크 (장중 최악), SHORT: today["high"]으로 체크
            check_price = today["low"] if pos.direction == "LONG" else today["high"]
            stop_triggered = (pos.direction == "LONG" and check_price <= pos.stop_loss) or (
                pos.direction == "SHORT" and check_price >= pos.stop_loss
            )

            if stop_triggered:
                logger.warning(f"스톱로스 발동: {pos.symbol} ({pos.direction}) @ {today['close']}")
                tracker.close_position(pos.position_id, pos.stop_loss, "Stop Loss")
                direction = Direction.LONG if pos.direction == "LONG" else Direction.SHORT
                risk_manager.remove_position(pos.symbol, pos.units, direction, n_value=pos.entry_n)
                await notifier.send_signal(
                    symbol=pos.symbol,
                    action="🛑 STOP LOSS",
                    price=pos.stop_loss,
                    quantity=pos.total_shares,
                    reason=f"스톱로스 발동 ({pos.direction}, 진입가: {pos.entry_price:,.0f})",
                )
                continue

            # Inverse ETF 괴리율/보유일 체크
            if inverse_filter.is_inverse_etf(pos.symbol):
                inv_config = inverse_filter.get_config(pos.symbol)
                if inv_config:
                    underlying_symbol = inv_config.underlying
                    underlying_df = data_fetcher.fetch(underlying_symbol, period="1mo")
                    if not underlying_df.empty:
                        underlying_price = underlying_df.iloc[-1]["close"]
                        # 일별 업데이트 (괴리율 계산 반영)
                        inverse_filter.on_daily_update(pos.symbol, today["close"], underlying_price)
                        should_exit, reason, msg = inverse_filter.should_force_exit(
                            pos.symbol, today["close"], underlying_price
                        )
                        if should_exit:
                            logger.warning(f"Inverse ETF 강제 청산: {pos.symbol} - {reason}")
                            tracker.close_position(pos.position_id, today["close"], f"Inverse Filter: {msg}")
                            direction = Direction.LONG if pos.direction == "LONG" else Direction.SHORT
                            risk_manager.remove_position(pos.symbol, pos.units, direction, n_value=pos.entry_n)
                            await notifier.send_signal(
                                symbol=pos.symbol,
                                action="INVERSE ETF EXIT",
                                price=today["close"],
                                quantity=pos.total_shares,
                                reason=msg,
                            )
                            continue

            # 청산 시그널 체크
            exit_signal = check_exit_signals(df, pos, pos.system)
            if exit_signal:
                logger.info(f"청산 시그널: {pos.symbol}")
                tracker.close_position(pos.position_id, exit_signal["price"], exit_signal["message"])
                direction = Direction.LONG if pos.direction == "LONG" else Direction.SHORT
                risk_manager.remove_position(pos.symbol, pos.units, direction, n_value=pos.entry_n)
                await notifier.send_signal(
                    symbol=pos.symbol,
                    action=f"EXIT System {pos.system}",
                    price=exit_signal["price"],
                    quantity=pos.total_shares,
                    reason=exit_signal["message"],
                )
                data_store.save_signal(exit_signal)
                continue

            # 피라미딩 기회 체크
            if tracker.should_pyramid(pos, today["close"]):
                logger.info(f"피라미딩 기회: {pos.symbol}")
                direction_text = "상승" if pos.direction == "LONG" else "하락"
                await notifier.send_signal(
                    symbol=pos.symbol,
                    action=f"📈 PYRAMID System {pos.system}",
                    price=today["close"],
                    quantity=0,
                    reason=f"0.5N {direction_text} (Level {pos.units} → {pos.units + 1})",
                )

        except Exception as e:
            logger.error(f"{pos.symbol} 처리 오류: {e}")

    # 2. 신규 진입 시그널 체크
    all_signals = []

    for item in all_symbols_list:
        if isinstance(item, tuple):
            symbol, name = item
        else:
            symbol = name = item

        try:
            logger.info(f"시그널 체크: {name}")

            # 마켓 활성 시간 체크
            if not should_check_signals(symbol):
                logger.info(f"마켓 비활동 시간: {symbol} ({infer_market(symbol)}) 스킵")
                continue

            # 데이터 페칭
            df = data_fetcher.fetch(symbol, period="6mo")
            if df.empty:
                continue

            df = add_turtle_indicators(df)

            # System 1/2 독립 운영 - 각 시스템별로 기존 포지션 확인
            existing_positions = tracker.get_open_positions(symbol)
            existing_systems = {p.system for p in existing_positions}

            signals_s1 = []
            signals_s2 = []

            if 1 not in existing_systems:
                signals_s1 = check_entry_signals(df, symbol, system=1, tracker=tracker)
            else:
                logger.info(f"System 1 포지션 보유 중: {symbol}")

            if 2 not in existing_systems:
                signals_s2 = check_entry_signals(df, symbol, system=2, tracker=tracker)
            else:
                logger.info(f"System 2 포지션 보유 중: {symbol}")

            # 리스크 매니저 필터링
            for signal in signals_s1 + signals_s2:
                direction = Direction.LONG if signal["direction"] == "LONG" else Direction.SHORT
                can_add, reason = risk_manager.can_add_position(
                    symbol=signal["symbol"], units=1, n_value=signal["n"], direction=direction
                )
                if can_add:
                    all_signals.append(signal)
                    # 리스크 상태 업데이트 (후속 시그널 정확한 체크를 위해)
                    risk_manager.add_position(signal["symbol"], 1, signal["n"], direction)
                else:
                    logger.info(f"리스크 제한으로 시그널 스킵: {signal['symbol']} - {reason}")

        except Exception as e:
            logger.error(f"{symbol} 처리 오류: {e}")

    # 3. 신규 시그널 알림
    if all_signals:
        logger.info(f"신규 시그널: {len(all_signals)}개")

        for signal in all_signals:
            # 시그널 저장
            data_store.save_signal({**signal, "timestamp": datetime.now().isoformat()})

            # 알림 전송
            await notifier.send_signal(
                symbol=signal["symbol"],
                action=f"System {signal['system']} {signal['direction']}",
                price=signal["price"],
                quantity=0,
                reason=signal["message"] + f" (N={signal['n']:.2f}, SL={signal['stop_loss']:.2f})",
            )

    else:
        logger.info("신규 시그널 없음")

    # 4. 요약 리포트
    summary = tracker.get_summary()
    logger.info(f"포지션 요약: {summary}")

    risk_summary = risk_manager.get_risk_summary()
    logger.info(f"리스크 요약: {risk_summary}")

    logger.info("=== 체크 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
