#!/usr/bin/env python3
"""
터틀 트레이딩 백테스터 CLI 스크립트

Usage:
    python scripts/run_backtest.py --symbols SPY QQQ --period 2y --system 1 --capital 100000
    python scripts/run_backtest.py --symbols SPY --system 2 --plot
    python scripts/run_backtest.py --symbols AAPL NVDA TSLA --system 1 --csv results.csv
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from src.backtester import BacktestConfig, BacktestResult, TurtleBacktester
from src.data_fetcher import DataFetcher
from src.universe_manager import UniverseManager

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """CLI 인자 파싱"""
    parser = argparse.ArgumentParser(
        description="터틀 트레이딩 백테스터", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # 필수 인자
    parser.add_argument("--symbols", nargs="+", required=False, help="백테스트할 티커 심볼 (공백으로 구분)")

    # 데이터 인자
    parser.add_argument("--period", default="2y", help="데이터 기간 (1y, 2y, 5y, max 등)")

    # 백테스트 설정
    parser.add_argument(
        "--system", type=int, choices=[1, 2], default=1, help="터틀 시스템 (1: 20일/10일, 2: 55일/20일)"
    )
    parser.add_argument("--capital", type=float, default=100000.0, help="초기 자본금")
    parser.add_argument("--risk", type=float, default=0.01, help="유닛당 리스크 비율 (0.01 = 1%%)")
    parser.add_argument("--commission", type=float, default=0.001, help="수수료 비율 (0.001 = 0.1%%)")
    parser.add_argument("--no-filter", action="store_true", help="System 1 필터 비활성화")
    parser.add_argument("--no-risk-limits", action="store_true", help="포트폴리오 리스크 한도 비활성화")
    parser.add_argument("--trend-filter", action="store_true", help="트렌드 품질 필터 활성화 (기본: OFF)")
    parser.add_argument("--er-threshold", type=float, default=0.3, help="ER 임계값 오버라이드")
    parser.add_argument("--regime-proxy", type=str, default=None, help="레짐 판별용 인덱스 프록시 심볼")

    # 다통화 모드
    parser.add_argument("--multi-currency", action="store_true", help="통화별 분리 백테스트 (KRW/USD 독립 포트폴리오)")
    parser.add_argument(
        "--krw-capital", type=float, default=100_000_000.0, help="KRW 포트폴리오 초기 자본 (기본: 1억원)"
    )
    parser.add_argument(
        "--usd-capital", type=float, default=100_000.0, help="USD 포트폴리오 초기 자본 (기본: $100,000)"
    )

    # 출력 옵션
    parser.add_argument("--plot", action="store_true", help="자본 곡선 및 낙폭 차트 생성 (PNG 저장)")
    parser.add_argument("--csv", type=str, help="거래 내역 CSV 파일 경로")
    parser.add_argument("--verbose", action="store_true", help="상세 로깅 출력")

    return parser.parse_args()


def setup_logging(verbose: bool):
    """로깅 설정"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )


def fetch_data(symbols: list, period: str, verbose: bool) -> Dict[str, pd.DataFrame]:
    """데이터 수집"""
    fetcher = DataFetcher(default_period=period)

    if verbose:
        logger.info(f"데이터 수집 중: {', '.join(symbols)}")

    data = fetcher.fetch_multiple(symbols, period=period)

    if not data:
        logger.error("데이터 수집 실패: 모든 종목에 대해 데이터를 가져올 수 없습니다.")
        sys.exit(1)

    missing = set(symbols) - set(data.keys())
    if missing:
        logger.warning(f"데이터 수집 실패한 종목: {', '.join(missing)}")

    for symbol, df in data.items():
        logger.info(f"{symbol}: {len(df)} 행 ({df['date'].min()} ~ {df['date'].max()})")

    return data


def run_backtest(data: Dict[str, pd.DataFrame], args: argparse.Namespace) -> BacktestResult:
    """백테스트 실행"""
    config = BacktestConfig(
        initial_capital=args.capital,
        risk_percent=args.risk,
        system=args.system,
        max_units=4,
        pyramid_interval_n=0.5,
        stop_distance_n=2.0,
        use_filter=not args.no_filter,
        commission_pct=args.commission,
        use_trend_quality_filter=args.trend_filter,
        er_threshold=args.er_threshold,
        regime_proxy_symbol=args.regime_proxy,
    )

    logger.info(f"백테스트 시작 - System {config.system}, 초기 자본: ${config.initial_capital:,.0f}")

    # short_restricted는 시장 실현가능성 제약이므로 항상 로드
    um = UniverseManager(yaml_path=str(Path(__file__).parent.parent / "config" / "universe.yaml"))
    short_restricted_symbols = um.get_short_restricted_symbols()

    symbol_groups = None
    if not args.no_risk_limits:
        full_mapping = um.get_group_mapping()
        symbol_groups = {s: full_mapping[s] for s in data.keys() if s in full_mapping}
        unmapped = set(data.keys()) - set(full_mapping.keys())
        if unmapped:
            logger.warning(f"universe.yaml에 미등록 종목 (US_EQUITY로 기본 분류): {', '.join(sorted(unmapped))}")
        if not symbol_groups:
            logger.warning("심볼이 universe.yaml에 없어 리스크 한도 미적용")
            symbol_groups = None

    if symbol_groups:
        logger.info(f"리스크 한도 적용: {len(symbol_groups)}개 종목")
    else:
        logger.info("리스크 한도 미적용 (--no-risk-limits 또는 미등록 종목)")

    backtester = TurtleBacktester(
        config,
        symbol_groups=symbol_groups,
        short_restricted_symbols=short_restricted_symbols,
    )
    result = backtester.run(data)

    return result


def print_results(result: BacktestResult):
    """백테스트 결과 출력"""
    print("\n" + "=" * 60)
    print("백테스트 결과 요약")
    print("=" * 60)

    print(f"\n초기 자본:         ${result.config.initial_capital:,.2f}")
    print(f"최종 자본:         ${result.final_equity:,.2f}")
    print(f"총 수익률:         {result.total_return * 100:.2f}%")
    print(f"CAGR:             {result.cagr * 100:.2f}%")
    print(f"최대 낙폭:         {result.max_drawdown * 100:.2f}%")
    print(f"샤프 비율:         {result.sharpe_ratio:.2f}")

    print(f"\n총 거래:           {result.total_trades}")
    print(f"승리 거래:         {result.winning_trades}")
    print(f"패배 거래:         {result.losing_trades}")
    print(f"승률:             {result.win_rate * 100:.2f}%")
    print(f"수익 팩터:         {result.profit_factor:.2f}")

    print(f"\n평균 승리:         ${result.avg_win:,.2f}")
    print(f"평균 손실:         ${result.avg_loss:,.2f}")

    if result.filter_stats:
        print("\n--- Trend Quality Filter ---")
        print(f"검사 시그널:       {result.filter_stats.total_checked}")
        print(f"레짐 차단:         {result.filter_stats.blocked_by_regime}")
        print(f"ER 차단:           {result.filter_stats.blocked_by_er}")
        print(f"통과:             {result.filter_stats.passed}")
        print(f"차단율:           {result.filter_stats.block_rate * 100:.1f}%")

    print("\n" + "=" * 60)


def plot_equity_curve(result: BacktestResult, symbols: list):
    """자본 곡선 및 낙폭 차트 생성"""
    output_dir = Path("data/backtest_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    symbols_str = "_".join(symbols[:3])  # 최대 3개 종목명
    if len(symbols) > 3:
        symbols_str += f"_and_{len(symbols) - 3}_more"
    filename = f"backtest_{symbols_str}_sys{result.config.system}_{timestamp}.png"
    output_path = output_dir / filename

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # 자본 곡선
    equity_df = result.equity_curve
    ax1.plot(equity_df["date"], equity_df["equity"], label="Equity", linewidth=2, color="#2E86AB")
    ax1.axhline(
        y=result.config.initial_capital, color="#A23B72", linestyle="--", linewidth=1.5, label="Initial Capital"
    )
    ax1.set_ylabel("Equity ($)", fontsize=12)
    ax1.set_title(
        f"Turtle Trading System {result.config.system} - {', '.join(symbols)}", fontsize=14, fontweight="bold"
    )
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))

    # 낙폭
    equity_df["peak"] = equity_df["equity"].cummax()
    equity_df["drawdown"] = (equity_df["peak"] - equity_df["equity"]) / equity_df["peak"] * 100
    ax2.fill_between(equity_df["date"], equity_df["drawdown"], 0, color="#F18F01", alpha=0.5, label="Drawdown")
    ax2.set_xlabel("Date", fontsize=12)
    ax2.set_ylabel("Drawdown (%)", fontsize=12)
    ax2.legend(loc="lower left")
    ax2.grid(True, alpha=0.3)
    ax2.invert_yaxis()

    # x축 포맷
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    logger.info(f"차트 저장: {output_path}")
    print(f"\n차트 저장됨: {output_path}")


def export_trades_csv(result: BacktestResult, csv_path: str):
    """거래 내역 CSV 저장"""
    trades_data = []
    for trade in result.trades:
        trades_data.append(
            {
                "symbol": trade.symbol,
                "direction": trade.direction,
                "entry_date": trade.entry_date.strftime("%Y-%m-%d") if trade.entry_date else None,
                "entry_price": trade.entry_price,
                "exit_date": trade.exit_date.strftime("%Y-%m-%d") if trade.exit_date else None,
                "exit_price": trade.exit_price,
                "quantity": trade.quantity,
                "pnl": trade.pnl,
                "pnl_pct": trade.pnl_pct * 100,  # 백분율로 변환
                "entry_reason": trade.entry_reason,
                "er_at_entry": trade.er_at_entry,
                "exit_reason": trade.exit_reason,
            }
        )

    df = pd.DataFrame(trades_data)
    df.to_csv(csv_path, index=False)
    logger.info(f"거래 내역 저장: {csv_path}")
    print(f"\n거래 내역 저장됨: {csv_path}")


def print_multi_currency_results(mc_result):
    """통화별 백테스트 결과 출력"""
    if not mc_result.results:
        logger.warning("통화별 결과가 없습니다.")
        return

    for currency, result in mc_result.results.items():
        symbol = "₩" if currency == "KRW" else "$"
        print(f"\n{'=' * 60}")
        print(f"[{currency} Portfolio]")
        print(f"{'=' * 60}")
        print(f"  초기 자본:      {symbol}{result.config.initial_capital:,.0f}")
        print(f"  최종 자본:      {symbol}{result.final_equity:,.0f}")
        print(f"  총 수익률:      {result.total_return:.1%}")
        print(f"  CAGR:          {result.cagr:.1%}")
        print(f"  최대 낙폭:      {result.max_drawdown:.1%}")
        print(f"  샤프 비율:      {result.sharpe_ratio:.2f}")
        print(f"  총 거래:        {result.total_trades}")
        print(f"  승률:          {result.win_rate:.1%}")
        print(f"  수익 팩터:      {result.profit_factor:.2f}")


def main():
    """메인 함수"""
    args = parse_args()
    setup_logging(args.verbose)

    if not args.multi_currency and not args.symbols:
        print("error: --symbols is required unless --multi-currency is used", file=sys.stderr)
        sys.exit(2)

    if args.multi_currency:
        from src.multi_currency_backtester import MultiCurrencyBacktester

        um = UniverseManager(yaml_path=str(Path(__file__).parent.parent / "config" / "universe.yaml"))
        currency_map = um.get_currency_map()

        # 심볼 결정: --symbols 지정 시 해당 심볼만, 아니면 전체 유니버스
        if args.symbols:
            symbols = args.symbols
        else:
            symbols = um.get_enabled_symbols()

        data = fetch_data(symbols, args.period, args.verbose)

        full_mapping = um.get_group_mapping()
        usd_symbols = {s for s in data if currency_map.get(s, "USD") == "USD"}
        krw_symbols = {s for s in data if currency_map.get(s) == "KRW"}

        usd_groups = {s: full_mapping[s] for s in usd_symbols if s in full_mapping} or None
        krw_groups = {s: full_mapping[s] for s in krw_symbols if s in full_mapping} or None

        usd_config = (
            BacktestConfig(
                initial_capital=args.usd_capital,
                risk_percent=args.risk,
                system=args.system,
                use_filter=not args.no_filter,
                commission_pct=args.commission,
                use_trend_quality_filter=args.trend_filter,
                er_threshold=args.er_threshold,
                regime_proxy_symbol=args.regime_proxy,
            )
            if usd_symbols
            else None
        )

        krw_config = (
            BacktestConfig(
                initial_capital=args.krw_capital,
                risk_percent=args.risk,
                system=args.system,
                use_filter=not args.no_filter,
                use_trend_quality_filter=args.trend_filter,
                er_threshold=args.er_threshold,
                regime_proxy_symbol=args.regime_proxy,
            )
            if krw_symbols
            else None
        )

        mcbt = MultiCurrencyBacktester(
            usd_config=usd_config,
            krw_config=krw_config,
            usd_symbol_groups=usd_groups if not args.no_risk_limits else None,
            krw_symbol_groups=krw_groups if not args.no_risk_limits else None,
            short_restricted_symbols=um.get_short_restricted_symbols(),
        )
        mc_result = mcbt.run(data, currency_map)
        print_multi_currency_results(mc_result)

        if args.plot or args.csv:
            logger.warning("--plot, --csv는 --multi-currency 모드에서 아직 지원되지 않습니다")
    else:
        # 기존 단일 통화 로직 (변경 없음)
        data = fetch_data(args.symbols, args.period, args.verbose)
        result = run_backtest(data, args)
        print_results(result)

        if args.plot:
            plot_equity_curve(result, args.symbols)

        if args.csv:
            export_trades_csv(result, args.csv)

        if result.total_trades == 0:
            logger.warning("거래가 발생하지 않았습니다.")
            sys.exit(2)

    logger.info("백테스트 완료")


if __name__ == "__main__":
    main()
