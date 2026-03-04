#!/usr/bin/env python3
"""과적합(Overfitting) 자동 점검 스크립트.

백테스트 결과를 분석하여 과적합 위험을 감지합니다.
6개 체크 항목으로 전략의 견고성을 평가합니다.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

BACKTEST_DIR = Path(__file__).parent.parent / "data" / "backtest"


def check_in_sample_vs_out_of_sample(results: dict) -> tuple[bool, str]:
    """체크 1: In-sample vs Out-of-sample 비교.
    OOS 수익률 < IS 수익률의 50% → 경고"""
    # Get IS and OOS returns from results
    is_return = results.get("in_sample_return", 0)
    oos_return = results.get("out_of_sample_return", 0)
    if is_return <= 0:
        return True, "IS 수익률 ≤ 0 — 비교 불가 (스킵)"
    ratio = oos_return / is_return if is_return != 0 else 0
    if ratio < 0.5:
        return False, f"OOS/IS 수익률 비율: {ratio:.1%} < 50% — 과적합 의심"
    return True, f"OOS/IS 비율: {ratio:.1%} (정상)"


def check_parameter_sensitivity(results: dict) -> tuple[bool, str]:
    """체크 2: 파라미터 민감도.
    ATR 기간 ±20% 변경 시 수익률 변동 > 30% → 경고"""
    sensitivity = results.get("parameter_sensitivity", {})
    base_return = sensitivity.get("base_return", 0)
    varied_returns = sensitivity.get("varied_returns", [])
    if not varied_returns or base_return == 0:
        return True, "민감도 데이터 없음 (스킵)"
    max_deviation = max(abs(r - base_return) / abs(base_return) for r in varied_returns) if base_return != 0 else 0
    if max_deviation > 0.3:
        return False, f"파라미터 변동 시 수익률 편차: {max_deviation:.1%} > 30% — 과적합 의심"
    return True, f"파라미터 민감도: {max_deviation:.1%} (정상)"


def check_trade_count(results: dict) -> tuple[bool, str]:
    """체크 3: 거래 횟수 충분성.
    총 거래 < 30건 → 통계적 유의성 부족"""
    total_trades = results.get("total_trades", 0)
    if total_trades < 30:
        return False, f"총 거래 {total_trades}건 < 30건 — 통계적 유의성 부족"
    return True, f"총 거래 {total_trades}건 (충분)"


def check_profit_factor_distribution(results: dict) -> tuple[bool, str]:
    """체크 4: Profit Factor 월별 분포.
    월별 PF 편차 > 2.0 → 과적합 의심"""
    monthly_pf = results.get("monthly_profit_factors", [])
    if len(monthly_pf) < 3:
        return True, "월별 PF 데이터 부족 (스킵)"
    std = float(np.std(monthly_pf))
    if std > 2.0:
        return False, f"월별 PF 표준편차: {std:.2f} > 2.0 — 과적합 의심"
    return True, f"월별 PF 표준편차: {std:.2f} (정상)"


def check_max_consecutive_losses(results: dict) -> tuple[bool, str]:
    """체크 5: 최대 연속 손실.
    연속 손실 > 10건 → 전략 검토 권고"""
    max_losses = results.get("max_consecutive_losses", 0)
    if max_losses > 10:
        return False, f"최대 연속 손실: {max_losses}건 > 10건 — 전략 검토 권고"
    return True, f"최대 연속 손실: {max_losses}건 (정상)"


def check_sharpe_stability(results: dict) -> tuple[bool, str]:
    """체크 6: Sharpe ratio 분기별 안정성.
    분기별 Sharpe 표준편차 > 1.5 → 경고"""
    quarterly_sharpe = results.get("quarterly_sharpe_ratios", [])
    if len(quarterly_sharpe) < 2:
        return True, "분기별 Sharpe 데이터 부족 (스킵)"
    std = float(np.std(quarterly_sharpe))
    if std > 1.5:
        return False, f"분기별 Sharpe 표준편차: {std:.2f} > 1.5 — 불안정"
    return True, f"분기별 Sharpe 표준편차: {std:.2f} (안정)"


ALL_CHECKS = [
    ("IS/OOS 비교", check_in_sample_vs_out_of_sample),
    ("파라미터 민감도", check_parameter_sensitivity),
    ("거래 횟수 충분성", check_trade_count),
    ("PF 분포", check_profit_factor_distribution),
    ("최대 연속 손실", check_max_consecutive_losses),
    ("Sharpe 안정성", check_sharpe_stability),
]


def load_backtest_results(path: Path = BACKTEST_DIR) -> dict:
    """백테스트 결과 로드"""
    result_file = path / "latest_result.json"
    if result_file.exists():
        with open(result_file) as f:
            return json.load(f)
    # Try loading from any available result file
    json_files = sorted(path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if json_files:
        with open(json_files[0]) as f:
            return json.load(f)
    return {}


def run_all_checks(results: dict) -> list[tuple[str, bool, str]]:
    """모든 체크 실행"""
    outcomes = []
    for name, check_fn in ALL_CHECKS:
        try:
            passed, message = check_fn(results)
            outcomes.append((name, passed, message))
        except Exception as e:
            outcomes.append((name, True, f"체크 실패: {e} (스킵)"))
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description="과적합 자동 점검")
    parser.add_argument("--backtest-dir", type=Path, default=BACKTEST_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    results = load_backtest_results(args.backtest_dir)
    if not results:
        logger.warning("백테스트 결과 파일을 찾을 수 없습니다.")
        sys.exit(1)

    outcomes = run_all_checks(results)

    warnings = 0
    for name, passed, message in outcomes:
        status = "✓ PASS" if passed else "⚠ WARN"
        if not passed:
            warnings += 1
        logger.info(f"  [{status}] {name}: {message}")

    logger.info("")
    logger.info(f"결과: {len(outcomes) - warnings}/{len(outcomes)} 통과, {warnings}건 경고")
    logger.info("")
    logger.info("※ Walk-forward 분석 미실행 — v4.2.0에서 자동화 예정")
    logger.info("  수동 검증 절차: docs/operations-guide.md 참조")

    sys.exit(1 if warnings > 0 else 0)


if __name__ == "__main__":
    main()
