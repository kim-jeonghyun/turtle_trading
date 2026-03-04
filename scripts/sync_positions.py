#!/usr/bin/env python3
"""
포지션 동기화 검증 스크립트 -- cron 실행 (장 마감 30분 후 권장)

KIS 계좌 잔고와 로컬 positions.json을 비교하여
불일치 발견 시 알림을 전송한다.

- Fail-Open: API 장애 시 알림만, 시스템 중단 없음
- 동기화 불일치는 거래를 차단하지 않음 (정보성 보고 전용)
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.kis_api import KISAPIClient
from src.notifier import NotificationLevel, NotificationMessage
from src.position_sync import PositionSyncVerifier
from src.position_tracker import PositionTracker
from src.script_helpers import create_kis_client, load_config, setup_notifier

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """로깅 설정."""
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.addHandler(console_handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


async def main(args: argparse.Namespace) -> None:
    """포지션 동기화 검증 메인."""
    config = load_config()
    notifier = setup_notifier(config)
    tracker = PositionTracker()

    kis_config = create_kis_client(config)
    if kis_config is None:
        logger.warning("KIS API 미설정 — 동기화 검증 스킵")
        return

    kis_ctx = KISAPIClient(kis_config)

    async with kis_ctx as kis_client:
        verifier = PositionSyncVerifier(kis_client=kis_client, tracker=tracker)

        try:
            discrepancies = await verifier.verify()
        except Exception as e:
            # Fail-Open: API 장애 시 알림만, 시스템 중단 없음
            logger.error(f"포지션 동기화 검증 실패: {e}")
            if not args.dry_run:
                await notifier.send_message(
                    NotificationMessage(
                        title="동기화 검증 실패",
                        body=str(e),
                        level=NotificationLevel.ERROR,
                    )
                )
            return

        if discrepancies:
            report = verifier.format_report(discrepancies)
            has_critical = any(d.is_critical for d in discrepancies)
            level = (
                NotificationLevel.ERROR
                if has_critical
                else NotificationLevel.WARNING
            )
            logger.warning(f"포지션 불일치 {len(discrepancies)}건 발견")
            logger.warning(report)

            if not args.dry_run:
                await notifier.send_message(
                    NotificationMessage(
                        title=f"포지션 불일치 {len(discrepancies)}건",
                        body=report,
                        level=level,
                    )
                )
            else:
                logger.info("[DRY-RUN] 알림 전송 스킵")
        else:
            logger.info("포지션 동기화 정상")


def cli_main():
    """CLI 엔트리포인트."""
    parser = argparse.ArgumentParser(
        description="KIS 잔고 vs 로컬 포지션 동기화 검증"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="검증만 수행하고 알림은 전송하지 않음",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="상세 로깅 활성화"
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)
    logger.info("=== 포지션 동기화 검증 시작 ===")
    asyncio.run(main(args))


if __name__ == "__main__":
    cli_main()
