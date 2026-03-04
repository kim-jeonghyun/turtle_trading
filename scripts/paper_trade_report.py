#!/usr/bin/env python3
"""
Paper Trading 성과 리포트 생성 스크립트.

data/paper_trading/ 의 거래 기록을 읽어 성과 지표를 출력한다.
"""

import argparse
import logging
from pathlib import Path

from src.utils import safe_load_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PAPER_TRADING_DIR = Path(__file__).parent.parent / "data" / "paper_trading"
PORTFOLIO_PATH = PAPER_TRADING_DIR / "portfolio.json"
TRADES_PATH = PAPER_TRADING_DIR / "trades.json"


def _calc_mdd(equity_curve: list[float]) -> float:
    """최대 낙폭(MDD) 계산"""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd


def generate_report(initial_capital: float = 5_000_000) -> dict:
    """Paper trading 성과 리포트 데이터 생성"""
    portfolio = safe_load_json(PORTFOLIO_PATH, default={})
    trades: list[dict] = safe_load_json(TRADES_PATH, default=[])

    if not portfolio and not trades:
        logger.warning("Paper trading 데이터가 없습니다. 먼저 dry-run 매매를 실행하세요.")
        return {}

    cash = portfolio.get("cash", initial_capital)
    positions = portfolio.get("positions", {})

    # 포지션 현재가치 (avg_price 기반 추정)
    position_value = sum(p.get("quantity", 0) * p.get("avg_price", 0) for p in positions.values())
    total_equity = cash + position_value
    total_pnl = total_equity - initial_capital
    return_pct = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0.0

    # 거래 통계
    closed_trades = [t for t in trades if t.get("side") == "sell"]
    winning = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losing = [t for t in closed_trades if t.get("pnl", 0) <= 0]
    win_rate = len(winning) / len(closed_trades) * 100 if closed_trades else 0.0

    avg_win = sum(t["pnl"] for t in winning) / len(winning) if winning else 0.0
    avg_loss = sum(abs(t["pnl"]) for t in losing) / len(losing) if losing else 0.0
    profit_factor = avg_win / avg_loss if avg_loss > 0 else float("inf")

    # 슬리피지 / 수수료 누적
    total_slippage_cost = sum(abs(t.get("slippage", 0)) * t.get("quantity", 0) for t in trades)
    total_commission = sum(t.get("commission", 0) for t in trades)

    # MDD: 거래별 누적 pnl 기반 equity curve 근사
    equity_curve: list[float] = [initial_capital]
    running = initial_capital
    for t in trades:
        running += t.get("pnl", 0) - t.get("commission", 0)
        equity_curve.append(running)
    mdd = _calc_mdd(equity_curve)

    return {
        "total_trades": len(trades),
        "closed_trades": len(closed_trades),
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "return_pct": return_pct,
        "mdd_pct": mdd * 100,
        "total_slippage_cost": total_slippage_cost,
        "total_commission": total_commission,
        "cash": cash,
        "position_value": position_value,
        "total_equity": total_equity,
        "open_positions": len(positions),
    }


def print_report(report: dict, initial_capital: float) -> None:
    """리포트 콘솔 출력"""
    sep = "=" * 55
    print(sep)
    print("  Paper Trading 성과 리포트")
    print(sep)
    print(f"  초기 자본      : {initial_capital:>15,.0f} 원")
    print(f"  현재 자산      : {report['total_equity']:>15,.0f} 원")
    print(f"  총 손익        : {report['total_pnl']:>+15,.0f} 원")
    print(f"  수익률         : {report['return_pct']:>14.2f} %")
    print(f"  최대낙폭(MDD)  : {report['mdd_pct']:>14.2f} %")
    print(sep)
    print(f"  총 주문        : {report['total_trades']:>15,} 건")
    print(f"  청산 거래      : {report['closed_trades']:>15,} 건")
    print(f"  승률           : {report['win_rate_pct']:>14.1f} %")
    print(f"  손익비(PF)     : {report['profit_factor']:>15.2f}")
    print(sep)
    print(f"  누적 슬리피지  : {report['total_slippage_cost']:>15,.0f} 원")
    print(f"  누적 수수료    : {report['total_commission']:>15,.0f} 원")
    print(f"  오픈 포지션    : {report['open_positions']:>15,} 개")
    print(sep)
    print()
    print("  [실거래 전환 판단 기준 안내]")
    print("  - 수익률 > 0%, MDD < 20%, 승률 >= 40%, 손익비 >= 1.5")
    print("  - 슬리피지 + 수수료 합계가 총수익의 20% 이하")
    print("  - 최소 30건 이상의 청산 거래 확보")
    print(sep)


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper Trading 성과 리포트")
    parser.add_argument(
        "--capital",
        type=float,
        default=5_000_000,
        help="초기 자본 (기본: 5,000,000원)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 형식으로 출력",
    )
    args = parser.parse_args()

    logger.info("=== Paper Trading 리포트 생성 시작 ===")
    report = generate_report(initial_capital=args.capital)

    if not report:
        return

    if args.json:
        import json

        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report, initial_capital=args.capital)

    logger.info("=== 리포트 완료 ===")


if __name__ == "__main__":
    main()
