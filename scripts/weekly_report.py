#!/usr/bin/env python3
"""
주간 리포트 생성 및 전송
- 신규 시그널
- 청산된 거래
- 현재 포지션
- 리스크 상태
- 주간 손익
"""

import sys
import os
import asyncio
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

try:
    import yaml
except ImportError:
    yaml = None
    logging.getLogger(__name__).warning("pyyaml 미설치. YAML 설정 파일을 사용할 수 없습니다.")

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(): pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.position_tracker import PositionTracker, PositionStatus
from src.data_store import ParquetDataStore
from src.risk_manager import PortfolioRiskManager, AssetGroup, Direction, RiskLimits
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


def load_config():
    """환경 변수에서 설정 로드"""
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


def setup_risk_manager() -> PortfolioRiskManager:
    """리스크 매니저 설정"""
    config_path = Path(__file__).parent.parent / "config" / "correlation_groups.yaml"
    symbol_groups = {}

    if not config_path.exists() or yaml is None:
        logger.warning(f"상관그룹 설정 파일 없음 또는 yaml 미설치: {config_path}")
        return PortfolioRiskManager(symbol_groups=symbol_groups)

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        if not config or 'groups' not in config:
            return PortfolioRiskManager(symbol_groups=symbol_groups)

        group_mapping = {
            'kr_equity': AssetGroup.KR_EQUITY,
            'us_equity': AssetGroup.US_EQUITY,
            'us_etf': AssetGroup.US_EQUITY,
            'crypto': AssetGroup.CRYPTO,
            'commodity': AssetGroup.COMMODITY,
            'bond': AssetGroup.BOND,
        }

        for group_name, symbols in config.get('groups', {}).items():
            asset_group = group_mapping.get(group_name, AssetGroup.US_EQUITY)
            for symbol in symbols:
                symbol_groups[symbol] = asset_group

        logger.info(f"상관그룹 설정 로드: {len(symbol_groups)}개 심볼")

    except yaml.YAMLError as e:
        logger.error(f"상관그룹 YAML 파싱 오류: {e}")

    return PortfolioRiskManager(symbol_groups=symbol_groups)


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


def format_signals_summary(signals: List[Dict]) -> str:
    """신규 시그널 요약"""
    if not signals:
        return "없음"

    summary_lines = []
    for signal in signals[:5]:  # 최근 5개만
        symbol = signal.get("symbol", "N/A")
        direction = signal.get("direction", "N/A")
        price = signal.get("price", "N/A")
        summary_lines.append(f"  • {symbol} {direction} @ {price}")

    if len(signals) > 5:
        summary_lines.append(f"  ... and {len(signals) - 5} more")

    return "\n".join(summary_lines)


def format_closed_trades_summary(trades: List) -> str:
    """청산된 거래 요약"""
    if not trades:
        return "없음"

    summary_lines = []
    total_pnl = 0.0

    for trade in trades[:5]:  # 최근 5개만
        symbol = trade.symbol
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


def format_open_positions_summary(positions: List) -> str:
    """오픈 포지션 요약"""
    if not positions:
        return "없음"

    summary_lines = []
    for pos in positions:
        symbol = pos.symbol
        direction = pos.direction
        units = pos.units
        summary_lines.append(f"  • {symbol} {direction} ({units}U)")

    return "\n".join(summary_lines)


def format_risk_summary(risk_manager: PortfolioRiskManager, positions: List) -> str:
    """리스크 상태 요약"""
    # 리스크 상태 로드
    for pos in positions:
        direction = Direction.LONG if pos.direction == "LONG" else Direction.SHORT
        risk_manager.add_position(pos.symbol, pos.units, pos.entry_n, direction)

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
    week_end = week_start + timedelta(days=7)

    report_body = f"""
📊 **WEEKLY TRADING REPORT**

기간: {week_start.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}

🆕 **NEW SIGNALS**
{format_signals_summary(signals)}

💰 **CLOSED TRADES**
{format_closed_trades_summary(closed_trades)}

📈 **OPEN POSITIONS**
{format_open_positions_summary(open_positions)}

⚠️  **RISK STATUS**
{format_risk_summary(risk_manager, open_positions)}

---
생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    # 출력
    if args.verbose:
        print(report_body)

    # 알림 전송
    if args.send:
        logger.info("Telegram 채널로 주간 리포트 전송 중...")
        await notifier.send_message(NotificationMessage(
            title="Weekly Trading Report",
            body=report_body,
            level=NotificationLevel.INFO
        ))
        logger.info("주간 리포트 전송 완료")
    else:
        logger.info("--send 플래그가 없어서 알림 전송을 건너뜁니다")

    logger.info("=== 리포트 생성 완료 ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="주간 리포트 생성 및 전송")
    parser.add_argument(
        "--send",
        action="store_true",
        help="실제로 알림 전송 (기본값: 전송 안함, 미리보기만)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 로깅 및 리포트 출력"
    )

    args = parser.parse_args()
    asyncio.run(main(args))
