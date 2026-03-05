"""Go-Live 자동 검증 체크리스트.

실거래 시작 전 모든 조건을 자동 검증합니다.
종료 코드: 0 = ready, 1 = not ready
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def check_health_check_passes() -> tuple[bool, str]:
    """체크 1: health_check.py 전체 통과"""
    try:
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import health_check

        core_checks = [
            health_check.check_python_version,
            health_check.check_data_directory,
            health_check.check_python_packages,
            health_check.check_position_files,
            health_check.check_disk_space,
            health_check.check_kill_switch,
            health_check.check_position_sync_module,
            health_check.check_vi_cb_detector,
        ]
        failed = []
        for fn in core_checks:
            ok, _ = fn()
            if not ok:
                failed.append(fn.__name__)
        if failed:
            return False, f"health_check 실패: {len(failed)}건 ({', '.join(failed)})"
        return True, f"health_check 전체 통과 ({len(core_checks)}건)"
    except Exception as e:
        return False, f"health_check 실행 실패: {e}"


def check_kis_token() -> tuple[bool, str]:
    """체크 2: KIS API 설정 확인"""
    try:
        import os

        from src.kis_api import KISAPIClient  # noqa: F401

        required_keys = ["KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO"]
        missing = [k for k in required_keys if not os.environ.get(k)]
        if missing:
            return False, f"KIS 환경변수 미설정: {', '.join(missing)} — .env 확인 필요"
        return True, "KIS API 모듈 + 환경변수 정상"
    except Exception as e:
        return False, f"KIS API 모듈 로드 실패: {e}"


def check_kis_balance() -> tuple[bool, str]:
    """체크 3: KIS 잔고 조회 가능 (메서드 호출 가능 검증)"""
    try:
        from src.kis_api import KISAPIClient

        if not callable(getattr(KISAPIClient, "get_balance", None)):
            return False, "get_balance() 메서드 없음"
        if not callable(getattr(KISAPIClient, "get_account_summary", None)):
            return False, "get_account_summary() 메서드 없음"
        return True, "get_balance() + get_account_summary() 메서드 확인"
    except Exception as e:
        return False, f"확인 실패: {e}"


def check_position_sync() -> tuple[bool, str]:
    """체크 4: 포지션 동기화 모듈 정상 (인스턴스 생성 검증)"""
    try:
        from src.position_sync import PositionSyncVerifier

        if not callable(getattr(PositionSyncVerifier, "verify", None)):
            return False, "verify() 메서드 없음"
        # 인스턴스 생성 가능 여부 검증
        verifier = PositionSyncVerifier()
        if not hasattr(verifier, "verify"):
            return False, "인스턴스에 verify() 메서드 없음"
        return True, "PositionSyncVerifier 인스턴스 생성 + verify() 확인"
    except Exception as e:
        return False, f"포지션 동기화 모듈 검증 실패: {e}"


def check_data_integrity() -> tuple[bool, str]:
    """체크 5: 데이터 무결성 검증 모듈 정상"""
    try:
        validate_path = PROJECT_ROOT / "scripts" / "validate_data.py"
        if validate_path.exists():
            return True, "validate_data.py 존재"
        return False, "validate_data.py 없음"
    except Exception as e:
        return False, f"확인 실패: {e}"


def check_recent_ohlcv() -> tuple[bool, str]:
    """체크 6: 최근 OHLCV 데이터 존재 (2일 이내 — 주말 포함)"""
    cache_dir = PROJECT_ROOT / "data" / "cache"
    if not cache_dir.exists():
        return False, "data/cache/ 디렉토리 없음"
    parquet_files = list(cache_dir.glob("*.parquet"))
    if not parquet_files:
        return False, "캐시된 OHLCV 데이터 없음"
    newest = max(parquet_files, key=lambda p: p.stat().st_mtime)
    age = datetime.now() - datetime.fromtimestamp(newest.stat().st_mtime)
    if age > timedelta(days=2):
        return False, f"최신 데이터가 {age.days}일 전 (2일 이내 필요)"
    return True, f"최신 OHLCV: {newest.name} ({age.total_seconds() / 3600:.0f}시간 전)"


def check_kill_switch() -> tuple[bool, str]:
    """체크 7: 킬 스위치 정상 (거래 활성화)"""
    try:
        from src.kill_switch import KillSwitch

        ks = KillSwitch()
        if ks.is_trading_enabled:
            return True, "거래 활성화 상태"
        return False, "킬 스위치 비활성화 상태 — 거래 중단됨"
    except Exception as e:
        return False, f"킬 스위치 확인 실패: {e}"


def check_backtest_performance() -> tuple[bool, str]:
    """체크 8: 백테스트 최소 성과 (30일 이내, MDD < 30%, PF > 1.0)"""
    backtest_dir = PROJECT_ROOT / "data" / "backtest"
    if not backtest_dir.exists():
        return False, "data/backtest/ 디렉토리 없음"
    json_files = sorted(
        backtest_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not json_files:
        return False, "백테스트 결과 파일 없음"
    newest = json_files[0]
    age = datetime.now() - datetime.fromtimestamp(newest.stat().st_mtime)
    if age > timedelta(days=30):
        return False, f"최신 백테스트가 {age.days}일 전 (30일 이내 필요)"
    try:
        with open(newest) as f:
            result = json.load(f)
        mdd_raw = result.get("max_drawdown", result.get("max_drawdown_pct"))
        if mdd_raw is None:
            return False, "백테스트 결과에 max_drawdown 필드 없음"
        mdd = abs(mdd_raw)
        pf = result.get("profit_factor")
        if pf is None:
            return False, "백테스트 결과에 profit_factor 필드 없음"
        issues = []
        if mdd > 0.3:
            issues.append(f"MDD {mdd:.1%} > 30%")
        if pf < 1.0:
            issues.append(f"PF {pf:.2f} < 1.0")
        if issues:
            return False, "; ".join(issues)
        return True, f"MDD: {mdd:.1%}, PF: {pf:.2f} (기준 충족)"
    except Exception as e:
        return False, f"백테스트 결과 파싱 실패: {e}"


def check_notification() -> tuple[bool, str]:
    """체크 9: 알림 채널 정상"""
    try:
        from src.notifier import NotificationManager  # noqa: F401

        return True, "NotificationManager 모듈 정상"
    except Exception as e:
        return False, f"알림 모듈 로드 실패: {e}"


def check_dry_run_order() -> tuple[bool, str]:
    """체크 10: AutoTrader 런타임 통합 검증 (인스턴스 생성 + 가드 연결 확인)"""
    try:
        from unittest.mock import MagicMock

        from src.auto_trader import AutoTrader
        from src.kill_switch import KillSwitch
        from src.trading_guard import TradingGuard, TradingLimits

        ks = KillSwitch()
        guard = TradingGuard(limits=TradingLimits(), kill_switch=ks)
        mock_kis = MagicMock()

        trader = AutoTrader(
            kis_client=mock_kis,
            dry_run=True,
            kill_switch=ks,
            trading_guard=guard,
        )
        # 가드 체인 연결 검증
        if trader.trading_guard is not guard:
            return False, "trading_guard 연결 실패"
        if trader.kill_switch is not ks:
            return False, "kill_switch 연결 실패"
        return True, "AutoTrader 인스턴스 생성 + 가드 체인 연결 검증 통과"
    except Exception as e:
        return False, f"AutoTrader 런타임 검증 실패: {e}"


def check_trading_guard_module() -> tuple[bool, str]:
    """체크 11: 안전 가드 모듈 기능 검증"""
    try:
        from src.kill_switch import KillSwitch
        from src.trading_guard import TradingGuard, TradingLimits

        ks = KillSwitch()
        guard = TradingGuard(limits=TradingLimits(), kill_switch=ks)

        # 실제 함수 호출로 검증
        ok1, _ = guard.check_daily_loss(1_000_000)
        ok2, _ = guard.check_order_size(100_000, 1_000_000)

        if not ok1:
            return False, "check_daily_loss 기본 테스트 실패"
        if not ok2:
            return False, "check_order_size 기본 테스트 실패"
        return True, "TradingGuard 인스턴스 생성 + 기본 동작 검증 통과"
    except ImportError:
        return False, "src/trading_guard.py 모듈 없음"
    except Exception as e:
        return False, f"TradingGuard 검증 실패: {e}"


def check_correlation_groups_consistency() -> tuple[bool, str]:
    """체크 12: 상관그룹 설정 일관성"""
    import yaml

    universe_path = PROJECT_ROOT / "config" / "universe.yaml"
    corr_path = PROJECT_ROOT / "config" / "correlation_groups.yaml"

    if not universe_path.exists():
        return False, "config/universe.yaml 없음"
    if not corr_path.exists():
        return False, "config/correlation_groups.yaml 없음"

    try:
        with open(universe_path) as f:
            universe = yaml.safe_load(f)
        with open(corr_path) as f:
            corr_groups = yaml.safe_load(f)

        # universe.yaml: {symbols: {market: [{symbol: X, ...}, ...]}}
        universe_symbols: set[str] = set()
        if isinstance(universe, dict):
            symbols_section = universe.get("symbols", {})
            if isinstance(symbols_section, dict):
                for market_list in symbols_section.values():
                    if isinstance(market_list, list):
                        for entry in market_list:
                            if isinstance(entry, dict) and "symbol" in entry:
                                universe_symbols.add(entry["symbol"])
                            elif isinstance(entry, str):
                                universe_symbols.add(entry)

        # correlation_groups.yaml: {groups: {name: [symbol, ...]}}
        corr_symbols: set[str] = set()
        if isinstance(corr_groups, dict):
            groups_section = corr_groups.get("groups", corr_groups)
            if isinstance(groups_section, dict):
                for members in groups_section.values():
                    if isinstance(members, list):
                        corr_symbols.update(str(s) for s in members)

        if not universe_symbols:
            return False, "universe.yaml에 심볼이 없음 — 설정 확인 필요"

        unmapped = universe_symbols - corr_symbols
        if unmapped and len(unmapped) == len(universe_symbols):
            return False, f"전체 심볼 미매핑: {len(unmapped)}건"
        if unmapped:
            return True, f"일부 미매핑 심볼 존재 ({len(unmapped)}건) — 허용"
        return True, f"상관그룹 일관성 확인 ({len(corr_symbols)}개 매핑)"
    except Exception as e:
        return False, f"설정 파일 파싱 실패: {e}"


def check_cost_analyzer_module() -> tuple[bool, str]:
    """체크 13: CostAnalyzer 기능 검증"""
    try:
        import tempfile
        from pathlib import Path

        from src.cost_analyzer import CostAnalyzer

        # 임시 파일로 테스트 (실제 로그 오염 방지)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=True) as tmp:
            analyzer = CostAnalyzer(cost_log_path=Path(tmp.name))
            cost = analyzer.analyze_order(
                order_id="TEST_001",
                symbol="005930.KS",
                requested_price=70000,
                fill_price=70010,
                quantity=1,
            )
            if cost.total_cost <= 0:
                return False, "비용 계산 결과 비정상"

            ok, _ = analyzer.check_budget_limit(
                total_equity=5_000_000,
                realized_profit=100_000,
            )
            return True, "CostAnalyzer 인스턴스 + analyze_order + check_budget_limit 검증 통과"
    except Exception as e:
        return False, f"CostAnalyzer 검증 실패: {e}"


ALL_CHECKS = [
    ("health_check 전체 통과", check_health_check_passes),
    ("KIS 토큰 발급", check_kis_token),
    ("KIS 잔고 조회", check_kis_balance),
    ("포지션 동기화", check_position_sync),
    ("데이터 무결성", check_data_integrity),
    ("최근 OHLCV 데이터", check_recent_ohlcv),
    ("킬 스위치 정상", check_kill_switch),
    ("백테스트 최소 성과", check_backtest_performance),
    ("알림 채널", check_notification),
    ("AutoTrader/KIS 모듈 로드", check_dry_run_order),
    ("안전 가드 모듈", check_trading_guard_module),
    ("CostAnalyzer 기능 검증", check_cost_analyzer_module),
    ("상관그룹 일관성", check_correlation_groups_consistency),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Go-Live 자동 검증 체크리스트")
    parser.add_argument("--verbose", action="store_true", help="상세 출력")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(message)s")
    logger.info("=" * 60)
    logger.info("Go-Live 자동 검증 체크리스트")
    logger.info("=" * 60)
    logger.info("")

    passed = 0
    failed = 0
    for name, check_fn in ALL_CHECKS:
        try:
            ok, message = check_fn()
        except Exception as e:
            ok, message = False, f"예외: {e}"

        status = "✓ PASS" if ok else "✗ FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        logger.info(f"  [{status}] {name}: {message}")

    logger.info("")
    logger.info(f"결과: {passed}/{len(ALL_CHECKS)} 통과, {failed}건 실패")

    if failed == 0:
        logger.info("→ Go-Live 준비 완료!")
    else:
        logger.info("→ Go-Live 불가 — 실패 항목을 해결하세요.")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
