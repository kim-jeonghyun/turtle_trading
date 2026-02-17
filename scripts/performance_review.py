#!/usr/bin/env python3
"""
성과 리뷰 - 지정 기간의 트레이딩 성과 분석
- 청산된 포지션 분석
- 총 손익, 승률, 평균 R-배수, 최고/최악 거래 계산
- 테이블 형식 또는 CSV 내보내기
"""

import sys
import argparse
import logging
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

try:
    from tabulate import tabulate
except ImportError:
    def tabulate(data, headers=None, tablefmt=None):
        lines = []
        if headers:
            lines.append(" | ".join(str(h) for h in headers))
        for row in data:
            lines.append(" | ".join(str(c) for c in row))
        return "\n".join(lines)

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.position_tracker import PositionTracker, Position, PositionStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_period(period_str: str) -> Tuple[datetime, datetime]:
    """
    기간 문자열을 datetime 범위로 파싱

    Args:
        period_str: "1m", "3m", "6m", "1y", "all"

    Returns:
        (start_date, end_date)
    """
    end_date = datetime.now()

    if period_str == "1m":
        start_date = end_date - timedelta(days=30)
    elif period_str == "3m":
        start_date = end_date - timedelta(days=90)
    elif period_str == "6m":
        start_date = end_date - timedelta(days=180)
    elif period_str == "1y":
        start_date = end_date - timedelta(days=365)
    elif period_str == "all":
        start_date = datetime(2000, 1, 1)  # 매우 과거
    else:
        raise ValueError(f"잘못된 기간: {period_str}")

    return start_date, end_date


def filter_closed_positions(
    positions: List[Position],
    start_date: datetime,
    end_date: datetime,
    system: Optional[int] = None
) -> List[Position]:
    """
    청산된 포지션 필터링

    Args:
        positions: 모든 포지션
        start_date: 검색 시작 날짜
        end_date: 검색 종료 날짜
        system: 필터할 시스템 (1 or 2, None이면 둘 다)

    Returns:
        필터링된 포지션 목록
    """
    filtered = []

    for pos in positions:
        # 청산된 포지션만
        if pos.status != PositionStatus.CLOSED.value:
            continue

        # 시간 범위 필터
        if pos.exit_date is None:
            continue

        try:
            exit_dt = datetime.fromisoformat(pos.exit_date)
        except (ValueError, TypeError):
            continue

        if not (start_date <= exit_dt <= end_date):
            continue

        # 시스템 필터
        if system is not None and pos.system != system:
            continue

        filtered.append(pos)

    return filtered


def calculate_statistics(positions: List[Position]) -> Dict:
    """
    트레이딩 성과 통계 계산

    Returns:
        {
            "total_trades": int,
            "winning_trades": int,
            "losing_trades": int,
            "win_rate_pct": float,
            "total_pnl": float,
            "avg_pnl": float,
            "best_trade": float,
            "worst_trade": float,
            "avg_r_multiple": float,
            "best_r_multiple": float,
            "worst_r_multiple": float,
            "profit_factor": float,
        }
    """
    if not positions:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "avg_r_multiple": 0.0,
            "best_r_multiple": 0.0,
            "worst_r_multiple": 0.0,
            "profit_factor": 0.0,
        }

    pnl_values = []
    r_multiples = []
    winning_pnl = 0.0
    losing_pnl = 0.0

    for pos in positions:
        if pos.pnl is None:
            continue

        pnl_values.append(pos.pnl)

        if pos.pnl > 0:
            winning_pnl += pos.pnl
        else:
            losing_pnl += abs(pos.pnl)

        if pos.r_multiple is not None:
            r_multiples.append(pos.r_multiple)

    total_pnl = sum(pnl_values)
    total_trades = len(pnl_values)
    winning_trades = sum(1 for p in pnl_values if p > 0)
    losing_trades = total_trades - winning_trades

    avg_r_multiple = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0
    best_r_multiple = max(r_multiples) if r_multiples else 0.0
    worst_r_multiple = min(r_multiples) if r_multiples else 0.0

    profit_factor = winning_pnl / losing_pnl if losing_pnl > 0 else (winning_pnl if winning_pnl > 0 else 0.0)

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate_pct": (winning_trades / total_trades * 100) if total_trades > 0 else 0.0,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / total_trades if total_trades > 0 else 0.0,
        "best_trade": max(pnl_values) if pnl_values else 0.0,
        "worst_trade": min(pnl_values) if pnl_values else 0.0,
        "avg_r_multiple": avg_r_multiple,
        "best_r_multiple": best_r_multiple,
        "worst_r_multiple": worst_r_multiple,
        "profit_factor": profit_factor,
    }


def print_statistics_report(stats: Dict, period: str):
    """통계 리포트 출력"""
    logger.info("=" * 80)
    logger.info(f"PERFORMANCE REVIEW - Period: {period}")
    logger.info("=" * 80)

    print("\n📊 TRADE SUMMARY")
    print(f"  Total Trades:     {stats['total_trades']}")
    print(f"  Winning Trades:   {stats['winning_trades']}")
    print(f"  Losing Trades:    {stats['losing_trades']}")
    print(f"  Win Rate:         {stats['win_rate_pct']:.2f}%")

    print("\n💰 PROFIT & LOSS")
    total_pnl_symbol = "+" if stats['total_pnl'] >= 0 else "-"
    print(f"  Total P&L:        {total_pnl_symbol}${abs(stats['total_pnl']):,.2f}")
    avg_pnl_symbol = "+" if stats['avg_pnl'] >= 0 else "-"
    print(f"  Average P&L:      {avg_pnl_symbol}${abs(stats['avg_pnl']):,.2f}")
    print(f"  Best Trade:       +${stats['best_trade']:,.2f}")
    print(f"  Worst Trade:      -${abs(stats['worst_trade']):,.2f}")

    print("\n📈 R-MULTIPLE ANALYSIS")
    print(f"  Average R:        {stats['avg_r_multiple']:.2f}R")
    print(f"  Best R:           {stats['best_r_multiple']:.2f}R")
    print(f"  Worst R:          {stats['worst_r_multiple']:.2f}R")
    print(f"  Profit Factor:    {stats['profit_factor']:.2f}")

    logger.info("=" * 80)


def print_position_details(positions: List[Position]):
    """개별 포지션 상세 정보 출력"""
    table_data = []

    for pos in sorted(positions, key=lambda p: p.exit_date or "", reverse=True):
        table_data.append([
            pos.symbol,
            pos.system,
            pos.direction,
            f"{pos.entry_date}",
            f"{pos.exit_date}",
            f"${pos.entry_price:,.2f}",
            f"${pos.exit_price:,.2f}" if pos.exit_price else "N/A",
            f"${pos.pnl:,.2f}" if pos.pnl else "N/A",
            f"{pos.r_multiple:.2f}R" if pos.r_multiple else "N/A",
            pos.exit_reason or "N/A",
        ])

    headers = [
        "Symbol", "System", "Dir", "Entry Date", "Exit Date",
        "Entry Price", "Exit Price", "P&L", "R-Multiple", "Reason"
    ]

    print("\n" + "=" * 150)
    print("TRADE DETAILS")
    print("=" * 150)
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print()


def export_to_csv(positions: List[Position], filepath: Path):
    """포지션을 CSV로 내보내기"""
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # 헤더
        writer.writerow([
            "Symbol", "System", "Direction", "Entry Date", "Entry Price",
            "Exit Date", "Exit Price", "Units", "Total Shares",
            "P&L", "P&L %", "R-Multiple", "Exit Reason"
        ])

        # 데이터
        for pos in sorted(positions, key=lambda p: p.exit_date or "", reverse=True):
            pnl_pct = pos.pnl_pct * 100 if pos.pnl_pct else None

            writer.writerow([
                pos.symbol,
                pos.system,
                pos.direction,
                pos.entry_date,
                f"{pos.entry_price:.2f}",
                pos.exit_date or "",
                f"{pos.exit_price:.2f}" if pos.exit_price else "",
                pos.units,
                pos.total_shares,
                f"{pos.pnl:.2f}" if pos.pnl else "",
                f"{pnl_pct:.2f}%" if pnl_pct else "",
                f"{pos.r_multiple:.2f}" if pos.r_multiple else "",
                pos.exit_reason or "",
            ])

    logger.info(f"CSV 내보내기: {filepath}")


def print_system_comparison(all_positions: List[Position], period: str):
    """System 1과 System 2 비교"""
    sys1_positions = [p for p in all_positions if p.system == 1]
    sys2_positions = [p for p in all_positions if p.system == 2]

    sys1_stats = calculate_statistics(sys1_positions)
    sys2_stats = calculate_statistics(sys2_positions)

    table_data = [
        ["Total Trades", sys1_stats["total_trades"], sys2_stats["total_trades"]],
        ["Win Rate", f"{sys1_stats['win_rate_pct']:.2f}%", f"{sys2_stats['win_rate_pct']:.2f}%"],
        ["Total P&L", f"${sys1_stats['total_pnl']:,.2f}", f"${sys2_stats['total_pnl']:,.2f}"],
        ["Avg R-Multiple", f"{sys1_stats['avg_r_multiple']:.2f}R", f"{sys2_stats['avg_r_multiple']:.2f}R"],
        ["Profit Factor", f"{sys1_stats['profit_factor']:.2f}", f"{sys2_stats['profit_factor']:.2f}"],
    ]

    print("\n" + "=" * 80)
    print("SYSTEM COMPARISON")
    print("=" * 80)
    print(tabulate(table_data, headers=["Metric", "System 1", "System 2"], tablefmt="grid"))
    print()


def main(args):
    """메인 함수"""
    logger.info("=== 성과 리뷰 분석 시작 ===")

    # 기간 파싱
    try:
        start_date, end_date = parse_period(args.period)
        logger.info(f"분석 기간: {start_date.date()} ~ {end_date.date()}")
    except ValueError as e:
        logger.error(f"기간 파싱 오류: {e}")
        return

    # 포지션 로드
    try:
        tracker = PositionTracker()
        all_positions = tracker.get_all_positions()
        logger.info(f"전체 포지션: {len(all_positions)}개")

    except Exception as e:
        logger.error(f"포지션 로드 오류: {e}")
        return

    # 기간 내 청산 포지션 필터링
    if args.system == "all":
        closed_positions = filter_closed_positions(all_positions, start_date, end_date)
    else:
        system = int(args.system)
        closed_positions = filter_closed_positions(all_positions, start_date, end_date, system=system)

    logger.info(f"청산된 포지션 (기간 내): {len(closed_positions)}개")

    if not closed_positions:
        logger.warning("분석할 청산 포지션 없음")
        return

    # 통계 계산
    stats = calculate_statistics(closed_positions)

    # 리포트 출력
    print_statistics_report(stats, args.period)

    # 상세 정보 출력
    if args.verbose:
        print_position_details(closed_positions)

    # System 비교 (--system all일 때만)
    if args.system == "all":
        print_system_comparison(closed_positions, args.period)

    # CSV 내보내기
    if args.csv:
        csv_path = Path(args.csv)
        export_to_csv(closed_positions, csv_path)

    logger.info("=== 분석 완료 ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="성과 리뷰 - 트레이딩 성과 분석")
    parser.add_argument(
        "--period",
        choices=["1m", "3m", "6m", "1y", "all"],
        default="3m",
        help="분석 기간 (기본값: 3m)"
    )
    parser.add_argument(
        "--system",
        choices=["1", "2", "all"],
        default="all",
        help="분석할 시스템 (기본값: all)"
    )
    parser.add_argument(
        "--csv",
        type=str,
        help="CSV 내보내기 경로"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 포지션 정보 출력"
    )

    args = parser.parse_args()
    main(args)
