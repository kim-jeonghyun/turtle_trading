"""
scripts/check_overfitting.py 단위 테스트

과적합 자동 점검 6개 체크 항목 검증:
- check_in_sample_vs_out_of_sample: IS/OOS 비교
- check_parameter_sensitivity: 파라미터 민감도
- check_trade_count: 거래 횟수 충분성
- check_profit_factor_distribution: PF 월별 분포
- check_max_consecutive_losses: 최대 연속 손실
- check_sharpe_stability: Sharpe 분기별 안정성
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.check_overfitting import (
    ALL_CHECKS,
    check_in_sample_vs_out_of_sample,
    check_max_consecutive_losses,
    check_parameter_sensitivity,
    check_profit_factor_distribution,
    check_sharpe_stability,
    check_trade_count,
    run_all_checks,
)

# ---------------------------------------------------------------------------
# 체크 1: IS/OOS 비교
# ---------------------------------------------------------------------------


def test_is_oos_pass() -> None:
    """OOS >= 50% of IS → pass"""
    results = {"in_sample_return": 0.20, "out_of_sample_return": 0.12}
    passed, msg = check_in_sample_vs_out_of_sample(results)
    assert passed is True
    assert "정상" in msg


def test_is_oos_warn() -> None:
    """OOS < 50% of IS → warn"""
    results = {"in_sample_return": 0.20, "out_of_sample_return": 0.05}
    passed, msg = check_in_sample_vs_out_of_sample(results)
    assert passed is False
    assert "과적합" in msg


def test_is_oos_skip() -> None:
    """IS <= 0 → skip (pass)"""
    results = {"in_sample_return": -0.05, "out_of_sample_return": 0.10}
    passed, msg = check_in_sample_vs_out_of_sample(results)
    assert passed is True
    assert "스킵" in msg


# ---------------------------------------------------------------------------
# 체크 2: 파라미터 민감도
# ---------------------------------------------------------------------------


def test_parameter_sensitivity_pass() -> None:
    """deviation < 30% → pass"""
    results = {
        "parameter_sensitivity": {
            "base_return": 0.20,
            "varied_returns": [0.18, 0.22],
        }
    }
    passed, msg = check_parameter_sensitivity(results)
    assert passed is True
    assert "정상" in msg


def test_parameter_sensitivity_warn() -> None:
    """deviation > 30% → warn"""
    results = {
        "parameter_sensitivity": {
            "base_return": 0.20,
            "varied_returns": [0.05, 0.35],
        }
    }
    passed, msg = check_parameter_sensitivity(results)
    assert passed is False
    assert "과적합" in msg


def test_parameter_sensitivity_skip_no_data() -> None:
    """민감도 데이터 없음 → skip (pass)"""
    passed, msg = check_parameter_sensitivity({})
    assert passed is True
    assert "스킵" in msg


# ---------------------------------------------------------------------------
# 체크 3: 거래 횟수 충분성
# ---------------------------------------------------------------------------


def test_trade_count_sufficient() -> None:
    """>= 30 → pass"""
    passed, msg = check_trade_count({"total_trades": 50})
    assert passed is True
    assert "충분" in msg


def test_trade_count_insufficient() -> None:
    """< 30 → warn"""
    passed, msg = check_trade_count({"total_trades": 15})
    assert passed is False
    assert "유의성" in msg


def test_trade_count_exactly_30() -> None:
    """exactly 30 → pass (boundary)"""
    passed, msg = check_trade_count({"total_trades": 30})
    assert passed is True


def test_trade_count_zero() -> None:
    """0건 → warn"""
    passed, msg = check_trade_count({"total_trades": 0})
    assert passed is False


# ---------------------------------------------------------------------------
# 체크 4: PF 월별 분포
# ---------------------------------------------------------------------------


def test_profit_factor_stable() -> None:
    """std < 2.0 → pass"""
    results = {"monthly_profit_factors": [1.2, 1.4, 1.3, 1.1, 1.5]}
    passed, msg = check_profit_factor_distribution(results)
    assert passed is True
    assert "정상" in msg


def test_profit_factor_unstable() -> None:
    """std > 2.0 → warn"""
    results = {"monthly_profit_factors": [0.5, 5.0, 0.3, 6.0, 0.1]}
    passed, msg = check_profit_factor_distribution(results)
    assert passed is False
    assert "과적합" in msg


def test_profit_factor_skip_insufficient() -> None:
    """데이터 < 3개 → skip (pass)"""
    results = {"monthly_profit_factors": [1.2, 1.5]}
    passed, msg = check_profit_factor_distribution(results)
    assert passed is True
    assert "스킵" in msg


# ---------------------------------------------------------------------------
# 체크 5: 최대 연속 손실
# ---------------------------------------------------------------------------


def test_consecutive_losses_ok() -> None:
    """<= 10 → pass"""
    passed, msg = check_max_consecutive_losses({"max_consecutive_losses": 7})
    assert passed is True
    assert "정상" in msg


def test_consecutive_losses_warn() -> None:
    """> 10 → warn"""
    passed, msg = check_max_consecutive_losses({"max_consecutive_losses": 13})
    assert passed is False
    assert "전략 검토" in msg


def test_consecutive_losses_exactly_10() -> None:
    """exactly 10 → pass (boundary)"""
    passed, msg = check_max_consecutive_losses({"max_consecutive_losses": 10})
    assert passed is True


# ---------------------------------------------------------------------------
# 체크 6: Sharpe 분기별 안정성
# ---------------------------------------------------------------------------


def test_sharpe_stable() -> None:
    """std < 1.5 → pass"""
    results = {"quarterly_sharpe_ratios": [1.2, 1.0, 1.3, 0.9]}
    passed, msg = check_sharpe_stability(results)
    assert passed is True
    assert "안정" in msg


def test_sharpe_unstable() -> None:
    """std > 1.5 → warn"""
    results = {"quarterly_sharpe_ratios": [-1.0, 3.5, -0.5, 4.0]}
    passed, msg = check_sharpe_stability(results)
    assert passed is False
    assert "불안정" in msg


def test_sharpe_skip_insufficient() -> None:
    """데이터 < 2개 → skip (pass)"""
    results = {"quarterly_sharpe_ratios": [1.2]}
    passed, msg = check_sharpe_stability(results)
    assert passed is True
    assert "스킵" in msg


# ---------------------------------------------------------------------------
# 통합 테스트
# ---------------------------------------------------------------------------


def test_run_all_checks_mixed() -> None:
    """혼합 결과: 일부 pass, 일부 warn"""
    results = {
        "in_sample_return": 0.20,
        "out_of_sample_return": 0.05,  # warn: OOS < 50%
        "total_trades": 50,  # pass
        "max_consecutive_losses": 5,  # pass
        # parameter_sensitivity 없음 → skip
        # monthly_profit_factors 없음 → skip
        # quarterly_sharpe_ratios 없음 → skip
    }
    outcomes = run_all_checks(results)
    assert len(outcomes) == len(ALL_CHECKS)

    # IS/OOS 체크는 warn이어야 함
    name, passed, msg = outcomes[0]
    assert name == "IS/OOS 비교"
    assert passed is False

    # 거래 횟수 체크는 pass이어야 함
    name, passed, msg = outcomes[2]
    assert name == "거래 횟수 충분성"
    assert passed is True


def test_run_all_checks_all_pass() -> None:
    """모든 체크 통과"""
    results = {
        "in_sample_return": 0.20,
        "out_of_sample_return": 0.15,
        "parameter_sensitivity": {
            "base_return": 0.20,
            "varied_returns": [0.19, 0.21],
        },
        "total_trades": 60,
        "monthly_profit_factors": [1.2, 1.3, 1.1, 1.4, 1.2],
        "max_consecutive_losses": 4,
        "quarterly_sharpe_ratios": [1.0, 1.2, 0.9, 1.1],
    }
    outcomes = run_all_checks(results)
    assert all(passed for _, passed, _ in outcomes)


def test_run_all_checks_exception_handling() -> None:
    """체크 중 예외 발생 시 스킵 처리"""
    # 잘못된 타입으로 예외 유도
    results = {
        "monthly_profit_factors": "not-a-list",  # np.std가 실패할 수 있음
    }
    outcomes = run_all_checks(results)
    # 예외가 발생해도 전체 체크는 완료되어야 함
    assert len(outcomes) == len(ALL_CHECKS)
