FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

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
