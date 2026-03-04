"""
Paper Trading 성과 리포트 스크립트

data/paper_trading/ 디렉토리의 데이터를 분석하여
수익률, MDD, 승률, 손익비, 누적 슬리피지 비용을 출력한다.

사용법:
    python scripts/paper_trade_report.py
"""

import sys
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils import safe_load_json

PAPER_TRADING_DIR = Path(__file__).parent.parent / "data" / "paper_trading"
PORTFOLIO_PATH = PAPER_TRADING_DIR / "portfolio.json"
TRADES_PATH = PAPER_TRADING_DIR / "trades.json"


def load_data() -> tuple[dict, list]:
    """포트폴리오 및 거래 데이터 로드"""
    portfolio: dict = safe_load_json(PORTFOLIO_PATH, default={})
    trades: list = safe_load_json(TRADES_PATH, default=[])
    return portfolio, trades


def calculate_pnl_series(trades: list) -> list[float]:
    """거래 목록에서 실현 PnL 시리즈를 계산한다.

    BUY 이후 SELL 쌍을 매칭하여 PnL을 산출한다.
    """
    pnl_list: list[float] = []
    open_positions: dict[str, dict] = {}

    for trade in trades:
        symbol = trade.get("symbol", "")
        side = trade.get("side", "")
        quantity = trade.get("quantity", 0)
        fill_price = trade.get("fill_price") or trade.get("price", 0.0)
        commission = trade.get("commission", 0.0)

        if side == "buy":
            open_positions[symbol] = {
                "fill_price": fill_price,
                "quantity": quantity,
                "commission": commission,
            }
        elif side == "sell" and symbol in open_positions:
            entry = open_positions.pop(symbol)
            gross_pnl = (fill_price - entry["fill_price"]) * min(quantity, entry["quantity"])
            net_pnl = gross_pnl - commission - entry["commission"]
            pnl_list.append(net_pnl)

    return pnl_list


def calculate_mdd(equity_curve: list[float]) -> float:
    """최대 낙폭(MDD) 계산"""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def build_equity_curve(initial_capital: float, pnl_series: list[float]) -> list[float]:
    """PnL 시리즈로 자본 곡선을 생성한다."""
    curve = [initial_capital]
    equity = initial_capital
    for pnl in pnl_series:
        equity += pnl
        curve.append(equity)
    return curve


def calculate_win_rate(pnl_series: list[float]) -> float:
    """승률 계산"""
    if not pnl_series:
        return 0.0
    wins = sum(1 for p in pnl_series if p > 0)
    return wins / len(pnl_series)


def calculate_profit_factor(pnl_series: list[float]) -> float:
    """손익비(Profit Factor) 계산"""
    gross_profit = sum(p for p in pnl_series if p > 0)
    gross_loss = abs(sum(p for p in pnl_series if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def print_report(portfolio: dict, trades: list) -> None:
    """성과 리포트를 stdout에 출력한다."""
    initial_capital = portfolio.get("initial_capital", 5_000_000)
    cash = portfolio.get("cash", initial_capital)
    position_value = portfolio.get("position_value", 0.0)
    total_equity = portfolio.get("total_equity", cash + position_value)
    total_commission = portfolio.get("total_commission", 0.0)
    total_slippage_cost = portfolio.get("total_slippage_cost", 0.0)
    last_updated = portfolio.get("last_updated", "N/A")

    pnl_series = calculate_pnl_series(trades)
    equity_curve = build_equity_curve(initial_capital, pnl_series)
    mdd = calculate_mdd(equity_curve)
    win_rate = calculate_win_rate(pnl_series)
    profit_factor = calculate_profit_factor(pnl_series)
    total_return = (total_equity - initial_capital) / initial_capital

    divider = "=" * 55
    print(divider)
    print("  Paper Trading 성과 리포트")
    print(divider)
    print(f"  마지막 업데이트    : {last_updated}")
    print(f"  초기 자본         : {initial_capital:>15,.0f} 원")
    print(f"  현재 총 자산       : {total_equity:>15,.0f} 원")
    print(f"  현금              : {cash:>15,.0f} 원")
    print(f"  포지션 평가액      : {position_value:>15,.0f} 원")
    print(divider)
    print("  성과 지표")
    print(divider)
    print(f"  총 수익률         : {total_return:>14.2%}")
    print(f"  최대 낙폭 (MDD)   : {mdd:>14.2%}")
    print(f"  승률              : {win_rate:>14.2%}")
    pf_str = f"{profit_factor:.2f}" if profit_factor != float("inf") else "inf"
    print(f"  손익비 (PF)       : {pf_str:>14}")
    print(f"  총 거래 수        : {len(pnl_series):>14} 건")
    print(divider)
    print("  비용 분석")
    print(divider)
    print(f"  누적 슬리피지 비용 : {total_slippage_cost:>15,.0f} 원")
    print(f"  누적 수수료       : {total_commission:>15,.0f} 원")
    total_cost = total_slippage_cost + total_commission
    print(f"  총 비용           : {total_cost:>15,.0f} 원")
    if initial_capital > 0:
        cost_rate = total_cost / initial_capital
        print(f"  비용/초기자본     : {cost_rate:>14.3%}")
    print(divider)
    print("  실거래 전환 판단 기준")
    print(divider)
    ready = True
    if total_return < 0:
        print("  [주의] 총 수익률 음수 — 전략 재검토 권고")
        ready = False
    if mdd > 0.30:
        print("  [주의] MDD > 30% — 위험 과다")
        ready = False
    if profit_factor < 1.0:
        print("  [주의] 손익비 < 1.0 — 전략 개선 필요")
        ready = False
    if len(pnl_series) < 10:
        print("  [주의] 거래 건수 < 10 — 통계적 유의성 부족")
        ready = False
    if ready:
        print("  [OK] 모든 기준 충족 — 실거래 전환 검토 가능")
    print(divider)


def main() -> None:
    if not PORTFOLIO_PATH.exists():
        print("포트폴리오 데이터 없음. Paper Trading을 먼저 실행하세요.")
        print(f"  예상 경로: {PORTFOLIO_PATH}")
        sys.exit(1)

    portfolio, trades = load_data()
    print_report(portfolio, trades)


if __name__ == "__main__":
    main()
