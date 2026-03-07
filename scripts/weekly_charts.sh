#!/usr/bin/env bash
# 주간 차트 자동 생성 래퍼 스크립트
# cron 등록: 0 6 * * 6 /path/to/turtle_trading/scripts/weekly_charts.sh
#
# 기능:
#   - fetch_universe_charts.py 실행
#   - 로그 파일 저장 (logs/weekly_charts/)
#   - 실패 시 종료 코드 전파
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

# Python 가상환경 활성화
VENV_PATH="$PROJECT_ROOT/.venv/bin/python"
if [ ! -f "$VENV_PATH" ]; then
    echo "[$TIMESTAMP] ERROR: Python venv not found at $VENV_PATH" | tee "$LOG_FILE"
    exit 1
fi

echo "[$TIMESTAMP] 주간 차트 생성 시작" | tee "$LOG_FILE"

# 차트 생성 실행
if "$VENV_PATH" "$PROJECT_ROOT/scripts/fetch_universe_charts.py" >> "$LOG_FILE" 2>&1; then
    echo "[$(date +"%Y-%m-%d_%H%M%S")] 차트 생성 완료" | tee -a "$LOG_FILE"
else
    EXIT_CODE=$?
    echo "[$(date +"%Y-%m-%d_%H%M%S")] ERROR: 차트 생성 실패 (exit code: $EXIT_CODE)" | tee -a "$LOG_FILE"
    exit $EXIT_CODE
fi

# 30일 이상 된 로그 정리
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true

echo "[$(date +"%Y-%m-%d_%H%M%S")] 완료" | tee -a "$LOG_FILE"
