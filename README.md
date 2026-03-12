# Turtle Trading System

> **v3.8.1** | Python 3.12 | MIT License

터틀 트레이딩 전략을 기반으로 한 반자동 멀티마켓 매매 시스템입니다.

## 주요 기능

### 트레이딩 시스템

- **System 1**: 20일 돌파 진입 / 10일 이탈 청산 (직전 거래 수익 시 스킵, 55일 failsafe 허용)
- **System 2**: 55일 돌파 진입 / 20일 이탈 청산 (필터 없음)
- **Wilder's ATR (N)**: 변동성 기반 포지션 사이징

### 리스크 관리

- 1% 리스크 기반 포지션 사이징 (Curtis Faith 원서 기준)
- 피라미딩: 0.5N 간격, 최대 4 Units
- 스톱로스: 진입가 기준 2N
- 포트폴리오 리스크 한도:
  - 상관 그룹: 6 Units
  - 단일 방향: 12 Units
  - 전체 N 노출: 10 단위 이하

### 지원 시장

14개 자산그룹, 42종목 유니버스:

- 미국 주식/ETF (SPY, QQQ, NVDA 등)
- 한국 주식 (삼성전자, SK하이닉스 등 — KIS OpenAPI)
- 유럽/중국 ETF (VGK, MCHI 등)
- 원자재 ETF (GLD, SLV, USO, DBA 등)
- 채권 ETF (TLT, SHY, TIP)
- 암호화폐 ETF (BITO, ETHA)
- REIT (VNQ)
- 대체투자 (DBMF)

### 알림 시스템

- Telegram, Discord, Email (재시도 + 에스컬레이션 로직 포함)

### 주간 차트 자동 생성

- mplfinance 기반 3-panel 차트 (캔들+MA, 거래량, MACD)
- 전 유니버스 42종목 자동 렌더링 (토요일 06:00 KST)
- 이동평균 4종 (5/20/60/120일) + MACD(12,26,9)

## 빠른 시작

### 방법 1: Docker 배포 (권장)

운영 환경에서는 Docker Compose로 실행합니다. cron 기반 자동화가 포함되어 있습니다.

> **필수**: Docker Desktop (또는 Docker Engine + Compose V2)
> **선택**: 한국투자증권 API 키 (실거래/모의투자), 알림 채널 (Telegram/Discord/Email)
> 알림과 API 키 없이도 백테스트 및 시그널 확인은 가능합니다.

```bash
# 1. 환경 변수 설정
cp .env.example .env
# .env 파일을 편집하여 API 키, 알림 채널 설정

# 2. 데이터/로그 디렉토리 생성 (gitignore 대상이므로 clone 후 수동 생성 필요)
mkdir -p data logs

# 3. 빌드 및 시작
docker compose up -d --build

# 4. 상태 확인
docker compose ps
docker compose logs turtle-cron --tail 20
```

#### 서비스 구성

| 서비스 | 역할 | 포트 |
|--------|------|------|
| `turtle-cron` | cron 스케줄러 (supercronic) — 데이터 수집, 시그널 체크, 모니터링 | - |
| `turtle-dashboard` | Streamlit 대시보드 | `localhost:8501` |

#### 수동 데이터 수집

```bash
# 오늘 날짜 OHLCV 수집 (장 마감 후)
docker compose exec turtle-cron python scripts/collect_daily_ohlcv.py --date $(date +%Y-%m-%d)

# Dry-run (실제 저장 없이 시뮬레이션)
docker compose exec turtle-cron python scripts/collect_daily_ohlcv.py --dry-run
```

#### 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `FATAL: /app/data is not writable by turtle (UID 1000)` | bind mount 디렉토리 미생성 또는 권한 불일치 | `mkdir -p data logs && chown -R $(id -u):$(id -g) ./data ./logs` |
| 권한 오류 (Linux, UID != 1000) | 호스트 UID가 컨테이너 기본값(1000)과 불일치 | `.env`에 `DOCKER_UID=$(id -u)`, `DOCKER_GID=$(id -g)` 추가 후 재빌드 |
| 컨테이너 즉시 종료 | `.env` 누락 또는 설정 오류 | `docker compose logs turtle-cron` 확인 |
| 대시보드 접속 불가 | 포트 충돌 또는 서비스 미시작 | `docker compose ps`로 상태 확인, `lsof -i :8501`로 포트 점유 확인 |

#### 중지 및 재시작

```bash
docker compose down          # 중지
docker compose up -d         # 재시작 (이미지 재사용)
docker compose up -d --build # 코드 변경 후 재빌드
```

### 방법 2: 로컬 개발

#### 1. 설치

```bash
git clone https://github.com/kim-jeonghyun/turtle_trading.git
cd turtle_trading
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

#### 2. 환경 변수 설정

```bash
cp .env.example .env
# .env 파일을 편집하여 API 키 설정
```

#### 3. 테스트

```bash
pytest -q
```

#### 4. 실행

```bash
# 포지션 & 시그널 체크
python scripts/check_positions.py

# 일일 리포트
python scripts/daily_report.py

# 시스템 건강진단
python scripts/health_check.py

# 백테스트
python scripts/run_backtest.py
```

## 프로젝트 구조

```
turtle_trading/
├── src/                        # 핵심 라이브러리
│   ├── types.py                # Enum/도메인 타입 중앙화 (Direction, SignalType 등)
│   ├── indicators.py           # ATR, Donchian 등 순수 계산
│   ├── data_fetcher.py         # 시장 데이터 획득 (캐시 우선)
│   ├── data_store.py           # Parquet 저장/조회/TTL
│   ├── position_sizer.py       # 위험 기반 수량 산정 (LivePosition, AccountState)
│   ├── risk_manager.py         # 포트폴리오 한도/상관군 제한
│   ├── pyramid_manager.py      # 피라미딩 상태 전이
│   ├── position_tracker.py     # 포지션 생애주기/손익 계산
│   ├── inverse_filter.py       # Inverse ETF 디케이 감시
│   ├── kill_switch.py             # 시스템 거래 정지 스위치
│   ├── universe_manager.py     # 심볼/그룹 관리
│   ├── kis_api.py              # 한국투자증권 주문/조회
│   ├── local_chart_renderer.py    # mplfinance 차트 렌더링
│   ├── auto_trader.py          # 주문 라우팅, 상태 동기화
│   ├── backtester.py           # 전략 검증 파이프라인
│   ├── cost_analyzer.py           # 슬리피지/수수료 측정, 비용 예산 관리
│   ├── notifier.py             # 알림 발송 (Telegram/Discord/Email)
│   ├── paper_trader.py            # 모의투자 시뮬레이션
│   ├── position_sync.py           # KIS 잔고 vs 로컬 포지션 동기화
│   ├── script_helpers.py       # 스크립트 공통 유틸리티
│   ├── analytics.py            # 거래 성과 분석 (R-배수, Sortino 등)
│   ├── market_calendar.py      # 시장 영업일/상태 판단
│   ├── security.py             # 보안 검증 유틸리티
│   ├── monitor_state.py        # 장중 모니터링 알림 상태 관리
│   ├── market_breadth.py       # 시장 브레드스 지표 (% above MA, NH/NL, AD)
│   ├── regime_detector.py      # 시장 레짐 분류 (5단계)
│   ├── screener.py             # 멀티 전략 스크리너 (Strategy Protocol)
│   ├── spot_price.py           # 실시간 가격 조회 (KIS API)
│   ├── trading_guard.py           # 주문 전 안전 검증 (일일 손실 한도)
│   ├── utils.py                # 공유 유틸 (atomic write, retry, 심볼 검증)
│   └── vi_cb_detector.py          # VI/CB 상태 탐지
│
├── scripts/                    # 운영 스크립트
│   ├── check_positions.py      # 포지션 상태/시그널/스톱 점검
│   ├── check_risk_limits.py    # 리스크 한도 점검
│   ├── collect_daily_ohlcv.py  # OHLCV 일별 배치 수집
│   ├── cleanup_old_data.py     # 오래된 데이터 정리
│   ├── daily_report.py         # 일일 요약 전송
│   ├── weekly_report.py        # 주간 성과 요약
│   ├── health_check.py         # 시스템/연동 상태 점검
│   ├── security_check.py       # 설정/키/권한 경고
│   ├── run_backtest.py         # 백테스트 엔트리포인트
│   ├── monitor_positions.py    # 포지션 모니터링
│   ├── auto_trade.py           # 자동 매매 실행
│   ├── list_positions.py       # 포지션 목록 조회
│   ├── performance_review.py   # 성과 리뷰
│   ├── validate_data.py        # 데이터 정합성 검증
│   ├── test_notifications.py   # 알림 채널 테스트
│   ├── backup_data.sh          # 데이터 백업
│   ├── check_overfitting.py       # 백테스트 과적합 점검
│   ├── fetch_universe_charts.py   # 유니버스 전종목 차트 수집
│   ├── go_live_check.py           # 실거래 전 사전 검증
│   ├── paper_trade_report.py      # 모의투자 성과 리포트
│   ├── sync_positions.py          # KIS 잔고 동기화
│   ├── toggle_trading.py          # 킬스위치 CLI
│   ├── weekly_charts.sh           # 주간 차트 자동 생성 (cron)
│   ├── market_intelligence.py  # 시장 인텔리전스 리포트 생성·전송
│   └── deploy-v3.2.1.sh        # v3.2.1 배포 (Legacy)
│
├── config/                     # 설정 파일
│   ├── universe.yaml           # 거래 유니버스 (심볼 단일 원본)
│   ├── correlation_groups.yaml # 상관군/최대 노출 정책
│   ├── notifications.yaml.example  # 알림 채널/이벤트 설정
│   ├── ohlcv_collection.yaml   # OHLCV 수집 대상 (KOSPI 200 + KOSDAQ 150)
│   └── system_status.yaml     # 킬스위치 상태
│
├── data/                       # 런타임 데이터 (gitignore)
│   ├── cache/                  # OHLCV Parquet 캐시
│   ├── charts/                # 주간 차트 PNG
│   ├── trades/                 # 거래 기록 JSON
│   ├── signals/                # 시그널 기록
│   └── ohlcv/                  # 일별 OHLCV 축적 데이터 (KOSPI 200 + KOSDAQ 150)
│
├── tests/                      # 테스트 스위트
├── docs/                       # 운영 가이드
├── pyproject.toml              # 패키지/의존성/도구 설정
├── CHANGELOG.md                # 버전별 변경 이력
├── app.py                      # Streamlit 대시보드 진입점
├── .env.example                # 환경 변수 템플릿
├── Dockerfile                  # Docker 이미지 빌드
├── docker-compose.yaml         # 서비스 정의 (turtle-cron + turtle-dashboard)
├── crontab                     # cron 스케줄 설정
└── entrypoint.sh               # 컨테이너 진입점 (권한 검증)
```

## 기술 스택

| 범주 | 기술 |
|------|------|
| Language | Python 3.12 |
| Core | pandas, numpy, pydantic, PyYAML, aiohttp |
| Testing | pytest, ruff, mypy |
| Market data | yfinance, FinanceDataReader, ccxt |
| Broker | 한국투자증권 OpenAPI (KIS) |
| 알림 | Telegram, Discord, Email |
| 저장소 | Parquet 캐시, JSON 트랜잭션 로그 |

## 설정

### 알림 채널

| 채널 | 환경 변수 |
|------|----------|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Discord | `DISCORD_WEBHOOK_URL` |
| Email | `EMAIL_USER`, `EMAIL_PASSWORD`, `EMAIL_TO`, `SMTP_HOST`, `SMTP_PORT` |

### 한국투자증권 API

1. [한국투자증권 OpenAPI](https://apiportal.koreainvestment.com/) 가입
2. 앱 키 발급
3. `.env`에 설정

## 백테스트

```bash
python scripts/run_backtest.py
```

## 참고 자료

- [Way of the Turtle - Curtis Faith](https://www.amazon.com/Way-Turtle-Methods-Ordinary-Legendary/dp/007148664X)
- [Original Turtle Trading Rules](https://www.trendfollowing.com/whitepaper/turtle-rules.pdf)

## 면책 조항

이 프로젝트는 교육 목적으로만 제공됩니다. 실제 투자에 사용할 경우 발생하는 모든 손실에 대한 책임은 사용자에게 있습니다.

## 라이선스

MIT License
