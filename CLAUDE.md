# Turtle Trading System - CLAUDE OPERATING GUIDE

Last updated: 2026-03-10

## 1. 목적과 운영 원칙

- 목적: 터틀 트레이딩 원칙을 기반으로 한 반자동 멀티마켓 매매 시스템 운영
- 기본 정책: "검증된 전략 변경만 적용", "실거래는 단계적 승인 후 진행"
- 설계 철학: CLAUDE.md는 맵 역할, 세부 방법은 코드·테스트·연결 문서로 이동
- 기본 답변 규칙:
  1) 결론을 먼저 제시
  2) 위험/가정/제약을 함께 제시
  3) 실행할 액션을 최소 1개 제안

## 2. 핵심 전략 규칙 (요약)

### 2.1 System 1 (Short-term breakout)

- 진입: 20일 돌파 브레이크아웃
- 필터: 직전 거래 수익 시 20일 돌파 스킵 (단, 55일 돌파는 failsafe 진입 허용)
- 청산: 10일 하향 이탈

### 2.2 System 2 (Long-term breakout)

- 진입: 55일 돌파
- 필터: 없음
- 청산: 20일 하향 이탈

### 2.3 위험 계산

- N = Wilder ATR 20
- 스톱: 진입가 기준 2N
- 포지션 사이징: 계좌 대비 1% 리스크(기본, Curtis Faith 원서 기준)
- 피라미딩: 수익 방향으로 0.5N마다 추가 진입, 최대 4 Units/종목

### 2.4 포트폴리오 한도

- 상관그룹: 6 Units | 단일 방향: 12 Units | 총 N 노출: 10 단위 이하
- 실시간 위험 점검은 `risk_manager`에서 이중 검증

### 2.5 주문 안전 체인 (Guard Chain)

```
kill_switch → vi_cb_detector → trading_guard → AutoTrader(5M) → place_order
```

- **Entry-Only Block**: 모든 Guard는 BUY만 차단, SELL(손절/청산)은 항상 허용
- **Fail-Open**: 킬스위치/VI 탐지기는 설정 로드 실패 시 거래 허용 (안전한 기본값)
- **이중 안전장치**: TradingGuard(2M 비즈니스) + AutoTrader(5M 시스템)
- **상태 파일**: `data/trading_guard_state.json` (cron 프로세스 간 공유)

## 3. 보안 및 제약

### 보안

- API key / secret / token 은 `.env` 또는 환경 변수만 사용
- 로그/에러에 민감정보 마스킹 적용, 브랜치/커밋에 계좌/주문 값 노출 금지
- 실거래 키는 개발 키와 분리 보관
- Discord 웹훅 URL: HTTPS 필수, `discord.com`/`discordapp.com` 도메인만 허용, `/api/webhooks/` 경로 필수 (`src/notifier.py` 참조)
- KIS API 응답 로그: `_SAFE_LOG_KEYS`(`rt_cd`, `msg_cd`, `msg1`)만 DEBUG 출력, 민감 필드 자동 제외 (`docs/operations-guide.md` 참조)

### 거래 제약

- 상한가·하한가 도달 구간은 진입 제한, 거래 정지 종목은 시그널 무효 처리
- 공매도 제한 종목은 Long-only 우선, 일시 중단 플래그 시 주문 차단

### API/네트워크

| API | 제약 |
|-----|------|
| KIS | 초당 ~20건, 정책 변경 시 반영 |
| yfinance | 요청 과다 시 캐시 우선 |
| Binance | WebSocket 우선, 캐시 정합성 확인 |

- Rate limit → 재시도 + 백오프 + 알림

### 데이터 보존

- `data/` 산출물은 실시간 운영 전용, 장기 보존은 압축/정리 정책 준수
- 거래 로그는 회계·리스크 감사 목적의 최소 보존 기준 적용

## 4. 기술 스택

| 범주 | 기술 |
|------|------|
| Language | Python 3.12 (`.python-version` 참조) |
| Core libs | pandas, numpy, pydantic, PyYAML, requests/aiohttp |
| Testing | pytest, ruff, mypy |
| Market data | yfinance, FinanceDataReader, ccxt |
| Broker | 한국투자증권 OpenAPI (KIS) |
| UI/알림 | Streamlit, Telegram, Discord, Email |
| 저장소 | Parquet 캐시, JSON 트랜잭션 로그 |

## 5. 프로젝트 구조

### pages/ (Streamlit 대시보드 모듈)

| 파일 | 책임 |
|------|------|
| `__init__.py` | 패키지 초기화 |
| `dashboard.py` | 포트폴리오 대시보드 (캐시 통계, 오픈 포지션, PnL 추이) |
| `chart_analysis.py` | 차트 분석 (캔들스틱, 도치안 채널, ATR) |
| `signals.py` | 시그널 기록 조회 |
| `trades.py` | 거래 기록 (R-배수, 상세 expander, CSV 다운로드) |
| `performance.py` | 성과 분석 (에쿼티 커브, R-배수 히스토그램, 월별 히트맵) |
| `risk.py` | 리스크 현황 (N 노출, 상관그룹, 킬스위치/가드 상태) |
| `backtest.py` | 백테스트 실행 |

> `app.py`가 `st.radio` 수동 라우팅으로 페이지 선택. `pages/`는 일반 Python 패키지 (Streamlit 네이티브 multi-page 아님).
> 모든 페이지의 `render()` 시그니처는 `render(data_fetcher, data_store, universe, **kwargs)` 로 통일. 신규 페이지 추가 시 이 규칙을 따를 것.

### src/

| 파일 | 책임 | 의존 방향 |
|------|------|-----------|
| `types.py` | Enum/도메인 타입 중앙화 | 전체 공통 |
| `indicators.py` | ATR, Donchian 등 순수 계산 | data_store/시그널/백테스트 |
| `data_fetcher.py` | 시장 데이터 획득(캐시 우선) | 외부 API + data_store |
| `data_store.py` | Parquet 저장/조회/TTL | fetcher + 분석 모듈 |
| `position_sizer.py` | 위험 기반 수량 산정 | RiskManager + tracker |
| `risk_manager.py` | 포트폴리오 한도/상관군 제한 | auto_trader + position_sizer |
| `screener.py` | 멀티 전략 스크리너 (Strategy Protocol, 확장 가능) | indicators + types |
| `pyramid_manager.py` | 피라미딩 상태 전이 | tracker + position_sizer |
| `regime_detector.py` | Rule-based 시장 레짐 분류 (5단계) | indicators |
| `position_tracker.py` | 포지션 생애주기/손익 계산 | trader + scripts + risk |
| `inverse_filter.py` | Inverse ETF 디케이 감시 | check_positions + trader |
| `universe_manager.py` | 심볼·그룹 관리 (15그룹, 42종목) | 스크리닝/시그널/보고 |
| `kis_api.py` | 주문/조회/예외 처리 | auto_trader + backtester |
| `auto_trader.py` | 주문 라우팅, 상태 동기화 | risk/notifier/kis_api |
| `backtester.py` | 전략 검증 파이프라인 + 리스크 한도 | indicators + position_sizer + pyramid_manager + risk_manager |
| `local_chart_renderer.py` | mplfinance 차트 렌더링 | fetch_universe_charts |
| `market_breadth.py` | 시장 브레드스 지표 (% above MA, 52주 NH/NL, AD, 종합 점수) | data_store + indicators |
| `notifier.py` | 알림 발송 채널 통합 | 운영 스크립트 |
| `kill_switch.py` | 시스템 거래 정지 스위치 (BUY만 차단) | auto_trader + trading_guard |
| `trading_guard.py` | 일일 손실 서킷브레이커/최대 주문 제한 | kill_switch + auto_trader |
| `vi_cb_detector.py` | VI/CB 상태 탐지 (진입 차단) | trading_guard |
| `cost_analyzer.py` | 슬리피지/수수료 측정, 비용 예산 관리 | auto_trader + check_positions |
| `paper_trader.py` | 모의투자 시뮬레이션 | auto_trader (OrderRecord) |
| `position_sync.py` | KIS 잔고 vs 로컬 포지션 동기화 | kis_api + position_tracker |
| `script_helpers.py` | 스크립트 공통: config 로딩, 알림 셋업 | notifier + risk_manager |
| `analytics.py` | 거래 성과 분석 (R-배수, 승률, MDD) | 포지션 데이터 |
| `market_calendar.py` | 시장 영업일/DST/타임존 관리 | check_positions + monitor |
| `monitor_state.py` | 장중 알림 중복 방지 상태 관리 | monitor_positions |
| `spot_price.py` | 실시간 가격 조회 (KIS API, async) | kis_api + market_calendar |
| `security.py` | dry-run 강제, 환경변수/권한 검증 | security_check |
| `utils.py` | atomic write, retry, 심볼 검증 | 전체 공통 |

### scripts/

| 파일 | 목적 | 빈도 |
|------|------|------|
| `check_positions.py` | 포지션 상태/시그널/Stop 점검 | 매일 cron |
| `check_risk_limits.py` | 리스크 한도 점검 | 매시 cron |
| `monitor_positions.py` | 장중 실시간 가격/Stop 모니터링 | 5분 cron |
| `collect_daily_ohlcv.py` | OHLCV 일별 배치 수집 (~350종목) | 매일 cron |
| `daily_report.py` | 일일 요약 전송 | 매일 cron |
| `weekly_report.py` | 주간 성과 요약 | 토요일 cron |
| `monthly_report.py` | 월간 성과 요약 | 매월 1일 cron |
| `fetch_universe_charts.py` | 주간 차트 생성 (mplfinance) | 토요일 06:00 cron |
| `weekly_charts.sh` | 차트 생성 래퍼 (로컬 호스트) | 토요일 06:00 cron |
| `health_check.py` | 시스템/연동 상태 점검 | 4시간 cron |
| `auto_trade.py` | 자동 매매 실행 (dry-run 기본) | 수동 |
| `toggle_trading.py` | 킬스위치 CLI (거래 정지/재개) | 수동 |
| `go_live_check.py` | 실거래 전 사전 검증 체크리스트 | 수동 |
| `sync_positions.py` | KIS 잔고 vs 로컬 포지션 동기화 | 수동 |
| `run_backtest.py` | 백테스트 엔트리포인트 | 수동 |
| `check_overfitting.py` | 백테스트 과적합 점검 | 수동 |
| `performance_review.py` | 거래 성과 분석 | 수동 |
| `paper_trade_report.py` | 모의투자 성과 리포트 | 수동 |
| `list_positions.py` | 포지션 목록 조회 | 수동 |
| `market_intelligence.py` | 시장 인텔리전스 리포트 생성·전송 | 수집 후 자동/수동 |
| `validate_data.py` | 데이터 정합성 검증/수복 | 수동 |
| `cleanup_old_data.py` | 오래된 캐시/로그 정리 | 수동 |
| `security_check.py` | 설정/키/권한 경고 | 수동 |
| `test_notifications.py` | 알림 채널 테스트 | 수동 |
| `backup_data.sh` | 데이터 백업 (압축) | 매일 02:00 cron |

### 설정 파일

- `config/universe.yaml`: 심볼 단일 원본
- `config/correlation_groups.yaml`: 상관군/최대 노출 정책
- `config/notifications.yaml.example`: 알림 채널/이벤트 템플릿
- `config/system_status.yaml`: 킬스위치 상태 (enable/disable)

## 6. 명명 규칙 및 타입 규약

- `Direction`, `OrderStatus`, `SystemType` 등 Enum 사용 — 하드코딩 문자열 비교 금지
- `position_id` 중심 위치 추적, 종료도 `position_id` 단위 처리
- 계산 함수는 `float`/`Decimal` 스케일 명시, 가격/비율/단위를 변수명에 반영
- 실패 예상 로직은 예외 또는 명시적 실패 플래그 반환

## 7. 빠른 시작

```bash
# 개발 환경 세팅
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # 필요 항목만 채움
pytest -q              # 전체 테스트

# 주요 명령
python scripts/check_positions.py   # 포지션 점검
python scripts/health_check.py      # 건강진단
python scripts/run_backtest.py                # 백테스트 (리스크 한도 적용)
python scripts/run_backtest.py --no-risk-limits  # 리스크 한도 없이 순수 전략 성과
python scripts/security_check.py    # 보안 점검

# 디버깅 예시
pytest tests/test_position_tracker.py -k stop   # 전략 테스트
pytest tests/test_kis_api.py                     # API 장애 시나리오
pytest tests/test_data_store.py tests/test_data_fetcher.py  # 데이터 파이프라인
```

## 8. GitHub Flow & 브랜치 정책

- 상세 규칙: `.claude/rules/git-workflow.md` 참조
- 커밋 형식: `[#NNN] 제목 (50자 이내)`

### 코드 변경 체크플로우

1. **의도 정의**: 전략 규칙 vs 리스크 규칙 vs 운영 편의성 구분
2. **구현**: 최소 변경 범위로 먼저 적용
3. **테스트**: 변경 포인트 주변 케이스 보강
4. **백테스트**: 성능/리스크 영향 확인
5. **운영 검증**: 알림/청산/예외 처리 경로 수동 점검
6. **릴리즈**: 롤백 조건과 모니터링 포인트 정의

### 3계층 방어 체계

| 계층 | 역할 | 수단 |
|------|------|------|
| 1: GitHub 서버 | push 시점 차단 | Branch Protection Rules (활성) |
| 2: 로컬 결정론적 | AI 커밋/푸시 차단 | `.claude/settings.json` hooks |
| 3: 행동 지침 | AI 안내 | CLAUDE.md + `.claude/rules/` |

## 9. 테스트 전략

- 레이어: unit → integration → simulation → smoke
- 모든 새 코드에 assertion 존재, `pytest` 통과 필수, 실패 테스트 허용 안 됨
- 고위험 모듈(리스크/주문/API) 커버리지 우선 상향
- `tests/conftest.py`: `MPLBACKEND=Agg` 자동 설정 — headless 환경(CI/cron)에서 matplotlib 렌더링 보장

### 배포 보류 기준

- Stop-loss 계산 불일치 1건이라도 존재
- API 파싱 실패 처리 누락
- `scripts` 핵심 경로에서 예외 무시 패턴 발견

## 10. 운영/백테스트/모니터링

상세 가이드: `docs/operations-guide.md`

- 실거래 전: 백테스트 임계치, paper trading, 알림 점검, 롤백 절차
- 실거래 중: 리스크 상한 → 체결 동기화 → 스톱 이벤트 재검토
- 알림: signal/trade/error/risk 4분류, 실패성 우선 전송, 디바운스 적용

## 11. 코드 리뷰 & Claude 실행 힌트

### 리뷰 3축

1. **전략 일관성** — 기준 규칙 훼손 여부
2. **리스크 안정성** — 한도/stop-loss/필터
3. **운영 회복력** — 재시도, 로깅, 알림

### 회귀 위험 포인트

- 멀티 포지션/심볼 처리, `position_id` 추적
- 외부 API 응답 파싱 실패, 파일 경로/YAML 스키마 로딩
- `entry_reason` 전파 체인 (`backtester.entry_reasons` dict → `Trade.entry_reason` → `analytics` 렌더링) — 연결 고리 변경 시 거래 기록 누락 위험

### Claude 행동 규칙

- 트레이딩 로직 변경 시 백테스트/리스크 체크리스트 먼저 제시
- 운영 이슈: "재현 스텝 + 영향 범위 + 완화안" 형태
- 알림·체결·리스크 중 하나라도 불완전하면 우선순위 높여 수정
- 추측성 최적화 금지 — 코드·데이터·테스트 근거로만 조치

## 연결 문서

- `docs/operations-guide.md` — 운영/백테스트/모니터링 상세
- `docs/roadmap.md` — 개발 로드맵
- `docs/decisions/` — 아키텍처 결정 기록 (ADR)
- `.claude/rules/git-workflow.md` — 브랜치/PR/커밋 규칙
- `config/universe.yaml` — 심볼 원본
- `config/correlation_groups.yaml` — 상관군 정책
- `.claude/rules/youtube-digest.md` — YouTube digest 저장 경로/카테고리 규칙
- `scripts/README.md` — 스크립트 상세 레퍼런스
