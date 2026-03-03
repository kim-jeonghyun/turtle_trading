#!/bin/bash
# research/readings/ → iCloud Obsidian Vault 실시간 동기화
#
# 사용법:
#   ./scripts/sync_to_obsidian.sh              # 기본 vault 경로 사용
#   OBSIDIAN_VAULT=~/path/to/vault ./scripts/sync_to_obsidian.sh  # 커스텀 경로
#
# 종료: Ctrl+C 또는 kill
#
# 요구사항: brew install fswatch

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE_DIR="$PROJECT_DIR/research/readings"

# Obsidian vault 경로 (환경변수 또는 기본값)
OBSIDIAN_VAULT="${OBSIDIAN_VAULT:-$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/TurtleTrading}"
TARGET_DIR="$OBSIDIAN_VAULT/readings"

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[sync]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err() { echo -e "${RED}[error]${NC} $1"; exit 1; }

# 사전 검증
command -v fswatch >/dev/null 2>&1 || err "fswatch 미설치. brew install fswatch"
command -v rsync >/dev/null 2>&1 || err "rsync 미설치"
[ -d "$SOURCE_DIR" ] || err "소스 디렉토리 없음: $SOURCE_DIR"

# Obsidian vault 디렉토리 확인/생성
if [ ! -d "$OBSIDIAN_VAULT" ]; then
    warn "Obsidian vault 디렉토리 없음: $OBSIDIAN_VAULT"
    warn "Obsidian 앱에서 iCloud vault를 먼저 생성하세요."
    warn "vault 이름: TurtleTrading"
    err "vault 생성 후 다시 실행하세요."
fi

mkdir -p "$TARGET_DIR"

# 단방향 미러 동기화: SOURCE → TARGET
# --delete: 소스에 없는 파일은 대상에서 삭제됨 (vault에 직접 추가한 파일 주의)
do_sync() {
    rsync -av --delete \
        --exclude='.DS_Store' \
        --exclude='.obsidian' \
        "$SOURCE_DIR/" "$TARGET_DIR/"
}

log "초기 동기화 시작..."
log "  소스: $SOURCE_DIR"
log "  대상: $TARGET_DIR"
do_sync
log "초기 동기화 완료"

# 파일 변경 감시
log "파일 변경 감시 시작... (Ctrl+C로 종료)"

fswatch -o --latency 2 "$SOURCE_DIR" | while read -r _; do  # 연속 변경 시 2초 묶어 처리
    log "변경 감지 → 동기화 중..."
    do_sync
    log "동기화 완료 ($(date '+%H:%M:%S'))"
done
