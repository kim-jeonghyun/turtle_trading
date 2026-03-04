#!/usr/bin/env python3
"""
과적합 자동 점검 스크립트

백테스트 결과의 과적합 위험을 자동으로 점검합니다.
결과는 advisory 수준이며 종료 코드는 항상 0 (차단하지 않음).

Note: Walk-forward 분석 미실행 — v4.2.0에서 자동화 예정
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

BACKTEST_RESULTS_DIR = Path(__file__).parent.parent / "data" / "backtest_results"

# 점검 임계치
THRESHOLD_OOS_IS_RATIO = 0.5  # OOS 수익률이 IS의 50% 미만이면 경고
THRESHOLD_PARAM_SENSITIVITY = 0.30  # ATR ±20% 변경 시 수익률 변동 > 30% 경고
THRESHOLD_MIN_TRADES = 30  # 거래 횟수 < 30 경고
THRESHOLD_MONTHLY_PF_STD = 2.0  # 월별 profit factor 표준편차 > 2.0 경고
THRESHOLD_MAX_CONSEC_LOSSES = 10  # 연속 손실 > 10 경고
THRESHOLD_QUARTERLY_SHARPE_STD = 1.5  # 분기별 Sharpe 표준편차 > 1.5 경고


@dataclass
class OverfittingCheckResult:
    """개별 과적합 체크 결과"""

    name: str
    passed: bool
    message: str


@dataclass
class BacktestSummary:
    """check_overfitting 스크립트가 소비하는 백테스트 요약 구조"""

    # 기본 성과
    total_return: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0

    # IS/OOS 구분 (있을 때만 사용)
    is_return: Optional[float] = None  # In-sample 수익률
    oos_return: Optional[float] = None  # Out-of-sample 수익률

    # 파라미터 민감도 (ATR ±20% 변형 백테스트 결과)
    param_sensitivity_returns: List[float] = field(default_factory=list)

    # 거래별 PnL 목록 (연속 손실 계산용)
    trade_pnls: List[float] = field(default_factory=list)

    # 월별 profit factor (월별 series)
    monthly_profit_factors: List[float] = field(default_factory=list)

    # 분기별 Sharpe ratio
    quarterly_sharpe_ratios: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 6개 점검 함수
# ---------------------------------------------------------------------------


def check_in_out_sample(results: BacktestSummary) -> Tuple[bool, str]:
    """OOS 수익률이 IS 수익률의 50% 미만이면 경고 (과적합 의심)."""
    if results.is_return is None or results.oos_return is None:
        return True, "IS/OOS 분리 데이터 없음 — 스킵 (walk-forward 미실행)"

    is_ret = results.is_return
    oos_ret = results.oos_return

    # IS 수익률이 0 이하이면 비율 계산 불가
    if is_ret <= 0:
        return True, f"IS 수익률 {is_ret:.1%} — 비율 계산 생략"

    ratio = oos_ret / is_ret
    if ratio < THRESHOLD_OOS_IS_RATIO:
        return (
            False,
            f"OOS/IS 수익률 비율 {ratio:.1%} < {THRESHOLD_OOS_IS_RATIO:.0%} "
            f"(IS: {is_ret:.1%}, OOS: {oos_ret:.1%}) — 과적합 의심",
        )
    return (
        True,
        f"OOS/IS 수익률 비율 {ratio:.1%} >= {THRESHOLD_OOS_IS_RATIO:.0%} (IS: {is_ret:.1%}, OOS: {oos_ret:.1%})",
    )


def check_parameter_sensitivity(results: BacktestSummary) -> Tuple[bool, str]:
    """ATR 기간 ±20% 변경 시 수익률 변동이 30%를 초과하면 경고."""
    returns = results.param_sensitivity_returns
    if not returns:
        return True, "파라미터 민감도 데이터 없음 — 스킵"

    base_return = results.total_return
    if abs(base_return) < 1e-9:
        return True, "기준 수익률 0 — 민감도 계산 생략"

    max_variance = max(abs(r - base_return) / abs(base_return) for r in returns)
    if max_variance > THRESHOLD_PARAM_SENSITIVITY:
        return (
            False,
            f"파라미터 민감도 최대 변동 {max_variance:.1%} > {THRESHOLD_PARAM_SENSITIVITY:.0%} — 파라미터 의존도 높음",
        )
    return True, f"파라미터 민감도 최대 변동 {max_variance:.1%} <= {THRESHOLD_PARAM_SENSITIVITY:.0%}"


def check_trade_count(results: BacktestSummary) -> Tuple[bool, str]:
    """거래 횟수가 30건 미만이면 통계적 유의성 부족 경고."""
    count = results.total_trades
    if count < THRESHOLD_MIN_TRADES:
        return (
            False,
            f"총 거래 {count}건 < {THRESHOLD_MIN_TRADES}건 — 통계적 유의성 부족",
        )
    return True, f"총 거래 {count}건 >= {THRESHOLD_MIN_TRADES}건"


def check_profit_factor_distribution(results: BacktestSummary) -> Tuple[bool, str]:
    """월별 profit factor 표준편차가 2.0을 초과하면 과적합 의심."""
    pf_list = results.monthly_profit_factors
    if len(pf_list) < 2:
        return True, "월별 profit factor 데이터 부족 — 스킵"

    std = float(np.std(pf_list, ddof=1))
    if std > THRESHOLD_MONTHLY_PF_STD:
        return (
            False,
            f"월별 profit factor 표준편차 {std:.2f} > {THRESHOLD_MONTHLY_PF_STD:.1f} — 성과 불안정",
        )
    return True, f"월별 profit factor 표준편차 {std:.2f} <= {THRESHOLD_MONTHLY_PF_STD:.1f}"


def check_max_consecutive_losses(results: BacktestSummary) -> Tuple[bool, str]:
    """연속 손실이 10건을 초과하면 전략 검토 권고."""
    pnls = results.trade_pnls
    if not pnls:
        return True, "거래 PnL 데이터 없음 — 스킵"

    max_consec = 0
    current = 0
    for pnl in pnls:
        if pnl < 0:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0

    if max_consec > THRESHOLD_MAX_CONSEC_LOSSES:
        return (
            False,
            f"최대 연속 손실 {max_consec}건 > {THRESHOLD_MAX_CONSEC_LOSSES}건 — 전략 검토 권고",
        )
    return True, f"최대 연속 손실 {max_consec}건 <= {THRESHOLD_MAX_CONSEC_LOSSES}건"


def check_sharpe_stability(results: BacktestSummary) -> Tuple[bool, str]:
    """분기별 Sharpe ratio 표준편차가 1.5를 초과하면 경고."""
    sharpe_list = results.quarterly_sharpe_ratios
    if len(sharpe_list) < 2:
        return True, "분기별 Sharpe ratio 데이터 부족 — 스킵"

    std = float(np.std(sharpe_list, ddof=1))
    if std > THRESHOLD_QUARTERLY_SHARPE_STD:
        return (
            False,
            f"분기별 Sharpe ratio 표준편차 {std:.2f} > {THRESHOLD_QUARTERLY_SHARPE_STD:.1f} — 성과 불안정",
        )
    return True, f"분기별 Sharpe ratio 표준편차 {std:.2f} <= {THRESHOLD_QUARTERLY_SHARPE_STD:.1f}"


# ---------------------------------------------------------------------------
# 결과 로드 헬퍼
# ---------------------------------------------------------------------------


def _load_backtest_json(path: Path) -> Optional[Dict[str, Any]]:
    """JSON 백테스트 결과 파일 로드. 실패 시 None 반환."""
    try:
        with open(path, encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
            return data
    except Exception:
        return None


def load_latest_backtest_results() -> Optional[BacktestSummary]:
    """data/backtest_results/ 에서 가장 최근 JSON 결과를 로드.

    결과 파일이 없거나 파싱에 실패하면 None 반환.
    현재 data/backtest_results/ 에는 PNG만 저장되어 있어
    JSON 파일이 없을 수 있습니다 — 체크들은 graceful skip 처리됩니다.
    """
    if not BACKTEST_RESULTS_DIR.exists():
        return None

    json_files = sorted(BACKTEST_RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        return None

    data = _load_backtest_json(json_files[0])
    if data is None:
        return None

    summary = BacktestSummary(
        total_return=data.get("total_return", 0.0),
        total_trades=data.get("total_trades", 0),
        profit_factor=data.get("profit_factor", 0.0),
        sharpe_ratio=data.get("sharpe_ratio", 0.0),
        is_return=data.get("is_return"),
        oos_return=data.get("oos_return"),
        param_sensitivity_returns=data.get("param_sensitivity_returns", []),
        trade_pnls=data.get("trade_pnls", []),
        monthly_profit_factors=data.get("monthly_profit_factors", []),
        quarterly_sharpe_ratios=data.get("quarterly_sharpe_ratios", []),
    )
    return summary


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

CHECK_FUNCTIONS = [
    ("IS/OOS 수익률 비교", check_in_out_sample),
    ("파라미터 민감도", check_parameter_sensitivity),
    ("거래 횟수 충분성", check_trade_count),
    ("Profit factor 분포", check_profit_factor_distribution),
    ("최대 연속 손실", check_max_consecutive_losses),
    ("Sharpe ratio 안정성", check_sharpe_stability),
]


def run_all_checks(results: BacktestSummary) -> List[OverfittingCheckResult]:
    """6개 과적합 체크를 모두 실행하고 결과 목록 반환."""
    check_results = []
    for name, fn in CHECK_FUNCTIONS:
        passed, message = fn(results)
        check_results.append(OverfittingCheckResult(name=name, passed=passed, message=message))
    return check_results


def print_report(check_results: List[OverfittingCheckResult]) -> None:
    """체크 결과를 포맷된 출력으로 표시."""
    print()
    print("=" * 60)
    print("  과적합 자동 점검 결과")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    warn_count = 0
    for i, result in enumerate(check_results, 1):
        status = "[PASS]" if result.passed else "[WARN]"
        if not result.passed:
            warn_count += 1
        print(f"\n  {i}. {result.name}")
        print(f"     {status} {result.message}")

    print()
    print("-" * 60)
    if warn_count == 0:
        print("  결과: 모든 체크 통과")
    else:
        print(f"  결과: {warn_count}개 경고 — 검토 권장 (차단하지 않음)")
    print()
    print("  ※ Walk-forward 분석 미실행 — v4.2.0에서 자동화 예정")
    print("    수동 검증 절차: docs/operations-guide.md 참조")
    print("=" * 60)
    print()


def main() -> None:
    results = load_latest_backtest_results()

    if results is None:
        # JSON 결과 파일 없음 — 빈 요약으로 graceful skip
        print()
        print("=" * 60)
        print("  과적합 자동 점검 결과")
        print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        print()
        print("  [INFO] data/backtest_results/ 에 JSON 결과 파일 없음")
        print("         scripts/run_backtest.py 실행 후 재점검하세요.")
        print()
        print("  ※ Walk-forward 분석 미실행 — v4.2.0에서 자동화 예정")
        print("=" * 60)
        print()
        sys.exit(0)

    check_results = run_all_checks(results)
    print_report(check_results)
    # 과적합 체크는 advisory — 항상 exit 0
    sys.exit(0)


if __name__ == "__main__":
    main()
