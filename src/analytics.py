"""
트레이딩 성과 분석 모듈
- R-multiple 분석
- 승률/손익비 계산
- 드로다운 분석
- 시스템별 성과 비교
"""

import logging
import math
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)


class TradeAnalytics:
    """청산 완료된 거래 기록을 분석하는 클래스"""

    def __init__(self, trades: List[dict]):
        """
        Args:
            trades: PositionTracker에서 가져온 청산 완료 거래 딕셔너리 리스트.
                    각 항목은 symbol, system, direction, entry_price, exit_price,
                    stop_loss, total_shares, pnl, entry_date, exit_date 필드를 포함.
        """
        self.trades = trades if trades else []

    def calculate_r_multiples(self) -> List[float]:
        """
        각 거래의 R-배수 계산.

        R = pnl / (entry_price - stop_loss) * total_shares
        R > 0 = 수익 거래, R < 0 = 손실 거래

        Returns:
            R-배수 리스트
        """
        r_multiples = []
        for trade in self.trades:
            try:
                entry_price = trade.get("entry_price", 0)
                stop_loss = trade.get("stop_loss", 0)
                total_shares = trade.get("total_shares", 0)
                pnl = trade.get("pnl", 0)

                # 초기 리스크 계산 (진입가 - 스톱로스) * 주식수
                risk_amount = abs(entry_price - stop_loss) * total_shares

                if risk_amount <= 0:
                    # 리스크 금액이 0이면 R-배수 계산 불가 → 스킵
                    logger.warning(
                        f"리스크 금액이 0 또는 음수: {trade.get('symbol', 'unknown')}, "
                        f"entry={entry_price}, stop={stop_loss}"
                    )
                    continue

                r = pnl / risk_amount
                r_multiples.append(r)
            except (TypeError, ZeroDivisionError) as e:
                logger.warning(f"R-배수 계산 오류: {e}")
                continue

        return r_multiples

    def get_r_distribution(self) -> dict:
        """
        R-배수 분포 통계 반환.

        Returns:
            {mean_r, median_r, std_r, max_r, min_r, positive_count, negative_count}
        """
        r_multiples = self.calculate_r_multiples()

        if not r_multiples:
            return {
                "mean_r": 0.0,
                "median_r": 0.0,
                "std_r": 0.0,
                "max_r": 0.0,
                "min_r": 0.0,
                "positive_count": 0,
                "negative_count": 0,
            }

        n = len(r_multiples)
        mean_r = sum(r_multiples) / n

        # 중앙값 계산
        sorted_r = sorted(r_multiples)
        mid = n // 2
        if n % 2 == 0:
            median_r = (sorted_r[mid - 1] + sorted_r[mid]) / 2
        else:
            median_r = sorted_r[mid]

        # 표준편차 계산 (표본 표준편차, n-1)
        variance = sum((r - mean_r) ** 2 for r in r_multiples) / (n - 1) if n > 1 else 0.0
        std_r = math.sqrt(variance)

        positive_count = sum(1 for r in r_multiples if r > 0)
        negative_count = sum(1 for r in r_multiples if r <= 0)

        return {
            "mean_r": round(mean_r, 4),
            "median_r": round(median_r, 4),
            "std_r": round(std_r, 4),
            "max_r": round(max(r_multiples), 4),
            "min_r": round(min(r_multiples), 4),
            "positive_count": positive_count,
            "negative_count": negative_count,
        }

    def get_expectancy(self) -> float:
        """
        수학적 기대값 (Expectancy) 계산.

        E = (승률 * 평균 승리 R) + (손실률 * 평균 손실 R)

        Returns:
            기대값 (양수면 유망한 시스템)
        """
        r_multiples = self.calculate_r_multiples()

        if not r_multiples:
            return 0.0

        winners = [r for r in r_multiples if r > 0]
        losers = [r for r in r_multiples if r <= 0]

        n = len(r_multiples)
        win_rate = len(winners) / n
        loss_rate = len(losers) / n

        avg_win_r = sum(winners) / len(winners) if winners else 0.0
        avg_loss_r = sum(losers) / len(losers) if losers else 0.0

        expectancy = (win_rate * avg_win_r) + (loss_rate * avg_loss_r)
        return round(expectancy, 4)

    def get_win_loss_stats(self) -> dict:
        """
        승/패 통계 계산.

        Returns:
            {total_trades, winners, losers, win_rate, avg_win, avg_loss,
             profit_factor, largest_win, largest_loss}
        """
        if not self.trades:
            return {
                "total_trades": 0,
                "winners": 0,
                "losers": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
            }

        pnl_values = [t.get("pnl", 0) or 0 for t in self.trades]
        winning_pnls = [p for p in pnl_values if p > 0]
        losing_pnls = [p for p in pnl_values if p <= 0]

        total = len(pnl_values)
        winners_count = len(winning_pnls)
        losers_count = len(losing_pnls)
        win_rate = winners_count / total if total > 0 else 0.0

        avg_win = sum(winning_pnls) / len(winning_pnls) if winning_pnls else 0.0
        avg_loss = sum(losing_pnls) / len(losing_pnls) if losing_pnls else 0.0

        total_gains = sum(winning_pnls)
        total_losses = abs(sum(losing_pnls))
        # Profit Factor: 총 수익 / 총 손실 (손실이 0이면 총 수익 그대로 반환)
        profit_factor = total_gains / total_losses if total_losses > 0 else total_gains

        largest_win = max(winning_pnls) if winning_pnls else 0.0
        largest_loss = min(losing_pnls) if losing_pnls else 0.0

        return {
            "total_trades": total,
            "winners": winners_count,
            "losers": losers_count,
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 4),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
        }

    def get_system_comparison(self) -> dict:
        """
        System 1 vs System 2 성과 비교.

        Returns:
            {"system_1": {...}, "system_2": {...}}
        """
        system1_trades = [t for t in self.trades if t.get("system") == 1]
        system2_trades = [t for t in self.trades if t.get("system") == 2]

        def _stats_for(trades: List[dict]) -> dict:
            sub_analytics = TradeAnalytics(trades)
            win_loss = sub_analytics.get_win_loss_stats()
            expectancy = sub_analytics.get_expectancy()
            r_dist = sub_analytics.get_r_distribution()
            total_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
            return {
                **win_loss,
                "expectancy": expectancy,
                "mean_r": r_dist["mean_r"],
                "total_pnl": round(total_pnl, 2),
            }

        return {
            "system_1": _stats_for(system1_trades),
            "system_2": _stats_for(system2_trades),
        }

    def get_monthly_returns(self) -> dict:
        """
        월별 손익 집계.

        Returns:
            {"YYYY-MM": total_pnl, ...}
        """
        monthly: Dict[str, float] = defaultdict(float)

        for trade in self.trades:
            exit_date = trade.get("exit_date", "")
            pnl = trade.get("pnl", 0) or 0

            if not exit_date:
                continue

            # YYYY-MM 형식으로 파싱 (YYYY-MM-DD 또는 YYYY-MM-DD 모두 지원)
            try:
                month_key = str(exit_date)[:7]  # "YYYY-MM"
                monthly[month_key] += pnl
            except Exception as e:
                logger.warning(f"월별 집계 오류: {e}, exit_date={exit_date}")
                continue

        # 월별 정렬
        return {k: round(v, 2) for k, v in sorted(monthly.items())}

    def get_drawdown_analysis(self, equity_series: list) -> dict:
        """
        드로다운 분석.

        Args:
            equity_series: 누적 자산 가치 리스트 (시간순)

        Returns:
            {max_drawdown, max_drawdown_pct, max_drawdown_duration,
             current_drawdown, current_drawdown_pct, recovery_factor}
        """
        if not equity_series or len(equity_series) < 2:
            return {
                "max_drawdown": 0.0,
                "max_drawdown_pct": 0.0,
                "max_drawdown_duration": 0,
                "current_drawdown": 0.0,
                "current_drawdown_pct": 0.0,
                "recovery_factor": 0.0,
            }

        peak = equity_series[0]
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        max_drawdown_duration = 0
        current_duration = 0

        for value in equity_series:
            if value > peak:
                peak = value
                current_duration = 0
            else:
                current_duration += 1
                drawdown = peak - value
                drawdown_pct = drawdown / peak if peak > 0 else 0.0

                if drawdown > max_drawdown:
                    max_drawdown = drawdown

                if drawdown_pct > max_drawdown_pct:
                    max_drawdown_pct = drawdown_pct

                if current_duration > max_drawdown_duration:
                    max_drawdown_duration = current_duration

        # 현재 드로다운
        current_peak = max(equity_series)
        current_value = equity_series[-1]
        current_drawdown = max(0.0, current_peak - current_value)
        current_drawdown_pct = current_drawdown / current_peak if current_peak > 0 else 0.0

        # Recovery Factor = 총 수익 / 최대 낙폭
        total_return = equity_series[-1] - equity_series[0]
        recovery_factor = total_return / max_drawdown if max_drawdown > 0 else 0.0

        return {
            "max_drawdown": round(max_drawdown, 2),
            "max_drawdown_pct": round(max_drawdown_pct * 100, 2),
            "max_drawdown_duration": max_drawdown_duration,
            "current_drawdown": round(current_drawdown, 2),
            "current_drawdown_pct": round(current_drawdown_pct * 100, 2),
            "recovery_factor": round(recovery_factor, 4),
        }

    def generate_summary_report(self) -> str:
        """
        성과 요약 리포트를 한국어 텍스트로 생성.

        Returns:
            사람이 읽을 수 있는 성과 요약 문자열
        """
        if not self.trades:
            return "분석할 거래 데이터가 없습니다."

        stats = self.get_win_loss_stats()
        expectancy = self.get_expectancy()
        r_dist = self.get_r_distribution()
        sys_cmp = self.get_system_comparison()
        monthly = self.get_monthly_returns()

        total_pnl = sum(t.get("pnl", 0) or 0 for t in self.trades)

        lines = [
            "=" * 50,
            "터틀 트레이딩 성과 분석 리포트",
            "=" * 50,
            "",
            "[전체 성과]",
            f"  총 거래 수     : {stats['total_trades']}건",
            f"  승리 거래      : {stats['winners']}건",
            f"  손실 거래      : {stats['losers']}건",
            f"  승률           : {stats['win_rate'] * 100:.1f}%",
            f"  총 손익        : ${total_pnl:,.2f}",
            f"  평균 수익      : ${stats['avg_win']:,.2f}",
            f"  평균 손실      : ${stats['avg_loss']:,.2f}",
            f"  Profit Factor  : {stats['profit_factor']:.2f}",
            f"  최대 수익      : ${stats['largest_win']:,.2f}",
            f"  최대 손실      : ${stats['largest_loss']:,.2f}",
            "",
            "[R-배수 분석]",
            f"  평균 R         : {r_dist['mean_r']:.2f}R",
            f"  중앙값 R       : {r_dist['median_r']:.2f}R",
            f"  표준편차       : {r_dist['std_r']:.2f}",
            f"  최대 R         : {r_dist['max_r']:.2f}R",
            f"  최소 R         : {r_dist['min_r']:.2f}R",
            f"  기대값 (E)     : {expectancy:.3f}R",
            "",
            "[시스템 비교]",
            f"  System 1 거래  : {sys_cmp['system_1']['total_trades']}건 | "
            f"승률 {sys_cmp['system_1']['win_rate'] * 100:.1f}% | "
            f"기대값 {sys_cmp['system_1']['expectancy']:.3f}R | "
            f"손익 ${sys_cmp['system_1']['total_pnl']:,.2f}",
            f"  System 2 거래  : {sys_cmp['system_2']['total_trades']}건 | "
            f"승률 {sys_cmp['system_2']['win_rate'] * 100:.1f}% | "
            f"기대값 {sys_cmp['system_2']['expectancy']:.3f}R | "
            f"손익 ${sys_cmp['system_2']['total_pnl']:,.2f}",
        ]

        if monthly:
            lines += ["", "[월별 손익]"]
            for month, pnl in monthly.items():
                sign = "+" if pnl >= 0 else ""
                lines.append(f"  {month}: {sign}${pnl:,.2f}")

        lines += ["", "=" * 50]
        return "\n".join(lines)


# ── 독립 함수 ──────────────────────────────────────────────────────────────


def calculate_sharpe_ratio(returns: list, risk_free_rate: float = 0.03) -> float:
    """
    샤프 지수 계산 (연율화).

    Args:
        returns: 기간별 수익률 리스트 (예: 일별 수익률)
        risk_free_rate: 연간 무위험 수익률 (기본값 3%)

    Returns:
        샤프 지수 (연율화)
    """
    if not returns or len(returns) < 2:
        return 0.0

    n = len(returns)
    mean_return = sum(returns) / n
    variance = sum((r - mean_return) ** 2 for r in returns) / (n - 1)
    std_return = math.sqrt(variance)

    if std_return < 1e-10:
        return 0.0

    # 일별 무위험 수익률로 변환 (거래일 252일 기준)
    daily_rf = risk_free_rate / 252
    excess_return = mean_return - daily_rf

    # 연율화: sqrt(252) 적용
    sharpe = (excess_return / std_return) * math.sqrt(252)
    return round(sharpe, 4)


def calculate_sortino_ratio(returns: list, risk_free_rate: float = 0.03) -> float:
    """
    소르티노 지수 계산 (연율화) - 하방 변동성만 사용.

    Args:
        returns: 기간별 수익률 리스트 (예: 일별 수익률)
        risk_free_rate: 연간 무위험 수익률 (기본값 3%)

    Returns:
        소르티노 지수 (연율화)
    """
    if not returns or len(returns) < 2:
        return 0.0

    n = len(returns)
    mean_return = sum(returns) / n
    daily_rf = risk_free_rate / 252

    # 하방 수익률만 추출 (무위험 수익률 미만)
    downside_returns = [r for r in returns if r < daily_rf]

    if not downside_returns:
        # 손실 거래가 없으면 소르티노 지수 = 무한대로 처리 → 0 반환
        return 0.0

    downside_variance = sum((r - daily_rf) ** 2 for r in downside_returns) / len(downside_returns)
    downside_std = math.sqrt(downside_variance)

    if downside_std == 0:
        return 0.0

    sortino = ((mean_return - daily_rf) / downside_std) * math.sqrt(252)
    return round(sortino, 4)


def calculate_calmar_ratio(cagr: float, max_drawdown: float) -> float:
    """
    칼마 지수 계산.

    Args:
        cagr: 연평균 복합 성장률 (CAGR), 예: 0.15 = 15%
        max_drawdown: 최대 낙폭 비율 (양수), 예: 0.20 = 20%

    Returns:
        칼마 지수 (CAGR / 최대낙폭)
    """
    if max_drawdown <= 0:
        return 0.0

    calmar = cagr / max_drawdown
    return round(calmar, 4)
