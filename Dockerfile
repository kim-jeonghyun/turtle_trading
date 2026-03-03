FROM python:3.12-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# supercronic 설치 (multi-arch: amd64/arm64)
ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.43
RUN ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" && \
    case "$ARCH" in \
      arm64) \
        SUPERCRONIC_SHA1SUM="5c6266786c2813d6f8a99965d84452faae42b483" && \
        SUPERCRONIC_URL="https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-arm64" ;; \
      amd64) \
        SUPERCRONIC_SHA1SUM="f97b92132b61a8f827c3faf67106dc0e4467ccf2" && \
        SUPERCRONIC_URL="https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" ;; \
      *) echo "Error: unsupported architecture '$ARCH'" >&2 && exit 1 ;; \
    esac && \
    curl -fsSLo /usr/local/bin/supercronic "$SUPERCRONIC_URL" && \
    echo "${SUPERCRONIC_SHA1SUM}  /usr/local/bin/supercronic" | sha1sum -c - && \
    chmod +x /usr/local/bin/supercronic

# 1단계: pyproject.toml 기반 패키지 설치
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# 2단계: 런타임에 필요한 파일만 명시적 COPY (COPY . . 금지 — 이중 상태 방지)
COPY scripts/ scripts/
COPY config/ config/
COPY crontab /app/crontab
COPY app.py .

# 디렉토리 생성
RUN mkdir -p /app/data/cache /app/data/trades /app/data/signals /app/data/ohlcv /app/logs

# Non-root user for data/log directories
RUN groupadd --gid 1000 turtle && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash turtle && \
    chown -R turtle:turtle /app/data /app/logs

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 환경 변수
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Seoul
ENV PYTHONPATH=/app

ENTRYPOINT ["/app/entrypoint.sh"]
USER turtle
CMD ["supercronic", "/app/crontab"]
