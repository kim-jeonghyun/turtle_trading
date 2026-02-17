#!/bin/bash
################################################################################
# Turtle Trading Data Backup Script
# 포지션, 캐시, 설정 파일을 타임스탬프 백업
################################################################################

set -e  # 에러 발생 시 즉시 중단

# 색상 코드
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 기본 백업 디렉토리
BACKUP_BASE="${1:-data/backups}"
DATE_STAMP=$(date +"%Y-%m-%d_%H%M%S")
BACKUP_DIR="${BACKUP_BASE}/${DATE_STAMP}"

# 백업할 디렉토리 및 파일 목록
BACKUP_SOURCES=(
    "data/positions"
    "data/entries"
    "data/cache"
    "data/signals"
    "data/trades"
    "config"
    # NOTE: .env excluded from backups - contains secrets (API keys, tokens)
    # Use a secrets manager or manual backup for credentials
)

echo -e "${GREEN}=== Turtle Trading Data Backup ===${NC}"
echo "Backup directory: ${BACKUP_DIR}"
echo ""

# 백업 디렉토리 생성
mkdir -p "${BACKUP_DIR}"

# 백업 실행
TOTAL_SIZE=0
BACKUP_COUNT=0

for SOURCE in "${BACKUP_SOURCES[@]}"; do
    if [ -e "${SOURCE}" ]; then
        echo -e "${YELLOW}Backing up: ${SOURCE}${NC}"

        # 디렉토리인 경우
        if [ -d "${SOURCE}" ]; then
            cp -r "${SOURCE}" "${BACKUP_DIR}/"
        else
            # 파일인 경우
            cp "${SOURCE}" "${BACKUP_DIR}/"
        fi

        # 파일 크기 계산
        if [ -d "${SOURCE}" ]; then
            SIZE=$(du -sk "${SOURCE}" | cut -f1)
        else
            SIZE=$(du -k "${SOURCE}" | cut -f1)
        fi
        TOTAL_SIZE=$((TOTAL_SIZE + SIZE))
        BACKUP_COUNT=$((BACKUP_COUNT + 1))
    else
        echo -e "${YELLOW}Skipping (not found): ${SOURCE}${NC}"
    fi
done

echo ""

# 압축
ARCHIVE_NAME="${BACKUP_BASE}/backup_${DATE_STAMP}.tar.gz"
echo -e "${YELLOW}Compressing to: ${ARCHIVE_NAME}${NC}"
tar -czf "${ARCHIVE_NAME}" -C "${BACKUP_DIR}" .

# 압축 후 원본 디렉토리 삭제
rm -rf "${BACKUP_DIR}"

# 압축 파일 크기
ARCHIVE_SIZE=$(du -h "${ARCHIVE_NAME}" | cut -f1)

echo -e "${GREEN}Backup complete!${NC}"
echo "  - Files backed up: ${BACKUP_COUNT}"
echo "  - Archive size: ${ARCHIVE_SIZE}"
echo "  - Location: ${ARCHIVE_NAME}"
echo ""

# 오래된 백업 정리 (최근 30개 유지)
MAX_BACKUPS=30
BACKUP_FILES=($(ls -t ${BACKUP_BASE}/backup_*.tar.gz 2>/dev/null || true))
BACKUP_FILE_COUNT=${#BACKUP_FILES[@]}

if [ ${BACKUP_FILE_COUNT} -gt ${MAX_BACKUPS} ]; then
    echo -e "${YELLOW}Cleaning old backups (keeping last ${MAX_BACKUPS})...${NC}"

    DELETE_COUNT=$((BACKUP_FILE_COUNT - MAX_BACKUPS))
    for ((i=MAX_BACKUPS; i<BACKUP_FILE_COUNT; i++)); do
        OLD_BACKUP="${BACKUP_FILES[$i]}"
        echo "  Removing: ${OLD_BACKUP}"
        rm -f "${OLD_BACKUP}"
    done

    echo -e "${GREEN}Removed ${DELETE_COUNT} old backups${NC}"
fi

echo ""
echo -e "${GREEN}=== Backup Summary ===${NC}"
echo "Total backups: ${BACKUP_FILE_COUNT}"
echo "Latest: ${ARCHIVE_NAME}"
echo ""

# 복원 방법 안내
echo -e "${YELLOW}To restore from this backup:${NC}"
echo "  tar -xzf ${ARCHIVE_NAME} -C ."
echo ""
