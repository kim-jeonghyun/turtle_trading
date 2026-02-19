#!/usr/bin/env python3
"""
리스크 한도 모니터링 - 포트폴리오 제한 근접 경고
- 오픈 포지션 로드
- 현재 리스크 지표 계산
- 한도에 근접하면 (>80%) 경고
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

try:
    import yaml
except ImportError:
    yaml = None
    logging.getLogger(__name__).warning("pyyaml 미설치. YAML 설정 파일을 사용할 수 없습니다.")

try:
    from tabulate import tabulate
except ImportError:

    def tabulate(data, headers=None, tablefmt=None):
        lines = []
        if headers:
            lines.append(" | ".join(str(h) for h in headers))
        for row in data:
            lines.append(" | ".join(str(c) for c in row))
        return "\n".join(lines)


try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv():
        pass


from src.position_tracker import Position, PositionTracker
from src.risk_manager import PortfolioRiskManager, RiskLimits
from src.types import AssetGroup, Direction

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_config():
    """환경 변수에서 설정 로드"""
    load_dotenv()


def setup_risk_manager() -> PortfolioRiskManager:
    """리스크 매니저 설정"""
    config_path = Path(__file__).parent.parent / "config" / "correlation_groups.yaml"
    symbol_groups = {}

    if not config_path.exists() or yaml is None:
        logger.warning(f"상관그룹 설정 파일 없음 또는 yaml 미설치: {config_path}. 기본 그룹으로 운영합니다.")
        return PortfolioRiskManager(symbol_groups=symbol_groups)

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        if not config or "groups" not in config:
            logger.warning("상관그룹 설정이 비어있습니다.")
            return PortfolioRiskManager(symbol_groups=symbol_groups)

        group_mapping = {
            "kr_equity": AssetGroup.KR_EQUITY,
            "us_equity": AssetGroup.US_EQUITY,
            "us_etf": AssetGroup.US_EQUITY,
            "crypto": AssetGroup.CRYPTO,
            "commodity": AssetGroup.COMMODITY,
            "bond": AssetGroup.BOND,
        }

        for group_name, symbols in config.get("groups", {}).items():
            asset_group = group_mapping.get(group_name, AssetGroup.US_EQUITY)
            for symbol in symbols:
                symbol_groups[symbol] = asset_group

        logger.info(f"상관그룹 설정 로드: {len(symbol_groups)}개 심볼")

    except yaml.YAMLError as e:
        logger.error(f"상관그룹 YAML 파싱 오류: {e}. 기본 그룹으로 운영합니다.")

    return PortfolioRiskManager(symbol_groups=symbol_groups)


def build_risk_state(positions: List[Position], risk_manager: PortfolioRiskManager) -> Dict:
    """
    현재 포지션에서 리스크 상태 구성

    Returns:
        {
            "units_by_symbol": {...},
            "units_by_group": {...},
            "long_units": int,
            "short_units": int,
            "total_n_exposure": float
        }
    """
    for position in positions:
        direction = Direction.LONG if position.direction == "LONG" else Direction.SHORT
        risk_manager.add_position(position.symbol, position.units, position.entry_n, direction)

    return {
        "units_by_symbol": dict(risk_manager.state.units_by_symbol),
        "units_by_group": {group.value: units for group, units in risk_manager.state.units_by_group.items()},
        "long_units": risk_manager.state.long_units,
        "short_units": risk_manager.state.short_units,
        "total_n_exposure": risk_manager.state.total_n_exposure,
    }


def calculate_risk_metrics(risk_state: Dict, limits: RiskLimits) -> List[Dict]:
    """
    리스크 지표 계산 및 포매팅

    Returns:
        [
            {
                "metric": "string",
                "current": "int/float",
                "limit": "int/float",
                "usage_pct": float (0-100),
                "status": "OK" / "WARNING" / "CRITICAL",
                "bar": visual bar
            }
        ]
    """
    metrics = []

    # 1. 장기 유닛
    long_usage = risk_state["long_units"] / limits.max_units_direction * 100
    metrics.append(
        {
            "metric": "Long Units",
            "current": risk_state["long_units"],
            "limit": limits.max_units_direction,
            "usage_pct": long_usage,
            "status": "CRITICAL" if long_usage >= 100 else ("WARNING" if long_usage >= 80 else "OK"),
        }
    )

    # 2. 단기 유닛
    short_usage = risk_state["short_units"] / limits.max_units_direction * 100
    metrics.append(
        {
            "metric": "Short Units",
            "current": risk_state["short_units"],
            "limit": limits.max_units_direction,
            "usage_pct": short_usage,
            "status": "CRITICAL" if short_usage >= 100 else ("WARNING" if short_usage >= 80 else "OK"),
        }
    )

    # 3. 전체 N 노출
    n_usage = risk_state["total_n_exposure"] / limits.max_total_n_exposure * 100
    metrics.append(
        {
            "metric": "Total N Exposure",
            "current": f"{risk_state['total_n_exposure']:.2f}",
            "limit": f"{limits.max_total_n_exposure:.2f}",
            "usage_pct": n_usage,
            "status": "CRITICAL" if n_usage >= 100 else ("WARNING" if n_usage >= 80 else "OK"),
        }
    )

    # 4. 그룹별 유닛 (각 그룹이 6 Units 제한)
    for group_name, units in risk_state["units_by_group"].items():
        group_usage = units / limits.max_units_correlated * 100
        metrics.append(
            {
                "metric": f"Group: {group_name}",
                "current": units,
                "limit": limits.max_units_correlated,
                "usage_pct": group_usage,
                "status": "CRITICAL" if group_usage >= 100 else ("WARNING" if group_usage >= 80 else "OK"),
            }
        )

    # 5. 단일 종목별 유닛 (각 종목이 4 Units 제한)
    for symbol, units in risk_state["units_by_symbol"].items():
        if units > 0:
            symbol_usage = units / limits.max_units_per_market * 100
            metrics.append(
                {
                    "metric": f"Symbol: {symbol}",
                    "current": units,
                    "limit": limits.max_units_per_market,
                    "usage_pct": symbol_usage,
                    "status": "CRITICAL" if symbol_usage >= 100 else ("WARNING" if symbol_usage >= 80 else "OK"),
                }
            )

    return metrics


def format_progress_bar(usage_pct: float, width: int = 20) -> str:
    """사용률을 시각적 바로 표현"""
    filled = int(usage_pct / 100 * width)
    filled = min(filled, width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}] {usage_pct:.1f}%"


def print_risk_report(metrics: List[Dict], warn_threshold: float = 0.8):
    """리스크 리포트 출력"""
    logger.info("=" * 80)
    logger.info("RISK LIMIT MONITOR")
    logger.info("=" * 80)

    # 테이블 데이터 구성
    table_data = []
    warnings = []
    criticals = []

    for metric in metrics:
        usage_pct = metric["usage_pct"]
        status = metric["status"]

        row = [metric["metric"], str(metric["current"]), str(metric["limit"]), format_progress_bar(usage_pct), status]
        table_data.append(row)

        # 경고/심각 상황 수집
        if status == "WARNING":
            warnings.append(f"{metric['metric']}: {usage_pct:.1f}%")
        elif status == "CRITICAL":
            criticals.append(f"{metric['metric']}: {usage_pct:.1f}%")

    # 테이블 출력
    headers = ["Metric", "Current", "Limit", "Usage", "Status"]
    print("\n" + tabulate(table_data, headers=headers, tablefmt="grid"))

    # 요약
    print("\n" + "=" * 80)
    if criticals:
        print("🔴 CRITICAL LIMITS EXCEEDED:")
        for msg in criticals:
            print(f"   • {msg}")
        print()

    if warnings:
        print("🟡 WARNING - APPROACHING LIMITS:")
        for msg in warnings:
            print(f"   • {msg}")
        print()

    if not criticals and not warnings:
        print("🟢 All risk limits within safe range")
        print()

    logger.info("=" * 80)


def export_to_json(metrics: List[Dict], filepath: Path):
    """리스크 지표를 JSON으로 내보내기"""
    export_data = {
        "timestamp": datetime.now().isoformat(),
        "metrics": metrics,
    }

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(export_data, f, indent=2, default=str)

    logger.info(f"JSON 내보내기: {filepath}")


def main(args):
    """메인 함수"""
    logger.info("=== 리스크 한도 모니터링 시작 ===")

    load_config()

    # 포지션 및 리스크 매니저 로드
    try:
        tracker = PositionTracker()
        risk_manager = setup_risk_manager()
        open_positions = tracker.get_open_positions()

        logger.info(f"오픈 포지션: {len(open_positions)}개")

    except Exception as e:
        logger.error(f"포지션/리스크 매니저 로드 오류: {e}")
        return

    if not open_positions:
        logger.info("오픈 포지션 없음 - 모든 한도 사용 중단")
        metrics = calculate_risk_metrics(
            {
                "units_by_symbol": {},
                "units_by_group": {},
                "long_units": 0,
                "short_units": 0,
                "total_n_exposure": 0.0,
            },
            risk_manager.limits,
        )
    else:
        # 리스크 상태 구성
        risk_state = build_risk_state(open_positions, risk_manager)

        # 리스크 지표 계산
        metrics = calculate_risk_metrics(risk_state, risk_manager.limits)

    # 리포트 출력
    print_risk_report(metrics, args.warn_threshold)

    # JSON 내보내기
    if args.json:
        json_path = Path(args.json)
        export_to_json(metrics, json_path)

    logger.info("=== 모니터링 완료 ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="리스크 한도 모니터링")
    parser.add_argument("--warn-threshold", type=float, default=0.8, help="경고 임계값 (기본값: 0.8 = 80%%)")
    parser.add_argument("--json", type=str, help="JSON 내보내기 경로")

    args = parser.parse_args()
    main(args)
