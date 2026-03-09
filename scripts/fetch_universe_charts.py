#!/usr/bin/env python
"""유니버스 전 종목 차트를 mplfinance로 로컬 렌더링한다.

사용법:
    python scripts/fetch_universe_charts.py            # 전체 유니버스
    python scripts/fetch_universe_charts.py --limit 5  # 5종목만
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 경로 추가 (scripts/ 디렉토리 기준)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.local_chart_renderer import BatchChartRenderer  # noqa: E402
from src.notifier import NotificationLevel, NotificationMessage  # noqa: E402
from src.script_helpers import load_config, setup_notifier  # noqa: E402
from src.universe_manager import UniverseManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ChartBatch")


def _send_notification(title: str, body: str, level: NotificationLevel):
    """설정된 채널(Telegram/Discord/Email)로 알림을 발송한다."""
    try:
        config = load_config()
        notifier = setup_notifier(config)
        if not notifier.channels:
            logger.info("알림 채널 미설정, 알림 스킵")
            return
        msg = NotificationMessage(title=title, body=body, level=level)
        asyncio.run(notifier.send_message(msg))
    except Exception as e:
        logger.warning(f"알림 발송 실패: {e}")


def main():
    parser = argparse.ArgumentParser(description="유니버스 전 종목 mplfinance 차트 생성")
    parser.add_argument("--limit", type=int, help="렌더링할 최대 종목 수")
    args = parser.parse_args()

    # 1. 출력 디렉토리 준비
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = PROJECT_ROOT / "data" / "charts" / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"출력 디렉토리: {output_dir}")

    # 2. Universe 로드
    universe_path = PROJECT_ROOT / "config" / "universe.yaml"
    if not universe_path.exists():
        logger.error(f"설정 파일이 존재하지 않습니다: {universe_path}")
        sys.exit(1)

    try:
        universe_manager = UniverseManager(yaml_path=str(universe_path))
        total = len(universe_manager.get_enabled_symbols())
        logger.info(f"총 {total}개 활성 심볼 감지")
    except Exception as e:
        logger.error(f"Universe 로드 실패: {e}")
        _send_notification(
            "주간 차트 생성 실패",
            "Universe 설정 파일 로드 중 오류가 발생했습니다. 서버 로그를 확인하세요.",
            NotificationLevel.ERROR,
        )
        sys.exit(1)

    # 3. 배치 렌더링
    renderer = BatchChartRenderer(universe_manager)
    logger.info(f"차트 렌더링 시작 (limit={args.limit})")
    results = renderer.render_all(output_dir=str(output_dir), limit=args.limit)

    # 4. 결과 리포팅
    successes = [s for s, ok in results.items() if ok]
    failures = [s for s, ok in results.items() if not ok]

    logger.info("=" * 40)
    logger.info(f"배치 완료: 성공 {len(successes)} / 실패 {len(failures)}")

    if len(failures) == len(results):
        # 전체 실패 → ERROR + 비정상 종료
        logger.error(f"전체 종목 실패: {', '.join(failures)}")
        _send_notification(
            "주간 차트 생성 전체 실패",
            f"전체 {len(failures)}개 종목 차트 생성 실패",
            NotificationLevel.ERROR,
        )
        logger.info("=" * 40)
        sys.exit(1)
    elif failures:
        # 부분 실패 → WARNING
        logger.warning(f"실패 종목: {', '.join(failures)}")
        _send_notification(
            "주간 차트 생성 부분 실패",
            f"성공 {len(successes)} / 실패 {len(failures)}\n실패 종목: {', '.join(failures)}",
            NotificationLevel.WARNING,
        )
    else:
        # 전체 성공 → INFO
        _send_notification(
            "주간 차트 생성 완료",
            f"전체 {len(successes)}개 종목 차트 생성 성공",
            NotificationLevel.INFO,
        )

    logger.info("=" * 40)


if __name__ == "__main__":
    main()
