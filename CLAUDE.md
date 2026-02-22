# Turtle Trading System - CLAUDE OPERATING GUIDE

Last updated: 2026-02-19

---

## 1. 목적과 운영 원칙

- 목적: 터틀 트레이딩 원칙을 기반으로 한 반자동 멀티마켓 매매 시스템 운영
- 기본 정책: “검증된 전략 변경만 적용”, “실거래는 단계적 승인 후 진행”
- 설계 철학: CLAUDE.md는 맵 역할, 세부 방법은 코드·테스트·연결 문서로 이동
- 기본 답변 규칙:  
  1) 결론을 먼저 제시  
  2) 위험/가정/제약을 함께 제시  
  3) 실행할 액션을 최소 1개 제안

---

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
- 피라미딩: 수익 방향으로 0.5N마다 추가 진입
- 최대 Units: 4 Units/종목

### 2.4 포트폴리오 하한/상한

- 상관그룹: 6 Units
- 단일 방향(Long or Short): 12 Units
- 총 N 노출: 10 단위 이하
- 실시간 위험 점검은 `risk_manager`에서 이중 검증

---

## 3. 보안, 운영, 자산군 제약

### 3.1 기본 보안 규칙

- API key / secret / token 은 `.env` 또는 환경 변수만 사용
- 로그/에러 메시지에 민감정보가 유입되지 않도록 마스킹 적용
- 실거래 키는 개발 키와 분리 보관
- 브랜치/커밋 메시지에 계좌/주문 값 노출 금지

### 3.2 주문/거래 제약

- 상한가·하한가 도달 구간은 진입 제한
- 거래 정지 종목은 시그널 무효 처리
- 공매도 제한 종목은 Long-only 우선 검증
- 일시 중단 플래그가 있을 경우 새 주문 생성 차단

### 3.3 API/네트워크 제약

- KIS: 초당 약 20건(정책 변경 시 반영)
- yfinance: 요청 과다 시 캐시 우선 동작
- Binance/암호화폐: WebSocket 우선 정책 및 캐시 정합성 확인
- Rate limit 이벤트는 재시도 + 백오프 + 알림으로 처리

### 3.4 데이터 보존

- data/ 산출물은 실시간 운영 상태 확인 전용
- 장기 보존 자료는 압축/정리 정책 준수
- 실시간 거래 로그는 회계·리스크 감사 목적의 최소 보존 기준 적용

---

## 4. 기술 스택

- Language: Python 3.12 (단일 버전 — `.python-version` 파일 참조)
- Core libs: pandas, numpy, pydantic, PyYAML, requests/aiohttp 패턴
- Testing: pytest, ruff, mypy
- Market data: yfinance, FinanceDataReader, ccxt
- Broker/API: 한국투자증권 OpenAPI (KIS)
- UI/리포팅: Streamlit
- Messaging: Telegram, Discord, Email
- 저장소: Parquet 캐시, JSON 트랜잭션 로그
- 브랜치 관리: GitHub Flow (상세: `.claude/rules/git-workflow.md`)

---

## 5. 프로젝트 구조(운영 기준)

### 5.1 src/

| 파일 | 책임 | 의존 방향 |
| --- | --- | --- |
| `src/types.py` | Enum/도메인 타입 중앙화 | 전체 공통 |
| `src/indicators.py` | ATR, Donchian 등 순수 계산 | data_store/시그널/백테스트 |
| `src/data_fetcher.py` | 시장 데이터 획득(캐시 우선) | 외부 소스 API + data_store |
| `src/data_store.py` | Parquet 저장/조회/TTL 처리 | fetcher + 분석 모듈 |
| `src/position_sizer.py` | 위험 기반 수량 산정 | RiskManager + tracker 연동 |
| `src/risk_manager.py` | 포트폴리오 한도/상관군 제한 | auto_trader + position_sizer |
| `src/pyramid_manager.py` | 피라미딩 상태 전이 | tracker + position_sizer |
| `src/position_tracker.py` | 포지션 생애주기/손익 계산 | trader + scripts + risk |
| `src/inverse_filter.py` | Inverse ETF 디케이 감시/강제 청산 | check_positions + trader |
| `src/universe_manager.py` | 심볼·그룹 관리 | 스크리닝/시그널/보고 |
| `src/kis_api.py` | 주문/조회/상태 조회/예외 처리 | auto_trader + backtester |
| `src/auto_trader.py` | 주문 라우팅, 상태 동기화 | risk/notifier/kis_api |
| `src/backtester.py` | 전략 검증 파이프라인 | tests + scripts |
| `src/notifier.py` | 알림 발송 채널 통합 | 대부분 운영 스크립트 |

### 5.2 scripts/

| 파일 | 목적 | 빈도 |
| --- | --- | --- |
| `scripts/check_positions.py` | 포지션 상태/Stop logic 점검 | 매시 또는 cron |
| `scripts/check_risk_limits.py` | 리스크 한도 상태 점검 | 주기적 |
| `scripts/daily_report.py` | 일일 요약 전송 | 매일 |
| `scripts/health_check.py` | 시스템/외부연동 상태 점검 | 짧은 주기 |
| `scripts/run_backtest.py` | 백테스트 실행 엔트리포인트 | 수동 |
| `scripts/security_check.py` | 설정/키/권한 경고 탐지 | 주기적 |
| `scripts/weekly_report.py` | 주간 성과 요약 | 주간 |

### 5.3 tests

- 단위 테스트: `tests/test_*.py`
- 회귀 테스트: 전략/리스크/필터/트래킹 관련 핵심 케이스
- API/예외 테스트: rate limit, 파싱 실패, 상태 불일치 시나리오

### 5.4 설정 파일

- `config/universe.yaml`: 심볼 단일 원본
- `config/correlation_groups.yaml`: 상관군 및 최대 노출 정책
- `config/notifications.yaml`: 알림 채널/이벤트 정의
- 환경 변수는 코드가 아닌 런타임에서 주입

---

## 6. 명명 규칙 및 타입 규약

- 하드코딩 문자열 상태(예: "LONG", "SHORT")를 직접 비교하지 말고 `Direction`, `OrderStatus`, `SystemType` 등 Enum 사용
- `position_id` 중심으로 위치 추적을 수행
- 단일 symbol 기준 집계를 수행하더라도, 포지션 종료는 가능하면 `position_id` 단위로 처리
- 계산 함수는 `float`/`Decimal` 스케일을 명시하고, 가격/비율/단위를 주석 또는 변수명에 반영
- 실패가 예상되는 로직은 예외를 던지거나 명시적으로 실패 플래그를 반환

---

## 7. 빠른 시작 (Quick Start)

### 7.1 개발 환경

1. Python 3.12 확인: `python3 --version` (pyenv 사용 시 `pyenv install 3.12 && pyenv local 3.12`)
2. `python3.12 -m venv .venv`
3. `source .venv/bin/activate`
4. `pip install -e ".[dev]"`
5. `cp .env.example .env` (필요 항목만 채움)
6. `pytest -q`

### 7.2 주요 실행 명령

- 포지션 점검: `python scripts/check_positions.py`
- 포지션 데이터 정합성: `python scripts/list_positions.py`
- 백테스트: `python scripts/run_backtest.py`
- 건강진단: `python scripts/health_check.py`
- 보안 점검: `python scripts/security_check.py`

### 7.3 로컬 디버깅 예시

- 전략만 테스트: `pytest tests/test_position_tracker.py -k stop`
- API 장애 시나리오 테스트: `pytest tests/test_kis_api.py`
- 데이터 파이프라인: `pytest tests/test_data_store.py tests/test_data_fetcher.py`

---

## 8. GitHub Flow & Issue-Driven Development

### 8.1 브랜치 정책

- main은 항상 배포 가능한 상태 유지
- 모든 변경은 feature 브랜치 → PR → CI 통과 → merge
- main에 직접 commit/push 금지 (`.claude/hooks/enforce-branch-policy.sh`로 강제)
- 상세 규칙: `.claude/rules/git-workflow.md` 참조

### 8.2 개발 사이클

1. **Issue 생성**: 성공 기준(Acceptance Criteria) 체크리스트 포함
2. **Feature 브랜치 생성**: `feature/issue-NNN-<설명>`, `bugfix/issue-NNN-<설명>`
3. **구현 + 로컬 검증**: pytest, ruff check, mypy
4. **PR 생성**: 본문에 `Fixes #NNN` 포함 (이슈 자동 닫기)
5. **CI 통과 → merge**

### 8.3 코드 변경 체크플로우

1. **의도 정의**: 변경이 전략 규칙인지, 리스크 규칙인지, 운영 편의성인지 구분
2. **구현**: 최소 변경 범위로 먼저 적용
3. **테스트 추가/갱신**: 변경 포인트 주변 케이스를 먼저 보강
4. **백테스트 선행**: 실질 성능/리스크 영향 확인
5. **운영 검증**: 알림/청산/예외 처리 경로를 수동 점검
6. **릴리즈 판단**: 롤백 조건과 모니터링 포인트 정의

### 8.4 커밋 메시지 형식

`[#NNN] 제목 (50자 이내)` — 본문에 무엇을, 왜 변경했는지 기술

### 8.5 3계층 방어 체계

| 계층 | 역할 | 수단 |
|------|------|------|
| 계층 1: GitHub 서버 | push 시점 차단 | Branch Protection Rules |
| 계층 2: 로컬 결정론적 | AI 커밋/푸시 시도 차단 | `.claude/settings.json` hooks |
| 계층 3: 행동 지침 | AI에게 "왜/어떻게" 안내 | CLAUDE.md + `.claude/rules/` |

---

## 9. 테스트 전략

### 9.1 필수 테스트 레이어

- unit: 계산/분기/규칙 단위 로직
- integration: tracker, risk manager, api adapter 간 결합
- simulation: 과거 구간 기준 백테스트
- smoke: 핵심 스크립트 실행

### 9.2 최소 통과 기준

- 모든 새 코드 경로에 assertion 존재
- `pytest` 1차 통과
- 고위험 모듈(리스크/주문/API) 커버리지 상향
- 실패 테스트가 허용되지 않음

### 9.3 실무적인 실패 기준

- Stop-loss 계산 불일치 1건 존재 시 배포 보류
- API 파싱 실패 처리 누락 시 배포 보류
- `scripts` 핵심 경로에서 예외가 무시되는 패턴 발견 시 배포 보류

---

## 10. 실제 운영 체크리스트

### 10.1 실거래 전

- 백테스트 성능 임계치 재확인(수익/드로우다운/거래빈도)
- 모의 거래 or paper trading 기간 확인
- 알림 누락 여부 점검
- 롤백/중단 절차 테스트

### 10.2 실거래 중

- 주문 전: 리스크 상한, 레버리지/노출, 가격 제한, API 상태 확인
- 주문 후: 체결 상태 동기화, 미체결 추적, 이탈/스톱 이벤트 재검토
- 오작동 징후: 빈번한 재시도 실패, stop-loss 미반영, 동일 심볼 다중 청산 오판

### 10.3 문제 대응

- 알림 수신 즉시 이벤트 원인 분리: 데이터/계산/API/알림
- `git bisect` 이전 동작으로 되돌릴 수 있는지 사전 준비
- 장애 발생 시 영향 범위(종목/자산군/계좌) 즉시 확정

---

## 11. 백테스트/시뮬레이션 가이드

- 사용 구간: 기본 최근 2~3년 + 스트레스 구간(강한 변동성 구간)
- 핵심 지표: CAGR, max drawdown, Sharpe, hit ratio, turnover
- 검토 항목:
  - 전략별 기여도(System1/System2)
  - Inverse ETF 필터 기여(청산 개선 vs 거래비용)
  - 상관군 제한이 수익/위험에 미치는 영향
  - 비용/슬리피지 민감도
- 결과 문서화: 일자, 입력 데이터 버전, 파라미터, 사용 브랜치

---

## 12. 알림/모니터링 정책

### 12.1 이벤트 분류

- signal: 조건 성립 및 진입/청산 판단
- trade: 주문/체결/상태 전이
- error: API 실패, 데이터 누락, 예외
- risk: 상한 초과, 규칙 위반, 위험 급증

### 12.2 알림 규칙

- 실패성 알림은 채널 손실 없이 우선 전송
- 동일 이벤트 중복 노이즈 방지 위해 집계/디바운스 적용
- 장애 상황에서는 “조치 항목 + 대상 symbol + 즉시성”을 반드시 함께 발송

---

## 13. 코드 리뷰 관점 (CLAUDE 전용)

- 변경은 항상 다음 3개 축으로 리뷰:
  1. 전략 일관성(기준 규칙 훼손 여부)
  2. 리스크 안정성(한도/stop-loss/필터)
  3. 운영 회복력(재시도, 로깅, 알림)
- 회귀 가능성이 큰 포인트:
  - 멀티 포지션/멀티 심볼 처리
  - `position_id` 추적 정확성
  - 외부 API 응답 파싱 실패
  - 파일 경로/설정 로딩 실패(누락 키, YAML 스키마)

---

## 16. 연결 문서

- `research/readings/youtube/`
- `research/readings/blog/`
- `config/correlation_groups.yaml`
- `config/universe.yaml`

---

## 17. Claude 실행 힌트

- 트레이딩 로직 변경 제안 시 항상 백테스트/리스크 체크리스트를 먼저 보여줄 것
- 운영 이슈가 보이면 “재현 스텝 + 영향 범위 + 완화안” 형태로 제시
- 알림·체결·리스크 중 하나라도 불완전하면 우선순위를 높여 수정
- 추측성 최적화는 제안하지 않고, 코드·데이터·테스트 근거로만 조치

---
