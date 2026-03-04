"""
tests/test_check_overfitting.py

과적합 자동 점검 스크립트 단위 테스트.
실제 백테스트 결과 파일 없이 mock 데이터로 검증합니다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.check_overfitting import (
    BacktestSummary,
    check_in_out_sample,
    check_max_consecutive_losses,
    check_parameter_sensitivity,
    check_profit_factor_distribution,
    check_sharpe_stability,
    check_trade_count,
    run_all_checks,
)

# ---------------------------------------------------------------------------
# check_in_out_sample
# ---------------------------------------------------------------------------


def test_in_out_sample_pass():
    """OOS/IS 비율 >= 0.5 이면 pass."""
    results = BacktestSummary(is_return=0.20, oos_return=0.15)
    passed, msg = check_in_out_sample(results)
    assert passed is True
    assert "IS" in msg and "OOS" in msg


def test_in_out_sample_warn():
    """OOS/IS 비율 < 0.5 이면 warn."""
    results = BacktestSummary(is_return=0.20, oos_return=0.05)
    passed, msg = check_in_out_sample(results)
    assert passed is False
    assert "과적합" in msg


def test_in_out_sample_no_data_skips():
    """IS/OOS 데이터가 없으면 스킵 (pass)."""
    results = BacktestSummary()  # is_return, oos_return = None
    passed, msg = check_in_out_sample(results)
    assert passed is True
    assert "스킵" in msg


def test_in_out_sample_is_zero_skips():
    """IS 수익률이 0 이하이면 비율 계산 생략 (pass)."""
    results = BacktestSummary(is_return=0.0, oos_return=0.10)
    passed, msg = check_in_out_sample(results)
    assert passed is True


def test_in_out_sample_exact_boundary():
    """OOS/IS 비율이 정확히 0.5이면 pass (경계값)."""
    results = BacktestSummary(is_return=0.20, oos_return=0.10)
    passed, _ = check_in_out_sample(results)
    assert passed is True


# ---------------------------------------------------------------------------
# check_parameter_sensitivity
# ---------------------------------------------------------------------------


def test_parameter_sensitivity_pass():
    """파라미터 변동이 30% 이하이면 pass."""
    results = BacktestSummary(
        total_return=0.20,
        param_sensitivity_returns=[0.18, 0.22],  # 10% 변동
    )
    passed, msg = check_parameter_sensitivity(results)
    assert passed is True
    assert "%" in msg


def test_parameter_sensitivity_warn():
    """파라미터 변동이 30%를 초과하면 warn."""
    results = BacktestSummary(
        total_return=0.20,
        param_sensitivity_returns=[0.08, 0.22],  # 60% 변동
    )
    passed, msg = check_parameter_sensitivity(results)
    assert passed is False
    assert "파라미터" in msg


def test_parameter_sensitivity_no_data_skips():
    """민감도 데이터 없으면 스킵 (pass)."""
    results = BacktestSummary(total_return=0.20)
    passed, msg = check_parameter_sensitivity(results)
    assert passed is True
    assert "스킵" in msg


# ---------------------------------------------------------------------------
# check_trade_count
# ---------------------------------------------------------------------------


def test_trade_count_pass():
    """거래 횟수 >= 30 이면 pass."""
    results = BacktestSummary(total_trades=30)
    passed, msg = check_trade_count(results)
    assert passed is True
    assert "30" in msg


def test_trade_count_warn():
    """거래 횟수 < 30 이면 warn."""
    results = BacktestSummary(total_trades=15)
    passed, msg = check_trade_count(results)
    assert passed is False
    assert "통계적 유의성" in msg


def test_trade_count_zero_warns():
    """거래 횟수 0 이면 warn."""
    results = BacktestSummary(total_trades=0)
    passed, _ = check_trade_count(results)
    assert passed is False


def test_trade_count_boundary():
    """경계값 29 → warn, 30 → pass."""
    assert check_trade_count(BacktestSummary(total_trades=29))[0] is False
    assert check_trade_count(BacktestSummary(total_trades=30))[0] is True


# ---------------------------------------------------------------------------
# check_profit_factor_distribution
# ---------------------------------------------------------------------------


def test_profit_factor_distribution_pass():
    """월별 PF 표준편차 <= 2.0 이면 pass."""
    results = BacktestSummary(monthly_profit_factors=[1.2, 1.5, 1.3, 1.4, 1.1])
    passed, msg = check_profit_factor_distribution(results)
    assert passed is True


def test_profit_factor_distribution_warn():
    """월별 PF 표준편차 > 2.0 이면 warn."""
    results = BacktestSummary(monthly_profit_factors=[0.5, 5.0, 0.3, 6.0, 0.2])
    passed, msg = check_profit_factor_distribution(results)
    assert passed is False
    assert "성과 불안정" in msg


def test_profit_factor_distribution_insufficient_data_skips():
    """데이터 1건이면 스킵 (pass)."""
    results = BacktestSummary(monthly_profit_factors=[1.5])
    passed, msg = check_profit_factor_distribution(results)
    assert passed is True
    assert "스킵" in msg


# ---------------------------------------------------------------------------
# check_max_consecutive_losses
# ---------------------------------------------------------------------------


def test_max_consecutive_losses_pass():
    """연속 손실 <= 10 이면 pass."""
    # 손실 8연속
    pnls = [-100.0] * 8 + [200.0] + [-50.0] * 3
    results = BacktestSummary(trade_pnls=pnls)
    passed, msg = check_max_consecutive_losses(results)
    assert passed is True
    assert "8" in msg


def test_max_consecutive_losses_warn():
    """연속 손실 > 10 이면 warn."""
    pnls = [-100.0] * 11 + [200.0]
    results = BacktestSummary(trade_pnls=pnls)
    passed, msg = check_max_consecutive_losses(results)
    assert passed is False
    assert "11" in msg
    assert "전략 검토" in msg


def test_max_consecutive_losses_no_data_skips():
    """거래 PnL 데이터 없으면 스킵 (pass)."""
    results = BacktestSummary()
    passed, msg = check_max_consecutive_losses(results)
    assert passed is True
    assert "스킵" in msg


def test_max_consecutive_losses_all_wins():
    """모두 수익이면 pass (연속 손실 0)."""
    results = BacktestSummary(trade_pnls=[100.0, 200.0, 150.0])
    passed, _ = check_max_consecutive_losses(results)
    assert passed is True


def test_max_consecutive_losses_boundary():
    """경계값: 연속 손실 10 → pass, 11 → warn."""
    results_10 = BacktestSummary(trade_pnls=[-1.0] * 10 + [1.0])
    results_11 = BacktestSummary(trade_pnls=[-1.0] * 11 + [1.0])
    assert check_max_consecutive_losses(results_10)[0] is True
    assert check_max_consecutive_losses(results_11)[0] is False


# ---------------------------------------------------------------------------
# check_sharpe_stability
# ---------------------------------------------------------------------------


def test_sharpe_stability_pass():
    """분기별 Sharpe 표준편차 <= 1.5 이면 pass."""
    results = BacktestSummary(quarterly_sharpe_ratios=[1.2, 1.0, 1.4, 1.1])
    passed, msg = check_sharpe_stability(results)
    assert passed is True


def test_sharpe_stability_warn():
    """분기별 Sharpe 표준편차 > 1.5 이면 warn."""
    results = BacktestSummary(quarterly_sharpe_ratios=[-2.0, 3.5, -1.5, 4.0])
    passed, msg = check_sharpe_stability(results)
    assert passed is False
    assert "성과 불안정" in msg


def test_sharpe_stability_insufficient_data_skips():
    """데이터 1건이면 스킵 (pass)."""
    results = BacktestSummary(quarterly_sharpe_ratios=[1.2])
    passed, msg = check_sharpe_stability(results)
    assert passed is True
    assert "스킵" in msg


def test_sharpe_stability_no_data_skips():
    """데이터 없으면 스킵 (pass)."""
    results = BacktestSummary()
    passed, msg = check_sharpe_stability(results)
    assert passed is True
    assert "스킵" in msg


# ---------------------------------------------------------------------------
# run_all_checks 통합
# ---------------------------------------------------------------------------


def test_run_all_checks_returns_six_results():
    """run_all_checks 는 항상 6개 결과를 반환한다."""
    results = BacktestSummary(total_trades=50)
    check_results = run_all_checks(results)
    assert len(check_results) == 6


def test_run_all_checks_all_pass():
    """충분한 데이터가 제공되면 모두 pass 가능."""
    results = BacktestSummary(
        total_return=0.20,
        total_trades=50,
        is_return=0.20,
        oos_return=0.15,
        param_sensitivity_returns=[0.18, 0.22],
        trade_pnls=[-100.0] * 5 + [500.0],
        monthly_profit_factors=[1.2, 1.3, 1.1, 1.4, 1.2, 1.3],
        quarterly_sharpe_ratios=[1.0, 1.2, 0.9, 1.1],
    )
    check_results = run_all_checks(results)
    failed = [r for r in check_results if not r.passed]
    assert len(failed) == 0, f"예상치 못한 WARN: {[r.message for r in failed]}"


def test_run_all_checks_detects_warns():
    """과적합 시그널이 있는 데이터에서 warn을 올바르게 감지."""
    results = BacktestSummary(
        total_return=0.20,
        total_trades=5,  # < 30 → warn
        is_return=0.20,
        oos_return=0.05,  # ratio 0.25 < 0.5 → warn
        trade_pnls=[-100.0] * 12,  # 12연속 손실 → warn
    )
    check_results = run_all_checks(results)
    failed = [r for r in check_results if not r.passed]
    assert len(failed) >= 3
