#!/usr/bin/env python3
"""
주간 리포트 생성 및 전송
- 신규 시그널
- 청산된 거래
- 현재 포지션
- 리스크 상태
- 주간 손익
"""

import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from src.data_store import ParquetDataStore
from src.notifier import NotificationLevel, NotificationMessage
from src.position_tracker import PositionStatus, PositionTracker
from src.risk_manager import PortfolioRiskManager
from src.script_helpers import load_config, setup_notifier, setup_risk_manager
from src.universe_manager import UniverseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_week_start() -> datetime:
    """월요일 00:00을 기준으로 주간 시작점 반환"""
    today = datetime.now()
    # 월요일이 0, 일요일이 6
    days_since_monday = today.weekday()
    week_start = today - timedelta(days=days_since_monday)
    # 시간을 00:00:00으로 설정
    return week_start.replace(hour=0, minute=0, second=0, microsecond=0)


def get_signals_this_week(data_store: ParquetDataStore) -> List[Dict]:
    """이번 주의 신규 시그널 조회"""
    week_start = get_week_start()

    try:
        all_signals_df = data_store.load_signals()
        if all_signals_df.empty:
            return []
        all_signals = all_signals_df.to_dict(orient="records")
    except Exception as e:
        logger.warning(f"시그널 로드 실패: {e}")
        return []

    week_signals = []
    for signal in all_signals:
        try:
            if isinstance(signal.get("date"), str):
                signal_date = datetime.fromisoformat(signal["date"])
            elif isinstance(signal.get("timestamp"), str):
                signal_date = datetime.fromisoformat(signal["timestamp"])
            else:
                continue

            if signal_date >= week_start:
                week_signals.append(signal)
        except (ValueError, KeyError):
            continue

    return sorted(week_signals, key=lambda s: s.get("date") or s.get("timestamp"), reverse=True)


def get_closed_trades_this_week(tracker: PositionTracker) -> List:
    """이번 주에 청산된 거래 조회"""
    week_start = get_week_start()
    all_positions = tracker.get_all_positions()

    closed_this_week = []
    for pos in all_positions:
        if pos.status != PositionStatus.CLOSED.value:
            continue

        if pos.exit_date is None:
            continue

        try:
            exit_date = datetime.fromisoformat(pos.exit_date)
            if exit_date >= week_start:
                closed_this_week.append(pos)
        except (ValueError, TypeError):
            continue

    return sorted(closed_this_week, key=lambda p: p.exit_date, reverse=True)


def format_signals_summary(signals: List[Dict], get_display_name=None) -> str:
    """신규 시그널 요약"""
    if not signals:
        return "없음"

    summary_lines = []
    for signal in signals[:5]:  # 최근 5개만
        raw = signal.get("symbol", "N/A")
        symbol = get_display_name(raw) if get_display_name else raw
        direction = signal.get("direction", "N/A")
        price = signal.get("price", "N/A")
        summary_lines.append(f"  • {symbol} {direction} @ {price}")

    if len(signals) > 5:
        summary_lines.append(f"  ... and {len(signals) - 5} more")

    return "\n".join(summary_lines)


def format_closed_trades_summary(trades: List, get_display_name=None) -> str:
    """청산된 거래 요약"""
    if not trades:
        return "없음"

    summary_lines = []
    total_pnl = 0.0

    for trade in trades[:5]:  # 최근 5개만
        symbol = get_display_name(trade.symbol) if get_display_name else trade.symbol
        pnl = trade.pnl if trade.pnl else 0.0
        total_pnl += pnl

        pnl_str = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
        reason = trade.exit_reason or "Exit Signal"
        summary_lines.append(f"  • {symbol}: {pnl_str} ({reason})")

    if len(trades) > 5:
        summary_lines.append(f"  ... and {len(trades) - 5} more")

    # 주간 합계
    all_pnl = sum(t.pnl for t in trades if t.pnl)
    summary_lines.append(f"\n  주간 합계: ${all_pnl:+,.0f}")

    return "\n".join(summary_lines)


def format_open_positions_summary(positions: List, get_display_name=None) -> str:
    """오픈 포지션 요약"""
    if not positions:
        return "없음"

    summary_lines = []
    for pos in positions:
        symbol = get_display_name(pos.symbol) if get_display_name else pos.symbol
        direction = pos.direction
        units = pos.units
        summary_lines.append(f"  • {symbol} {direction.value} ({units}U)")

    return "\n".join(summary_lines)


def format_risk_summary(risk_manager: PortfolioRiskManager, positions: List) -> str:
    """리스크 상태 요약"""
    # 리스크 상태 로드
    for pos in positions:
        risk_manager.add_position(pos.symbol, pos.units, pos.entry_n, pos.direction)

    summary = risk_manager.get_risk_summary()

    lines = [
        f"  롱 유닛: {summary['long_units']}/12",
        f"  숏 유닛: {summary['short_units']}/12",
        f"  활성 포지션: {summary['positions_count']}",
        f"  총 N 노출: {summary['total_n_exposure']:.1f}/10.0",
    ]

    return "\n".join(lines)


async def main(args):
    """메인 함수"""
    logger.info("=== 주간 리포트 생성 ===")

    # 필수 컴포넌트 로드
    config = load_config()
    tracker = PositionTracker()
    data_store = ParquetDataStore()
    risk_manager = setup_risk_manager()
    notifier = setup_notifier(config)

    # 유니버스 매니저
    universe_yaml = Path(__file__).parent.parent / "config" / "universe.yaml"
    if universe_yaml.exists():
        universe = UniverseManager(yaml_path=str(universe_yaml))
    else:
        universe = UniverseManager()

    # 데이터 수집
    try:
        signals = get_signals_this_week(data_store)
        closed_trades = get_closed_trades_this_week(tracker)
        open_positions = tracker.get_open_positions()

        logger.info(f"신규 시그널: {len(signals)}개")
        logger.info(f"청산된 거래: {len(closed_trades)}개")
        logger.info(f"오픈 포지션: {len(open_positions)}개")

    except Exception as e:
        logger.error(f"데이터 수집 오류: {e}")
        return

    # 주간 리포트 본문 구성
    week_start = get_week_start()
    _week_end = week_start + timedelta(days=7)

    report_body = f"""
📊 **WEEKLY TRADING REPORT**

기간: {week_start.strftime("%Y-%m-%d")} ~ {datetime.now().strftime("%Y-%m-%d")}

🆕 **NEW SIGNALS**
{format_signals_summary(signals, universe.get_display_name)}

💰 **CLOSED TRADES**
{format_closed_trades_summary(closed_trades, universe.get_display_name)}

📈 **OPEN POSITIONS**
{format_open_positions_summary(open_positions, universe.get_display_name)}

⚠️  **RISK STATUS**
{format_risk_summary(risk_manager, open_positions)}

---
생성 시간: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    # 출력
    if args.verbose:
        print(report_body)

    # 알림 전송
    if args.send:
        logger.info("Telegram 채널로 주간 리포트 전송 중...")
        await notifier.send_message(
            NotificationMessage(title="Weekly Trading Report", body=report_body, level=NotificationLevel.INFO)
        )
        logger.info("주간 리포트 전송 완료")
    else:
        logger.info("--send 플래그가 없어서 알림 전송을 건너뜁니다")

    logger.info("=== 리포트 생성 완료 ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="주간 리포트 생성 및 전송")
    parser.add_argument("--send", action="store_true", help="실제로 알림 전송 (기본값: 전송 안함, 미리보기만)")
    parser.add_argument("--verbose", action="store_true", help="상세 로깅 및 리포트 출력")

    args = parser.parse_args()
    asyncio.run(main(args))
