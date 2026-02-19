"""
analytics.py 단위 테스트
- R-배수, 기대값, 승/패 통계, 시스템 비교, 지수 계산
"""

import pytest
from src.analytics import (
    TradeAnalytics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_calmar_ratio,
)


# 테스트용 샘플 거래 데이터
SAMPLE_TRADES = [
    {
        "symbol": "SPY",
        "system": 1,
        "direction": "LONG",
        "entry_price": 450.0,
        "exit_price": 470.0,
        "stop_loss": 440.0,
        "total_shares": 100,
        "pnl": 2000.0,
        "entry_date": "2025-01-15",
        "exit_date": "2025-02-10",
    },
    {
        "symbol": "QQQ",
        "system": 1,
        "direction": "LONG",
        "entry_price": 380.0,
        "exit_price": 370.0,
        "stop_loss": 370.0,
        "total_shares": 50,
        "pnl": -500.0,
        "entry_date": "2025-02-01",
        "exit_date": "2025-02-20",
    },
    {
        "symbol": "AAPL",
        "system": 2,
        "direction": "LONG",
        "entry_price": 180.0,
        "exit_price": 200.0,
        "stop_loss": 170.0,
        "total_shares": 80,
        "pnl": 1600.0,
        "entry_date": "2025-01-20",
        "exit_date": "2025-03-15",
    },
    {
        "symbol": "TSLA",
        "system": 2,
        "direction": "LONG",
        "entry_price": 250.0,
        "exit_price": 230.0,
        "stop_loss": 240.0,
        "total_shares": 30,
        "pnl": -600.0,
        "entry_date": "2025-03-01",
        "exit_date": "2025-03-20",
    },
]


class TestRMultiples:
    """R-배수 계산 테스트"""

    def test_winning_trade_positive_r(self):
        """수익 거래는 R > 0"""
        winning_trade = [
            {
                "symbol": "SPY",
                "system": 1,
                "direction": "LONG",
                "entry_price": 450.0,
                "exit_price": 470.0,
                "stop_loss": 440.0,
                "total_shares": 100,
                "pnl": 2000.0,
                "entry_date": "2025-01-15",
                "exit_date": "2025-02-10",
            }
        ]
        analytics = TradeAnalytics(winning_trade)
        r_multiples = analytics.calculate_r_multiples()

        assert len(r_multiples) == 1
        assert r_multiples[0] > 0

    def test_losing_trade_negative_r(self):
        """손실 거래는 R < 0"""
        losing_trade = [
            {
                "symbol": "QQQ",
                "system": 1,
                "direction": "LONG",
                "entry_price": 380.0,
                "exit_price": 370.0,
                "stop_loss": 370.0,
                "total_shares": 50,
                "pnl": -500.0,
                "entry_date": "2025-02-01",
                "exit_date": "2025-02-20",
            }
        ]
        analytics = TradeAnalytics(losing_trade)
        r_multiples = analytics.calculate_r_multiples()

        assert len(r_multiples) == 1
        assert r_multiples[0] < 0

    def test_r_distribution_stats(self):
        """평균, 중앙값, 표준편차 계산 검증"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        dist = analytics.get_r_distribution()

        # 모든 키 존재 확인
        assert "mean_r" in dist
        assert "median_r" in dist
        assert "std_r" in dist
        assert "max_r" in dist
        assert "min_r" in dist
        assert "positive_count" in dist
        assert "negative_count" in dist

        # 기본 범위 검증
        assert dist["max_r"] >= dist["mean_r"] >= dist["min_r"]
        assert dist["std_r"] >= 0
        assert dist["positive_count"] + dist["negative_count"] == len(
            analytics.calculate_r_multiples()
        )

    def test_r_distribution_empty_trades(self):
        """거래 없을 때 기본값 반환"""
        analytics = TradeAnalytics([])
        dist = analytics.get_r_distribution()

        assert dist["mean_r"] == 0.0
        assert dist["positive_count"] == 0
        assert dist["negative_count"] == 0

    def test_zero_risk_trade_skipped(self):
        """스톱로스 = 진입가인 경우 (리스크 0) 스킵"""
        zero_risk_trade = [
            {
                "symbol": "TEST",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "stop_loss": 100.0,  # 진입가와 동일 → 리스크 0
                "total_shares": 10,
                "pnl": 100.0,
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-10",
            }
        ]
        analytics = TradeAnalytics(zero_risk_trade)
        r_multiples = analytics.calculate_r_multiples()

        # 리스크가 0이면 스킵되어 빈 리스트 반환
        assert len(r_multiples) == 0

    def test_r_value_correctness(self):
        """R-배수 수치 정확성 검증"""
        # SPY: entry=450, stop=440, shares=100, pnl=2000
        # risk = (450-440)*100 = 1000
        # R = 2000/1000 = 2.0
        spy_trade = [SAMPLE_TRADES[0]]
        analytics = TradeAnalytics(spy_trade)
        r_multiples = analytics.calculate_r_multiples()

        assert abs(r_multiples[0] - 2.0) < 0.001


class TestExpectancy:
    """기대값 계산 테스트"""

    def test_positive_expectancy(self):
        """양의 엣지를 가진 시스템"""
        # 높은 승률 + 큰 수익을 가진 거래 데이터
        good_trades = [
            {
                "symbol": "A",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 120.0,
                "stop_loss": 90.0,
                "total_shares": 10,
                "pnl": 200.0,  # R = 200/(10*10) = 2.0
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-15",
            },
            {
                "symbol": "B",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 115.0,
                "stop_loss": 90.0,
                "total_shares": 10,
                "pnl": 150.0,  # R = 150/100 = 1.5
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-15",
            },
            {
                "symbol": "C",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 95.0,
                "stop_loss": 90.0,
                "total_shares": 10,
                "pnl": -50.0,  # R = -50/100 = -0.5
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-15",
            },
        ]
        analytics = TradeAnalytics(good_trades)
        expectancy = analytics.get_expectancy()

        # 2/3 승률, 평균 수익 1.75R, 평균 손실 -0.5R → 기대값 양수
        assert expectancy > 0

    def test_negative_expectancy(self):
        """음의 엣지를 가진 시스템"""
        bad_trades = [
            {
                "symbol": "A",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "stop_loss": 90.0,
                "total_shares": 10,
                "pnl": 50.0,  # R = 50/100 = 0.5
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-15",
            },
            {
                "symbol": "B",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 80.0,
                "stop_loss": 90.0,
                "total_shares": 10,
                "pnl": -200.0,  # R = -200/100 = -2.0
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-15",
            },
            {
                "symbol": "C",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 85.0,
                "stop_loss": 90.0,
                "total_shares": 10,
                "pnl": -150.0,  # R = -150/100 = -1.5
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-15",
            },
        ]
        analytics = TradeAnalytics(bad_trades)
        expectancy = analytics.get_expectancy()

        # 1/3 승률, 평균 수익 0.5R, 평균 손실 -1.75R → 기대값 음수
        assert expectancy < 0

    def test_empty_trades_expectancy(self):
        """거래 없을 때 기대값 0"""
        analytics = TradeAnalytics([])
        assert analytics.get_expectancy() == 0.0


class TestWinLossStats:
    """승/패 통계 테스트"""

    def test_basic_stats(self):
        """승률, Profit Factor 기본 검증"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        stats = analytics.get_win_loss_stats()

        assert stats["total_trades"] == 4
        assert stats["winners"] == 2  # SPY($2000), AAPL($1600)
        assert stats["losers"] == 2   # QQQ(-$500), TSLA(-$600)
        assert abs(stats["win_rate"] - 0.5) < 0.001

        # Profit Factor = 총 수익 / 총 손실 = 3600 / 1100 ≈ 3.27
        assert stats["profit_factor"] > 1.0
        assert abs(stats["profit_factor"] - (3600 / 1100)) < 0.01

    def test_empty_trades(self):
        """거래 없을 때 기본값 반환 (ZeroDivisionError 방지)"""
        analytics = TradeAnalytics([])
        stats = analytics.get_win_loss_stats()

        assert stats["total_trades"] == 0
        assert stats["winners"] == 0
        assert stats["losers"] == 0
        assert stats["win_rate"] == 0.0
        assert stats["profit_factor"] == 0.0

    def test_all_winning_trades(self):
        """모든 거래가 수익인 경우"""
        all_wins = [
            {
                "symbol": "A",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "stop_loss": 90.0,
                "total_shares": 10,
                "pnl": 100.0,
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-10",
            },
            {
                "symbol": "B",
                "system": 2,
                "direction": "LONG",
                "entry_price": 200.0,
                "exit_price": 220.0,
                "stop_loss": 190.0,
                "total_shares": 5,
                "pnl": 100.0,
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-10",
            },
        ]
        analytics = TradeAnalytics(all_wins)
        stats = analytics.get_win_loss_stats()

        assert stats["win_rate"] == 1.0
        assert stats["losers"] == 0
        # 손실이 없으면 profit_factor = total_gains (손실=0)
        assert stats["profit_factor"] == 200.0

    def test_all_losing_trades(self):
        """모든 거래가 손실인 경우"""
        all_losses = [
            {
                "symbol": "A",
                "system": 1,
                "direction": "LONG",
                "entry_price": 100.0,
                "exit_price": 90.0,
                "stop_loss": 90.0,
                "total_shares": 10,
                "pnl": -100.0,
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-10",
            },
        ]
        analytics = TradeAnalytics(all_losses)
        stats = analytics.get_win_loss_stats()

        assert stats["win_rate"] == 0.0
        assert stats["winners"] == 0
        assert stats["largest_loss"] == -100.0


class TestSystemComparison:
    """시스템 비교 테스트"""

    def test_system1_vs_system2(self):
        """System 1과 System 2를 혼합한 거래 비교"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        comparison = analytics.get_system_comparison()

        assert "system_1" in comparison
        assert "system_2" in comparison

        # System 1: SPY($2000), QQQ(-$500) → 2건
        assert comparison["system_1"]["total_trades"] == 2

        # System 2: AAPL($1600), TSLA(-$600) → 2건
        assert comparison["system_2"]["total_trades"] == 2

        # System 1 total PnL = 2000 - 500 = 1500
        assert abs(comparison["system_1"]["total_pnl"] - 1500.0) < 0.01

        # System 2 total PnL = 1600 - 600 = 1000
        assert abs(comparison["system_2"]["total_pnl"] - 1000.0) < 0.01

    def test_system_comparison_only_one_system(self):
        """한 시스템의 거래만 있는 경우"""
        sys1_only = [t for t in SAMPLE_TRADES if t["system"] == 1]
        analytics = TradeAnalytics(sys1_only)
        comparison = analytics.get_system_comparison()

        assert comparison["system_1"]["total_trades"] == 2
        assert comparison["system_2"]["total_trades"] == 0

    def test_system_comparison_has_required_keys(self):
        """비교 결과에 필수 키 존재 확인"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        comparison = analytics.get_system_comparison()

        required_keys = [
            "total_trades", "winners", "losers", "win_rate",
            "avg_win", "avg_loss", "profit_factor",
            "largest_win", "largest_loss", "expectancy",
            "mean_r", "total_pnl",
        ]
        for key in required_keys:
            assert key in comparison["system_1"], f"system_1에 '{key}' 키 없음"
            assert key in comparison["system_2"], f"system_2에 '{key}' 키 없음"


class TestRatios:
    """샤프/소르티노/칼마 지수 테스트"""

    def test_sharpe_ratio_positive(self):
        """수익률이 일관된 시스템의 샤프 지수"""
        # 꾸준한 양의 수익률 (일별)
        good_returns = [0.001] * 200 + [-0.0005] * 52  # 대부분 양의 수익
        sharpe = calculate_sharpe_ratio(good_returns, risk_free_rate=0.03)

        # 양의 샤프 지수 기대
        assert sharpe > 0

    def test_sharpe_ratio_negative(self):
        """손실이 많은 시스템의 샤프 지수"""
        bad_returns = [-0.002] * 200 + [0.0005] * 52
        sharpe = calculate_sharpe_ratio(bad_returns, risk_free_rate=0.03)

        assert sharpe < 0

    def test_sharpe_ratio_empty(self):
        """빈 수익률 리스트"""
        assert calculate_sharpe_ratio([]) == 0.0
        assert calculate_sharpe_ratio([0.01]) == 0.0  # 단일 원소는 표준편차 계산 불가

    def test_sharpe_ratio_constant_returns(self):
        """모든 수익률이 동일한 경우 std=0 → 0.0 반환 (division by zero 방어)"""
        flat_returns = [0.001] * 100
        sharpe = calculate_sharpe_ratio(flat_returns)
        # std_return == 0이면 함수가 0.0을 반환 (infinity 방지)
        assert isinstance(sharpe, float)
        assert sharpe == 0.0

    def test_sortino_ratio(self):
        """소르티노 지수 - 하방 변동성만 사용"""
        # 하방 변동성이 있는 수익률
        mixed_returns = [0.002, -0.001, 0.003, -0.002, 0.001, 0.004, -0.0005]
        sortino = calculate_sortino_ratio(mixed_returns, risk_free_rate=0.03)

        # 결과값 타입 및 유한성 확인
        assert isinstance(sortino, float)
        assert not (sortino != sortino)  # NaN 체크

    def test_sortino_ratio_no_downside(self):
        """하방 수익률이 없는 경우"""
        # 모든 수익률이 무위험 수익률 이상
        positive_returns = [0.01, 0.02, 0.015, 0.008, 0.012]
        sortino = calculate_sortino_ratio(positive_returns, risk_free_rate=0.0)

        # 손실 없음 → 0 반환 (무한대 방지)
        assert sortino == 0.0

    def test_sortino_ratio_empty(self):
        """빈 수익률 리스트"""
        assert calculate_sortino_ratio([]) == 0.0

    def test_calmar_ratio(self):
        """칼마 지수 = CAGR / 최대낙폭"""
        cagr = 0.20    # 20% 연수익률
        max_dd = 0.10  # 10% 최대낙폭
        calmar = calculate_calmar_ratio(cagr, max_dd)

        assert abs(calmar - 2.0) < 0.001

    def test_calmar_ratio_zero_drawdown(self):
        """낙폭 0인 경우 (완벽한 시스템 → 0 반환)"""
        calmar = calculate_calmar_ratio(0.20, 0.0)
        assert calmar == 0.0

    def test_calmar_ratio_negative_cagr(self):
        """손실 시스템의 칼마 지수"""
        calmar = calculate_calmar_ratio(-0.05, 0.20)
        assert calmar < 0


class TestDrawdownAnalysis:
    """드로다운 분석 테스트"""

    def test_basic_drawdown(self):
        """기본 드로다운 계산"""
        # 100 → 120 → 90 → 110 형태의 자산 곡선
        equity = [100, 105, 110, 120, 115, 100, 90, 95, 105, 110]
        analytics = TradeAnalytics(SAMPLE_TRADES)
        result = analytics.get_drawdown_analysis(equity)

        assert "max_drawdown" in result
        assert "max_drawdown_pct" in result
        assert "max_drawdown_duration" in result
        assert "current_drawdown" in result
        assert "recovery_factor" in result

        # 최대 낙폭: 120 → 90 = 30
        assert abs(result["max_drawdown"] - 30.0) < 0.01

        # 최대 낙폭률: 30/120 = 25%
        assert abs(result["max_drawdown_pct"] - 25.0) < 0.01

    def test_monotonically_increasing(self):
        """계속 상승하는 자산 곡선"""
        equity = [100, 105, 110, 115, 120, 125]
        analytics = TradeAnalytics(SAMPLE_TRADES)
        result = analytics.get_drawdown_analysis(equity)

        assert result["max_drawdown"] == 0.0
        assert result["max_drawdown_pct"] == 0.0
        assert result["current_drawdown"] == 0.0

    def test_empty_equity_series(self):
        """빈 자산 시리즈"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        result = analytics.get_drawdown_analysis([])

        assert result["max_drawdown"] == 0.0
        assert result["max_drawdown_duration"] == 0


class TestMonthlyReturns:
    """월별 손익 테스트"""

    def test_monthly_grouping(self):
        """월별 집계 정확성"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        monthly = analytics.get_monthly_returns()

        # SPY: exit 2025-02-10 → 2025-02
        # QQQ: exit 2025-02-20 → 2025-02
        # AAPL: exit 2025-03-15 → 2025-03
        # TSLA: exit 2025-03-20 → 2025-03

        assert "2025-02" in monthly
        assert "2025-03" in monthly

        # 2025-02: SPY $2000 + QQQ -$500 = $1500
        assert abs(monthly["2025-02"] - 1500.0) < 0.01

        # 2025-03: AAPL $1600 + TSLA -$600 = $1000
        assert abs(monthly["2025-03"] - 1000.0) < 0.01

    def test_monthly_sorted(self):
        """월별 정렬 확인"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        monthly = analytics.get_monthly_returns()
        keys = list(monthly.keys())
        assert keys == sorted(keys)

    def test_empty_trades_monthly(self):
        """거래 없을 때 빈 딕셔너리 반환"""
        analytics = TradeAnalytics([])
        assert analytics.get_monthly_returns() == {}


class TestSummaryReport:
    """요약 리포트 생성 테스트"""

    def test_report_contains_korean(self):
        """한국어 텍스트 포함 여부"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        report = analytics.generate_summary_report()

        assert "터틀 트레이딩" in report
        assert "승률" in report
        assert "R-배수" in report

    def test_empty_trades_report(self):
        """거래 없을 때 안내 메시지 반환"""
        analytics = TradeAnalytics([])
        report = analytics.generate_summary_report()

        assert "데이터가 없습니다" in report

    def test_report_is_string(self):
        """반환값이 문자열인지 확인"""
        analytics = TradeAnalytics(SAMPLE_TRADES)
        report = analytics.generate_summary_report()
        assert isinstance(report, str)
        assert len(report) > 0
