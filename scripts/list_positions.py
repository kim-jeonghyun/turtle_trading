#!/usr/bin/env python3
"""
Turtle Trading Position Viewer
오픈 및 청산된 포지션 조회 스크립트
"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
from typing import List
from src.position_tracker import PositionTracker, Position


def format_currency(value: float, symbol: str) -> str:
    """통화 형식 변환"""
    if symbol.endswith('.KS') or symbol.endswith('.KQ'):
        # 한국 원화
        return f"₩{value:,.0f}"
    else:
        # 달러
        return f"${value:,.2f}"


def format_pnl(pnl: float, pnl_pct: float = None) -> str:
    """손익 형식 변환 (색상 코드 포함)"""
    sign = "+" if pnl >= 0 else ""
    pnl_str = f"{sign}${pnl:,.2f}"

    if pnl_pct is not None:
        pnl_str += f" ({sign}{pnl_pct:.2f}%)"

    return pnl_str


def print_positions_table(positions: List[Position], show_closed: bool = False):
    """포지션을 테이블 형식으로 출력"""
    if not positions:
        print("No positions found.")
        return

    # 오픈 포지션만 필터링
    open_positions = [p for p in positions if p.status == 'open']
    closed_positions = [p for p in positions if p.status == 'closed']

    # 오픈 포지션 출력
    if open_positions:
        print("=== Open Positions ===")
        print()
        print(f"{'Symbol':<12} | {'System':<6} | {'Direction':<9} | {'Entry':<10} | {'Units':<5} | {'Stop Loss':<10} | {'Last Update':<10}")
        print("-" * 90)

        for p in open_positions:
            entry_price = format_currency(p.entry_price, p.symbol)
            stop_loss = format_currency(p.stop_loss, p.symbol)
            units = f"{p.units}/{p.max_units}"
            system = f"S{p.system}"

            print(f"{p.symbol:<12} | {system:<6} | {p.direction:<9} | {entry_price:<10} | {units:<5} | {stop_loss:<10} | {p.entry_date:<10}")

        print()
        print(f"Total Open: {len(open_positions)} positions")
        print()

    # 청산 포지션 출력
    if show_closed and closed_positions:
        print("=== Closed Positions (Recent) ===")
        print()
        print(f"{'Symbol':<12} | {'System':<6} | {'Entry':<10} | {'Exit':<10} | {'P&L':<15} | {'R-Multiple':<10} | {'Exit Date':<10}")
        print("-" * 100)

        # 최근 10개만 표시
        for p in sorted(closed_positions, key=lambda x: x.exit_date or "", reverse=True)[:10]:
            entry_price = format_currency(p.entry_price, p.symbol)
            exit_price = format_currency(p.exit_price, p.symbol) if p.exit_price else "N/A"
            pnl_str = format_pnl(p.pnl, p.pnl_pct) if p.pnl is not None else "N/A"
            r_mult = f"{p.r_multiple:.2f}R" if p.r_multiple is not None else "N/A"
            system = f"S{p.system}"

            print(f"{p.symbol:<12} | {system:<6} | {entry_price:<10} | {exit_price:<10} | {pnl_str:<15} | {r_mult:<10} | {p.exit_date or 'N/A':<10}")

        print()
        print(f"Total Closed: {len(closed_positions)} positions (showing recent 10)")
        print()


def print_positions_json(positions: List[Position]):
    """포지션을 JSON 형식으로 출력"""
    data = [p.to_dict() for p in positions]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="List Turtle Trading positions")
    parser.add_argument('--all', action='store_true', help='Include closed positions')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--symbol', type=str, help='Filter by symbol (e.g., SPY, 005930.KS)')

    args = parser.parse_args()

    try:
        tracker = PositionTracker(base_dir="data")

        # 포지션 조회
        if args.symbol:
            positions = tracker.get_position_history(args.symbol)
        else:
            positions = tracker._load_positions()

        # 필터링
        if not args.all:
            positions = [p for p in positions if p.status == 'open']

        # 출력
        if args.json:
            print_positions_json(positions)
        else:
            print_positions_table(positions, show_closed=args.all)

            # 요약 정보 출력
            if not args.symbol:
                summary = tracker.get_summary()
                print("=== Summary ===")
                print(f"Total Positions: {summary['total_positions']}")
                print(f"Open: {summary['open_positions']}, Closed: {summary['closed_positions']}")
                print(f"Total P&L: ${summary['total_pnl']:,.2f}")
                print(f"Win Rate: {summary['win_rate']*100:.1f}% ({summary['winning_trades']}/{summary['closed_positions']} wins)")
                print(f"Average R-Multiple: {summary['avg_r_multiple']:.2f}R")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
