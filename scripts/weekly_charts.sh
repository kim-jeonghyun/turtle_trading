#!/usr/bin/env bash
# 주간 차트 자동 생성 래퍼 스크립트 (로컬 호스트용)
# Docker 환경: crontab 파일에서 직접 fetch_universe_charts.py 실행
# 로컬 환경: 0 6 * * 6 /path/to/turtle_trading/scripts/weekly_charts.sh
#
# 기능:
#   - fetch_universe_charts.py 실행
#   - 로그 파일 저장 (logs/weekly_charts/)
#   - 실패 시 notifier 알림 발송
#   - 30일 이상 된 로그 자동 정리

set -euo pipefail

# 프로젝트 루트 (이 스크립트 기준 상위 디렉토리)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 로그 디렉토리
LOG_DIR="$PROJECT_ROOT/logs/weekly_charts"
mkdir -p "$LOG_DIR"

# 로그 파일명: YYYY-MM-DD_HHMMSS.log
TIMESTAMP=$(date +"%Y-%m-%d_%H%M%S")
LOG_FILE="$LOG_DIR/$TIMESTAMP.log"

# Python 가상환경
VENV_PATH="$PROJECT_ROOT/.venv/bin/python"
if [ ! -f "$VENV_PATH" ]; then
    echo "[$TIMESTAMP] ERROR: Python venv not found at $VENV_PATH" | tee "$LOG_FILE"
    exit 1
fi

# 실패 시 알림 발송 함수
send_failure_notification() {
    local exit_code="$1"
    local log_file="$2"
    "$VENV_PATH" -c "
import asyncio
from src.notifier import NotificationManager, NotificationMessage, NotificationLevel
async def notify():
    mgr = NotificationManager()
    msg = NotificationMessage(
        title='주간 차트 생성 실패',
        body='weekly_charts.sh 실행 실패 (exit code: $exit_code). 로그: $log_file',
        level=NotificationLevel.ERROR,
    )
    await mgr.send_message(msg)
asyncio.run(notify())
" 2>/dev/null || echo "[$TIMESTAMP] WARNING: 알림 발송 실패 (notifier 설정 확인 필요)" >> "$log_file"
}

echo "[$TIMESTAMP] 주간 차트 생성 시작" | tee "$LOG_FILE"

# 차트 생성 실행
if "$VENV_PATH" "$PROJECT_ROOT/scripts/fetch_universe_charts.py" >> "$LOG_FILE" 2>&1; then
    echo "[$(date +"%Y-%m-%d_%H%M%S")] 차트 생성 완료" | tee -a "$LOG_FILE"
else
    EXIT_CODE=$?
    echo "[$(date +"%Y-%m-%d_%H%M%S")] ERROR: 차트 생성 실패 (exit code: $EXIT_CODE)" | tee -a "$LOG_FILE"
    cd "$PROJECT_ROOT" && send_failure_notification "$EXIT_CODE" "$LOG_FILE"
    exit $EXIT_CODE
fi

# 30일 이상 된 로그 정리
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true

echo "[$(date +"%Y-%m-%d_%H%M%S")] 완료" | tee -a "$LOG_FILE"
