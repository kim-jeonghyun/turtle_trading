#!/usr/bin/env python3
"""
자동매매 실행 스크립트
- check_positions.py의 시그널을 기반으로 자동 주문 실행
- dry-run 모드가 기본 (--live 플래그로 실거래)

사용법:
    # Dry-run (기본)
    python scripts/auto_trade.py --symbols SPY QQQ

    # 실거래 (주의!)
    python scripts/auto_trade.py --live --symbols SPY --system 2

    # 전체 유니버스, 최대 주문 금액 제한
    python scripts/auto_trade.py --max-amount 1000000 --verbose
"""

import argparse
import asyncio
import fcntl
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from src.auto_trader import AutoTrader
from src.data_fetcher import DataFetcher
from src.indicators import add_turtle_indicators
from src.kis_api import KISAPIClient, KISConfig, OrderSide, OrderType
from src.types import OrderStatus
from src.universe_manager import UniverseManager

logger = logging.getLogger(__name__)

LOCK_FILE = Path(__file__).parent.parent / "data" / ".auto_trade.lock"


def acquire_lock():
    """중복 실행 방지를 위한 파일 잠금"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
        return fd
    except IOError:
        fd.close()
        logger.warning("이미 다른 auto_trade 인스턴스가 실행 중입니다. 종료합니다.")
        return None


def release_lock(fd):
    """파일 잠금 해제"""
    if fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
        except Exception:
            pass


# 기본 주문 한도 (KRW)
DEFAULT_MAX_AMOUNT = 5_000_000

# 테스트용 기본 유니버스 (fallback)
DEFAULT_SYMBOLS = [
    "SPY",
    "QQQ",
    "AAPL",
    "NVDA",
    "TSLA",
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
]


def get_default_symbols() -> list:
    """config/universe.yaml에서 기본 심볼 로드"""
    yaml_path = Path(__file__).parent.parent / "config" / "universe.yaml"
    if yaml_path.exists():
        universe = UniverseManager(yaml_path=str(yaml_path))
        return universe.get_enabled_symbols()
    return DEFAULT_SYMBOLS  # fallback to hardcoded


def parse_args() -> argparse.Namespace:
    """CLI 인수 파싱"""
    parser = argparse.ArgumentParser(
        description="터틀 트레이딩 자동매매 실행 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # Dry-run (기본, 안전)
  python scripts/auto_trade.py

  # 특정 종목, System 1만
  python scripts/auto_trade.py --symbols SPY QQQ --system 1

  # 실거래 모드 (주의: 실제 주문이 체결됩니다!)
  python scripts/auto_trade.py --live --symbols SPY
        """,
    )

    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="실거래 모드 활성화 (기본: dry-run). 주의: 실제 주문이 체결됩니다!",
    )

    parser.add_argument(
        "--max-amount",
        type=float,
        default=DEFAULT_MAX_AMOUNT,
        metavar="FLOAT",
        help=f"단일 주문 최대 금액 KRW (기본: {DEFAULT_MAX_AMOUNT:,.0f})",
    )

    parser.add_argument(
        "--symbols", nargs="+", default=None, metavar="SYMBOL", help="대상 종목 코드 리스트 (기본: 내장 유니버스)"
    )

    parser.add_argument(
        "--system",
        type=int,
        choices=[1, 2],
        default=None,
        metavar="{1,2}",
        help="트레이딩 시스템 선택 (1=20일, 2=55일, 기본: 둘 다)",
    )

    parser.add_argument("--verbose", action="store_true", default=False, help="상세 로그 출력")

    return parser.parse_args()


def setup_logging(verbose: bool):
    """로깅 설정"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def load_kis_config() -> KISConfig:
    """환경 변수에서 KIS API 설정 로드"""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        logger.warning("python-dotenv 미설치. 환경 변수를 직접 사용합니다.")

    app_key = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    account_no = os.getenv("KIS_ACCOUNT_NO", "")
    account_suffix = os.getenv("KIS_ACCOUNT_SUFFIX", "01")
    is_real = os.getenv("KIS_IS_REAL", "false").lower() == "true"

    if not app_key or not app_secret or not account_no:
        logger.warning(
            "KIS API 자격증명이 설정되지 않았습니다. "
            "환경 변수 KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO를 설정하세요."
        )

    return KISConfig(
        app_key=app_key, app_secret=app_secret, account_no=account_no, account_suffix=account_suffix, is_real=is_real
    )


def check_entry_signal(df, symbol: str, system: int) -> dict | None:
    """
    진입 시그널 확인

    Args:
        df: 터틀 지표가 추가된 DataFrame
        symbol: 종목 코드
        system: 시스템 번호 (1 또는 2)

    Returns:
        시그널 딕셔너리 또는 None
    """
    if len(df) < 2:
        return None

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    # System 1: 20일 돌파, System 2: 55일 돌파
    high_col = "dc_high_20" if system == 1 else "dc_high_55"

    if high_col not in df.columns or "N" not in df.columns:
        logger.warning(f"필수 컬럼 없음: {high_col} 또는 N")
        return None

    # 롱 진입 시그널: 오늘 고가가 전일 채널 상단 돌파
    if today["high"] > yesterday[high_col]:
        entry_price = yesterday[high_col]
        n_value = today["N"]
        stop_loss = entry_price - (2 * n_value)

        return {
            "symbol": symbol,
            "system": system,
            "direction": "LONG",
            "entry_price": entry_price,
            "current_price": today["close"],
            "n_value": n_value,
            "stop_loss": stop_loss,
            "date": today["date"].strftime("%Y-%m-%d") if hasattr(today["date"], "strftime") else str(today["date"]),
            "message": f"System {system} 롱 진입: {entry_price:.2f} 돌파",
        }

    return None


def calculate_order_quantity(signal: dict, account_balance: float, risk_percent: float = 0.01) -> int:
    """
    1% 리스크 기반 주문 수량 계산 (Curtis Faith 원서 기준)

    Args:
        signal: 시그널 딕셔너리 (entry_price, n_value 포함)
        account_balance: 계좌 잔고
        risk_percent: 리스크 비율 (기본 1%)

    Returns:
        주문 수량 (정수)
    """
    entry_price = signal["entry_price"]
    n_value = signal["n_value"]

    if n_value <= 0 or entry_price <= 0:
        return 0

    # 달러 리스크 = 계좌 잔고 * 리스크 비율
    dollar_risk = account_balance * risk_percent

    # 수량 = 달러 리스크 / (2 * N) / 가격
    # (2N 스톱로스 기준, 터틀 트레이딩 공식: Unit = (Account * Risk%) / (2 * N * Price))
    shares = (dollar_risk / (2 * n_value)) / entry_price
    shares = max(1, int(shares))

    return shares


async def run_auto_trade(args: argparse.Namespace):
    """
    자동매매 메인 실행 함수

    Args:
        args: CLI 인수
    """
    # Live 모드 보안 검사
    from src.security import enforce_dry_run

    if args.live:
        if not enforce_dry_run(is_live=True):
            logger.error("실거래가 차단됨. TURTLE_ALLOW_LIVE=true 환경변수를 설정하세요.")
            sys.exit(1)

    # Live 모드 경고
    if args.live:
        logger.warning("=" * 70)
        logger.warning("[WARNING] 실거래 모드 (--live) 활성화!")
        logger.warning("실제 주문이 KIS API를 통해 체결됩니다!")
        logger.warning("계좌 설정 및 주문 금액을 반드시 확인하세요.")
        logger.warning(f"최대 주문 금액: {args.max_amount:,.0f} KRW")
        logger.warning("=" * 70)

    # 설정 로드
    kis_config = load_kis_config()
    kis_client = KISAPIClient(kis_config)

    # AutoTrader 초기화 (--live 미사용 시 dry_run=True)
    trader = AutoTrader(kis_client=kis_client, dry_run=not args.live, max_order_amount=args.max_amount)

    # 데이터 페처
    data_fetcher = DataFetcher()

    # 대상 종목 결정
    symbols = args.symbols if args.symbols else get_default_symbols()

    # 대상 시스템 결정
    systems = [args.system] if args.system else [1, 2]

    logger.info(f"자동매매 시작: {len(symbols)}개 종목, System {systems}")
    logger.info(f"모드: {'LIVE' if args.live else 'DRY-RUN'}")

    # 계좌 요약 조회
    account = await trader.get_account_summary()
    account_balance = account.get("total_equity")
    if account_balance is None or account_balance <= 0:
        if not trader.dry_run:
            logger.error("계좌 잔고 조회 실패 - 실거래 중단")
            sys.exit(1)
        account_balance = 10_000_000
        logger.warning(f"Dry-run 계좌 잔고 (가정): {account_balance:,.0f} KRW")
    elif account.get("dry_run"):
        logger.info(f"Dry-run 계좌 잔고 (가정): {account_balance:,.0f} KRW")
    else:
        logger.info(f"계좌 잔고: {account_balance:,.0f} KRW")

    # 주문 결과 집계
    placed_orders = []
    skipped_signals = []

    # 각 종목별 시그널 체크 및 주문 실행
    for symbol in symbols:
        try:
            logger.info(f"종목 처리 중: {symbol}")

            # 데이터 페칭 (6개월)
            df = data_fetcher.fetch(symbol, period="6mo")
            if df is None or df.empty:
                logger.warning(f"데이터 없음: {symbol}")
                continue

            # 터틀 지표 계산
            df = add_turtle_indicators(df)
            if len(df) < 2:
                logger.warning(f"데이터 부족: {symbol}")
                continue

            # 각 시스템별 시그널 체크
            for system in systems:
                signal = check_entry_signal(df, symbol, system)

                if signal is None:
                    logger.debug(f"시그널 없음: {symbol} System {system}")
                    continue

                logger.info(f"시그널 감지: {signal['message']}")

                # 주문 수량 계산
                quantity = calculate_order_quantity(signal, account_balance)
                if quantity <= 0:
                    logger.warning(f"주문 수량 0: {symbol} - 스킵")
                    skipped_signals.append({**signal, "skip_reason": "수량 0"})
                    continue

                # 주문 금액 사전 체크 (AutoTrader 내부에서도 체크하지만 로그 목적)
                order_amount = quantity * signal["entry_price"]
                if order_amount > args.max_amount:
                    # 금액 초과 시 수량 축소
                    quantity = int(args.max_amount / signal["entry_price"])
                    if quantity <= 0:
                        logger.warning(f"금액 제한으로 주문 불가: {symbol}")
                        skipped_signals.append({**signal, "skip_reason": "금액 한도 초과"})
                        continue
                    logger.info(f"금액 제한으로 수량 축소: {quantity}주")

                # 주문 실행
                order_record = await trader.place_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=quantity,
                    price=signal["entry_price"],
                    order_type=OrderType.LIMIT,
                    reason=signal["message"],
                )

                placed_orders.append(order_record)
                status_str = (
                    "완료" if order_record.status in (OrderStatus.FILLED.value, OrderStatus.DRY_RUN.value) else "실패"
                )
                logger.info(
                    f"주문 {status_str}: {order_record.order_id} | {symbol} {quantity}주 @ {signal['entry_price']:,.2f}"
                )

        except Exception as e:
            logger.error(f"{symbol} 처리 오류: {e}")

    # 일별 통계
    stats = trader.get_daily_stats()

    # 결과 요약 출력
    print("\n" + "=" * 60)
    print(f"자동매매 실행 완료 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'LIVE' if args.live else 'DRY-RUN'}")
    print("=" * 60)
    print(f"처리 종목: {len(symbols)}개")
    print(f"시그널 감지: {len(placed_orders) + len(skipped_signals)}개")
    print(f"주문 실행: {len(placed_orders)}개")
    print(f"스킵: {len(skipped_signals)}개")
    print("-" * 60)
    print(f"오늘 통계: {stats}")
    print("=" * 60)

    # 주문 상세 내역 출력
    if placed_orders:
        print("\n주문 내역:")
        for order in placed_orders:
            status_label = {
                OrderStatus.FILLED.value: "체결",
                OrderStatus.DRY_RUN.value: "시뮬레이션",
                OrderStatus.FAILED.value: "실패",
                OrderStatus.PENDING.value: "대기",
                OrderStatus.CANCELLED.value: "취소",
            }.get(order.status, order.status)

            print(
                f"  [{status_label}] {order.symbol} "
                f"{order.side.upper()} {order.quantity}주 "
                f"@ {order.price:,.2f} | {order.reason or ''}"
            )

    return placed_orders


def main():
    args = parse_args()
    setup_logging(args.verbose)

    lock_fd = acquire_lock()
    if lock_fd is None:
        sys.exit(1)

    try:
        asyncio.run(run_auto_trade(args))
        sys.exit(0)
    except KeyboardInterrupt:
        logger.info("사용자에 의해 중단됨")
        sys.exit(1)
    except Exception as e:
        logger.error(f"자동매매 실행 실패: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)
    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    main()
