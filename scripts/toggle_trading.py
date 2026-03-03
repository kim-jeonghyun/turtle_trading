#!/usr/bin/env python3
"""킬 스위치 토글 CLI.

사용법:
  python scripts/toggle_trading.py --disable --reason "시장 급변"
  python scripts/toggle_trading.py --enable
  python scripts/toggle_trading.py --status
"""

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.kill_switch import KillSwitch


def main():
    parser = argparse.ArgumentParser(description="킬 스위치 토글 CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", action="store_true", help="트레이딩 재개")
    group.add_argument("--disable", action="store_true", help="트레이딩 중단")
    group.add_argument("--status", action="store_true", help="현재 상태 출력")
    parser.add_argument("--reason", type=str, default="수동 킬 스위치", help="비활성화 사유")

    args = parser.parse_args()
    ks = KillSwitch()

    if args.status:
        if ks.is_trading_enabled:
            print("Trading: ENABLED")
        else:
            print("Trading: DISABLED")
            print(f"Reason:  {ks.reason}")
            if ks.disabled_at:
                print(f"Since:   {ks.disabled_at}")
    elif args.disable:
        try:
            ks.activate(reason=args.reason)
            print(f"Trading: DISABLED (reason: {args.reason})")
        except Exception as e:
            print(f"Error: 킬 스위치 활성화 실패 - {e}", file=sys.stderr)
            sys.exit(1)
    elif args.enable:
        try:
            ks.deactivate()
            print("Trading: ENABLED")
        except Exception as e:
            print(f"Error: 킬 스위치 해제 실패 - {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
