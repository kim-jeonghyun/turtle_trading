# Turtle Trading System - CLAUDE OPERATING GUIDE

Last updated: 2026-02-23

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

## 3. 보안 및 제약

### 보안

- API key / secret / token 은 `.env` 또는 환경 변수만 사용
- 로그/에러에 민감정보 마스킹 적용, 브랜치/커밋에 계좌/주문 값 노출 금지
- 실거래 키는 개발 키와 분리 보관

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

### src/

| 파일 | 책임 | 의존 방향 |
|------|------|-----------|
| `types.py` | Enum/도메인 타입 중앙화 | 전체 공통 |
| `indicators.py` | ATR, Donchian 등 순수 계산 | data_store/시그널/백테스트 |
| `data_fetcher.py` | 시장 데이터 획득(캐시 우선) | 외부 API + data_store |
| `data_store.py` | Parquet 저장/조회/TTL | fetcher + 분석 모듈 |
| `position_sizer.py` | 위험 기반 수량 산정 | RiskManager + tracker |
| `risk_manager.py` | 포트폴리오 한도/상관군 제한 | auto_trader + position_sizer |
| `pyramid_manager.py` | 피라미딩 상태 전이 | tracker + position_sizer |
| `position_tracker.py` | 포지션 생애주기/손익 계산 | trader + scripts + risk |
| `inverse_filter.py` | Inverse ETF 디케이 감시 | check_positions + trader |
| `universe_manager.py` | 심볼·그룹 관리 | 스크리닝/시그널/보고 |
| `kis_api.py` | 주문/조회/예외 처리 | auto_trader + backtester |
| `auto_trader.py` | 주문 라우팅, 상태 동기화 | risk/notifier/kis_api |
| `backtester.py` | 전략 검증 파이프라인 | tests + scripts |
| `notifier.py` | 알림 발송 채널 통합 | 운영 스크립트 |

### scripts/

| 파일 | 목적 | 빈도 |
|------|------|------|
| `check_positions.py` | 포지션 상태/Stop 점검 | 매시 cron |
| `check_risk_limits.py` | 리스크 한도 점검 | 주기적 |
| `daily_report.py` | 일일 요약 전송 | 매일 |
| `health_check.py` | 시스템/연동 상태 점검 | 짧은 주기 |
| `run_backtest.py` | 백테스트 엔트리포인트 | 수동 |
| `security_check.py` | 설정/키/권한 경고 | 주기적 |
| `weekly_report.py` | 주간 성과 요약 | 주간 |

### 설정 파일

- `config/universe.yaml`: 심볼 단일 원본
- `config/correlation_groups.yaml`: 상관군/최대 노출 정책
- `config/notifications.yaml`: 알림 채널/이벤트

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
python scripts/run_backtest.py      # 백테스트
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

### Claude 행동 규칙

- 트레이딩 로직 변경 시 백테스트/리스크 체크리스트 먼저 제시
- 운영 이슈: "재현 스텝 + 영향 범위 + 완화안" 형태
- 알림·체결·리스크 중 하나라도 불완전하면 우선순위 높여 수정
- 추측성 최적화 금지 — 코드·데이터·테스트 근거로만 조치

## 연결 문서

- `docs/operations-guide.md` — 운영/백테스트/모니터링 상세
- `.claude/rules/git-workflow.md` — 브랜치/PR/커밋 규칙
- `config/universe.yaml` — 심볼 원본
- `config/correlation_groups.yaml` — 상관군 정책
- `research/readings/` — 전략 리서치 자료
