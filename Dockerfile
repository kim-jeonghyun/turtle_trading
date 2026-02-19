FROM python:3.12-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y \
    cron \
    && rm -rf /var/lib/apt/lists/*

# 1단계: pyproject.toml 기반 패키지 설치
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# 2단계: 런타임에 필요한 파일만 명시적 COPY (COPY . . 금지 — 이중 상태 방지)
COPY scripts/ scripts/
COPY config/ config/

# 디렉토리 생성
RUN mkdir -p /app/data/cache /app/data/trades /app/data/signals /app/logs

# Crontab 설정
COPY crontab /etc/cron.d/turtle-cron
RUN chmod 0644 /etc/cron.d/turtle-cron
RUN crontab /etc/cron.d/turtle-cron

# 환경 변수
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Seoul

# 기본 명령어
CMD ["cron", "-f"]
