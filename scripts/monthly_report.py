#!/usr/bin/env python3
"""월간 성과 리포트 생성 및 전송 스크립트"""

import argparse
import asyncio
import logging
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List

from src.analytics import TradeAnalytics
from src.data_store import ParquetDataStore
from src.notifier import NotificationLevel, NotificationMessage
from src.position_tracker import PositionStatus, PositionTracker
from src.script_helpers import load_config, setup_notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def get_previous_month() -> str:
    """이전 달을 YYYY-MM 형식으로 반환"""
    today = datetime.now()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def parse_month(month_str: str) -> tuple[int, int]:
    """YYYY-MM 문자열을 (year, month) 튜플로 파싱"""
    try:
        dt = datetime.strptime(month_str, "%Y-%m")
        return dt.year, dt.month
    except ValueError as e:
        raise ValueError(f"잘못된 월 형식 '{month_str}': YYYY-MM 형식이어야 합니다.") from e


def get_month_boundaries(month_str: str) -> tuple[date, date]:
    """월의 첫째 날과 마지막 날을 반환"""
    year, month = parse_month(month_str)
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    return first_day, last_day


def filter_trades_for_month(tracker: PositionTracker, month_str: str) -> List[dict]:
    """해당 월에 청산된 거래만 필터링하여 딕셔너리 리스트로 반환"""
    first_day, last_day = get_month_boundaries(month_str)
    all_positions = tracker.get_all_positions()

    month_trades = []
    for pos in all_positions:
        if pos.status != PositionStatus.CLOSED.value:
            continue
        if pos.exit_date is None:
            continue
        try:
            exit_date = datetime.fromisoformat(pos.exit_date).date()
            if first_day <= exit_date <= last_day:
                month_trades.append(pos.to_dict())
        except (ValueError, TypeError):
            continue

    return month_trades


def get_per_symbol_pnl(trades: List[dict]) -> Dict[str, float]:
    """심볼별 손익 합계 계산"""
    symbol_pnl: Dict[str, float] = defaultdict(float)
    for trade in trades:
        symbol = trade.get("symbol", "unknown")
        pnl = trade.get("pnl", 0) or 0
        symbol_pnl[symbol] += pnl
    return {k: round(v, 2) for k, v in symbol_pnl.items()}


def build_equity_series(trades: List[dict]) -> List[float]:
    """청산 날짜순으로 누적 손익 시리즈 생성 (드로다운 계산용)"""
    sorted_trades = sorted(
        [t for t in trades if t.get("exit_date")],
        key=lambda t: t.get("exit_date", ""),
    )
    if not sorted_trades:
        return []
    equity = 0.0
    series = []
    for t in sorted_trades:
        equity += t.get("pnl", 0) or 0
        series.append(equity)
    return series


def generate_report(month_str: str, tracker: PositionTracker, data_store: ParquetDataStore) -> dict:
    """월간 리포트 데이터 생성

    Args:
        month_str: 대상 월 (YYYY-MM)
        tracker: PositionTracker 인스턴스
        data_store: ParquetDataStore 인스턴스 (미래 확장용)

    Returns:
        리포트 데이터 딕셔너리
    """
    logger.info(f"월간 리포트 생성 중: {month_str}")

    trades = filter_trades_for_month(tracker, month_str)
    trade_count = len(trades)

    # 기본 통계
    if trades:
        analytics = TradeAnalytics(trades)
        win_loss_stats = analytics.get_win_loss_stats()
        r_distribution = analytics.get_r_distribution()
        system_comparison = analytics.get_system_comparison()
        expectancy = analytics.get_expectancy()

        total_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
        win_rate = win_loss_stats["win_rate"]
        profit_factor = win_loss_stats["profit_factor"]

        # 드로다운 분석 (월 내)
        equity_series = build_equity_series(trades)
        drawdown_info = analytics.get_drawdown_analysis(equity_series) if equity_series else {}

        # 심볼별 손익
        symbol_pnl = get_per_symbol_pnl(trades)
        sorted_symbols = sorted(symbol_pnl.items(), key=lambda x: x[1], reverse=True)
        top5 = sorted_symbols[:5]
        bottom5 = sorted(symbol_pnl.items(), key=lambda x: x[1])[:5]
    else:
        win_loss_stats = {}
        r_distribution = {}
        system_comparison = {}
        expectancy = 0.0
        total_pnl = 0.0
        win_rate = 0.0
        profit_factor = 0.0
        drawdown_info = {}
        symbol_pnl = {}
        top5 = []
        bottom5 = []

    # 이전 달 비교
    year, month = parse_month(month_str)
    if month == 1:
        prev_month_str = f"{year - 1}-12"
    else:
        prev_month_str = f"{year}-{month - 1:02d}"

    prev_trades = filter_trades_for_month(tracker, prev_month_str)
    prev_total_pnl = sum(t.get("pnl", 0) or 0 for t in prev_trades)
    if prev_total_pnl != 0:
        mom_change_pct = (total_pnl - prev_total_pnl) / abs(prev_total_pnl) * 100
    else:
        mom_change_pct = None  # ZeroDivisionError 방지

    return {
        "month": month_str,
        "trade_count": trade_count,
        "total_pnl": round(total_pnl, 2),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "win_loss_stats": win_loss_stats,
        "r_distribution": r_distribution,
        "system_comparison": system_comparison,
        "drawdown_info": drawdown_info,
        "top5_symbols": top5,
        "bottom5_symbols": bottom5,
        "prev_month": prev_month_str,
        "prev_total_pnl": round(prev_total_pnl, 2),
        "mom_change_pct": mom_change_pct,
    }


def format_report(report_data: dict) -> str:
    """리포트 데이터를 마크다운 텍스트(한국어)로 포맷"""
    month = report_data["month"]
    trade_count = report_data["trade_count"]
    total_pnl = report_data["total_pnl"]
    win_rate = report_data["win_rate"]
    profit_factor = report_data["profit_factor"]
    expectancy = report_data["expectancy"]

    pnl_sign = "+" if total_pnl >= 0 else ""

    lines = [
        f"# 월간 성과 리포트 — {month}",
        "",
        "## 월별 수익률",
        f"- 청산 거래 수: {trade_count}건",
        f"- 총 손익: {pnl_sign}${total_pnl:,.2f}",
    ]

    # 전월 대비
    mom = report_data.get("mom_change_pct")
    prev_month = report_data.get("prev_month", "")
    prev_pnl = report_data.get("prev_total_pnl", 0.0)
    prev_sign = "+" if prev_pnl >= 0 else ""
    lines.append(f"- 전월({prev_month}) 손익: {prev_sign}${prev_pnl:,.2f}")
    if mom is not None:
        mom_sign = "+" if mom >= 0 else ""
        lines.append(f"- 전월 대비 변화: {mom_sign}{mom:.1f}%")
    else:
        lines.append("- 전월 대비 변화: N/A (전월 거래 없음)")

    lines += ["", "## 승률 / Profit Factor"]
    if trade_count > 0:
        stats = report_data.get("win_loss_stats", {})
        winners = stats.get("winners", 0)
        losers = stats.get("losers", 0)
        lines += [
            f"- 승률: {win_rate * 100:.1f}% ({winners}승 / {losers}패)",
            f"- Profit Factor: {profit_factor:.2f}",
            f"- 기대값 (Expectancy): {expectancy:.3f}R",
            f"- 평균 수익: ${stats.get('avg_win', 0):,.2f}",
            f"- 평균 손실: ${stats.get('avg_loss', 0):,.2f}",
        ]
    else:
        lines += [
            "- 해당 월 청산 거래 없음",
        ]

    # 드로다운
    dd = report_data.get("drawdown_info", {})
    lines += ["", "## 최대 낙폭 (월 내)"]
    if dd:
        lines += [
            f"- 최대 낙폭: ${dd.get('max_drawdown', 0):,.2f} ({dd.get('max_drawdown_pct', 0):.2f}%)",
            f"- 최대 낙폭 지속: {dd.get('max_drawdown_duration', 0)}거래",
        ]
    else:
        lines.append("- 데이터 없음")

    # 시스템 기여도
    sys_cmp = report_data.get("system_comparison", {})
    lines += ["", "## 전략 기여도 (System 1 / 2)"]
    if sys_cmp:
        s1 = sys_cmp.get("system_1", {})
        s2 = sys_cmp.get("system_2", {})
        s1_pnl = s1.get("total_pnl", 0)
        s2_pnl = s2.get("total_pnl", 0)
        s1_sign = "+" if s1_pnl >= 0 else ""
        s2_sign = "+" if s2_pnl >= 0 else ""
        lines += [
            f"- System 1: {s1.get('total_trades', 0)}건 | "
            f"승률 {s1.get('win_rate', 0) * 100:.1f}% | "
            f"손익 {s1_sign}${s1_pnl:,.2f}",
            f"- System 2: {s2.get('total_trades', 0)}건 | "
            f"승률 {s2.get('win_rate', 0) * 100:.1f}% | "
            f"손익 {s2_sign}${s2_pnl:,.2f}",
        ]
    else:
        lines.append("- 데이터 없음")

    # 심볼별 Top5 / Bottom5
    top5 = report_data.get("top5_symbols", [])
    bottom5 = report_data.get("bottom5_symbols", [])

    lines += ["", "## 심볼별 손익 Top 5"]
    if top5:
        for symbol, pnl in top5:
            sign = "+" if pnl >= 0 else ""
            lines.append(f"  - {symbol}: {sign}${pnl:,.2f}")
    else:
        lines.append("  - 데이터 없음")

    lines += ["", "## 심볼별 손익 Bottom 5"]
    if bottom5:
        for symbol, pnl in bottom5:
            sign = "+" if pnl >= 0 else ""
            lines.append(f"  - {symbol}: {sign}${pnl:,.2f}")
    else:
        lines.append("  - 데이터 없음")

    # R-배수 분포
    r_dist = report_data.get("r_distribution", {})
    lines += ["", "## R-배수 분포"]
    if r_dist and trade_count > 0:
        lines += [
            f"- 평균 R: {r_dist.get('mean_r', 0):.2f}R",
            f"- 중앙값 R: {r_dist.get('median_r', 0):.2f}R",
            f"- 최대 R: {r_dist.get('max_r', 0):.2f}R",
            f"- 최소 R: {r_dist.get('min_r', 0):.2f}R",
            f"- 수익 거래: {r_dist.get('positive_count', 0)}건 | 손실 거래: {r_dist.get('negative_count', 0)}건",
        ]
    else:
        lines.append("- 데이터 없음")

    lines += ["", "---", f"생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]

    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="월간 성과 리포트 생성 및 전송")
    parser.add_argument(
        "--month",
        default=None,
        help="대상 월 (YYYY-MM 형식, 기본값: 이전 달)",
    )
    parser.add_argument("--send", action="store_true", help="알림 채널로 리포트 전송")
    parser.add_argument("--verbose", action="store_true", help="상세 로깅 및 리포트 콘솔 출력")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    month_str = args.month if args.month else get_previous_month()

    # month 형식 검증
    try:
        parse_month(month_str)
    except ValueError as e:
        logger.error(str(e))
        return

    logger.info(f"=== 월간 리포트 생성 시작: {month_str} ===")

    config = load_config()
    notifier = setup_notifier(config)
    tracker = PositionTracker()
    data_store = ParquetDataStore()

    report_data = generate_report(month_str, tracker, data_store)
    report_text = format_report(report_data)

    if args.verbose:
        print(report_text)

    logger.info(f"리포트 완료: {report_data['trade_count']}건 거래, 총 손익 ${report_data['total_pnl']:,.2f}")

    if args.send:
        logger.info("알림 채널로 월간 리포트 전송 중...")
        await notifier.send_message(
            NotificationMessage(
                title=f"월간 성과 리포트 — {month_str}",
                body=report_text,
                level=NotificationLevel.INFO,
            )
        )
        logger.info("월간 리포트 전송 완료")
    else:
        logger.info("--send 플래그가 없어서 알림 전송을 건너뜁니다")

    logger.info("=== 월간 리포트 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
