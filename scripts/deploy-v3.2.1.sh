#!/bin/bash
# v3.2.1 Docker Build & Deploy Script
# 사용법: bash scripts/deploy-v3.2.1.sh
#
# 사전 조건:
# 1. Docker Desktop 실행
# 2. 현재 브랜치: main (v3.2.1 코드 포함)
# 3. Pre-deployment 검증 완료 (artifacts/task-1.2.3-precheck.md)
# 4. 롤백 절차 숙지 (.sisyphus/reviews/v3.2.1-rollback-procedure.md)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION="v3.2.1"
IMAGE_NAME="turtle-trading"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

cd "$PROJECT_DIR"

echo "============================================"
echo "  Turtle Trading System - $VERSION Deploy"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "============================================"

# Step 0: Docker 데몬 확인
echo ""
echo "[0/6] Docker 데몬 확인..."
if ! docker info &>/dev/null; then
    echo "ERROR: Docker 데몬이 실행 중이 아닙니다. Docker Desktop을 먼저 실행해주세요."
    exit 1
fi
echo "  Docker 데몬 실행 중"

# Step 1: Git 상태 확인
echo ""
echo "[1/6] Git 상태 확인..."
BRANCH=$(git branch --show-current)
echo "  현재 브랜치: $BRANCH"
if [ "$BRANCH" != "main" ]; then
    echo "WARNING: main 브랜치가 아닙니다. 계속하시겠습니까? (y/N)"
    read -r response
    [ "$response" != "y" ] && exit 1
fi
COMMIT=$(git rev-parse --short HEAD)
echo "  최신 커밋: $COMMIT"

# Step 2: 포지션 파일 백업
echo ""
echo "[2/6] 포지션 파일 백업..."
if [ -f "data/positions/positions.json" ]; then
    BACKUP_DIR="data/positions/backups"
    mkdir -p "$BACKUP_DIR"
    cp "data/positions/positions.json" "$BACKUP_DIR/positions-pre-${VERSION}-${TIMESTAMP}.json"
    echo "  백업 완료: $BACKUP_DIR/positions-pre-${VERSION}-${TIMESTAMP}.json"
else
    echo "  WARNING: positions.json 파일이 없습니다 (신규 환경인 경우 정상)"
fi

# Step 3: 기존 이미지 태깅 (롤백용)
echo ""
echo "[3/6] 기존 이미지 태깅 (롤백용)..."
if docker image inspect "${IMAGE_NAME}:latest" &>/dev/null; then
    docker tag "${IMAGE_NAME}:latest" "${IMAGE_NAME}:pre-${VERSION}-backup"
    echo "  백업 태그 생성: ${IMAGE_NAME}:pre-${VERSION}-backup"
else
    echo "  기존 이미지 없음 (첫 빌드)"
fi

# Step 4: Docker 이미지 빌드 + 태깅
echo ""
echo "[4/6] Docker 이미지 빌드..."
docker build -t "${IMAGE_NAME}:${VERSION}" -t "${IMAGE_NAME}:latest" .
echo "  빌드 완료:"
echo "    - ${IMAGE_NAME}:${VERSION}"
echo "    - ${IMAGE_NAME}:latest"

# Step 5: 이미지 내 signal_check.py 부재 확인
echo ""
echo "[5/6] 이미지 내 signal_check.py 검증..."
GREP_RESULT=$(docker run --rm "${IMAGE_NAME}:${VERSION}" find /app -name "signal_check*" 2>/dev/null || true)
if [ -z "$GREP_RESULT" ]; then
    echo "  PASS: signal_check.py 없음"
else
    echo "  FAIL: signal_check 관련 파일 발견: $GREP_RESULT"
    echo "  배포를 중단합니다."
    exit 1
fi

# Step 6: 컨테이너 재시작
echo ""
echo "[6/6] 컨테이너 재시작..."
docker-compose down
docker-compose up -d
echo "  turtle-cron + turtle-dashboard 서비스 재시작 완료"

echo ""
echo "============================================"
echo "  배포 완료: $VERSION ($COMMIT)"
echo "============================================"
echo ""
echo "다음 단계 (Post-deployment):"
echo "  1. 첫 KR 실행 (16:00) 로그 확인: tail -f logs/check_kr.log"
echo "  2. 첫 US 실행 (07:00) 로그 확인: tail -f logs/check_us.log"
echo "  3. Telegram 알림 수신 확인"
echo "  4. 수동 Donchian 채널 계산 대조 (2-3 종목)"
echo "  5. docker exec turtle-cron crontab -l  # crontab 확인"
echo "  6. 이상 발생 시 롤백 절차서 참조 (아래)"
echo ""
echo "롤백 절차: .sisyphus/reviews/v3.2.1-rollback-procedure.md"
