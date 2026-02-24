# Turtle Trading System

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

- 미국 주식 (yfinance)
- 한국 주식 (FinanceDataReader, KIS OpenAPI)
- 암호화폐 (ccxt/Binance)
- 원자재/채권 ETF

### 알림 시스템

- Telegram, Discord, Email (재시도 + 에스컬레이션 로직 포함)

## 빠른 시작

### 1. 설치

```bash
git clone https://github.com/kim-jeonghyun/turtle_trading.git
cd turtle_trading
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. 환경 변수 설정

```bash
cp .env.example .env
# .env 파일을 편집하여 API 키 설정
```

### 3. 테스트

```bash
pytest -q
```

### 4. 실행

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
│   ├── universe_manager.py     # 심볼/그룹 관리
│   ├── kis_api.py              # 한국투자증권 주문/조회
│   ├── auto_trader.py          # 주문 라우팅, 상태 동기화
│   ├── backtester.py           # 전략 검증 파이프라인
│   ├── notifier.py             # 알림 발송 (Telegram/Discord/Email)
│   ├── script_helpers.py       # 스크립트 공통 유틸리티
│   ├── analytics.py            # 거래 성과 분석 (R-배수, Sortino 등)
│   ├── market_calendar.py      # 시장 영업일/상태 판단
│   ├── security.py             # 보안 검증 유틸리티
│   └── utils.py                # 공유 유틸 (atomic write, retry, 심볼 검증)
│
├── scripts/                    # 운영 스크립트
│   ├── check_positions.py      # 포지션 상태/시그널/스톱 점검
│   ├── check_risk_limits.py    # 리스크 한도 점검
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
│   └── test_notifications.py   # 알림 채널 테스트
│
├── config/                     # 설정 파일
│   ├── universe.yaml           # 거래 유니버스 (심볼 단일 원본)
│   ├── correlation_groups.yaml # 상관군/최대 노출 정책
│   └── notifications.yaml      # 알림 채널/이벤트 설정
│
├── data/                       # 런타임 데이터 (gitignore)
│   ├── cache/                  # OHLCV Parquet 캐시
│   ├── trades/                 # 거래 기록 JSON
│   └── signals/                # 시그널 기록
│
├── tests/                      # 테스트 스위트
├── docs/                       # 운영 가이드
├── pyproject.toml              # 패키지/의존성/도구 설정
├── CHANGELOG.md                # 버전별 변경 이력
└── .env.example                # 환경 변수 템플릿
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
