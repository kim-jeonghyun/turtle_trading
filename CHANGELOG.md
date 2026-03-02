# Changelog

모든 주요 변경사항은 이 파일에 기록됩니다.

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/) 기반이며,
이 프로젝트는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

---

## [Unreleased]

### Changed
- supercronic v0.2.33 → v0.2.43 업그레이드: PID 1 fork exec 버그 수정 (aptible/supercronic#177)
- `docker-compose.yaml`에 `init: true` 추가 (defense-in-depth)

---

## [3.6.0] — 2026-02-28

장중 실시간 포지션 모니터링 — KIS API 기반 실시간 가격 조회, 스톱로스 장중 감지, P&L 알림 중복 방지.

### Added
- `src/spot_price.py`: `SpotPriceFetcher` — KIS API 실시간 가격 조회 (KR/US), CCXT (Crypto), yfinance fallback
- `src/monitor_state.py`: `MonitorState` — 알림 중복 방지 상태 관리 (스톱로스 1회 알림 + 가격 회복 리셋, P&L 쿨다운)
- `src/script_helpers.py`: `create_kis_client()` — KIS API 설정 팩토리 함수
- `scripts/monitor_positions.py`: 프로덕션 장중 모니터링 스크립트 (5분 cron, 파일 잠금, 타임아웃 보호)
- crontab: KR 장중 (09:00-15:25 KST) + US 장중 (22:00-06:25 KST, DST 양방향 커버) 5분 폴링
- 테스트 39개 추가 (test_spot_price 12개, test_monitor_state 12개, test_monitor_positions 15개)

### Changed
- `scripts/monitor_positions.py`: 프로토타입에서 프로덕션 리팩토링 — DataFetcher 일봉 → SpotPriceFetcher 실시간, 현재가 → 고/저가 스톱로스, 파일 잠금 추가
- `docker-compose.yaml`: healthcheck를 `pgrep -x supercronic`으로 변경, start_period 30s → 6m
- crontab: `TZ=Asia/Seoul` 명시 추가

---

## [3.5.0] — 2026-02-28

데이터 파이프라인 복원 & Docker 배포 준비 — 거래 기록 파이프라인 연결, 리스크 매니저 통합, Docker/cron 보강.

### Added
- PR #89: 3개 청산 경로(stop-loss/inverse-filter/exit-signal)에 `save_trade()` 파이프라인 연결
- PR #89: `_build_trade_record()` 헬퍼 — 16개 필드 포함 거래 기록 dict 생성
- PR #89: `save_trade()` 실패 시 try/except 에러 처리 (루프 중단 방지)
- PR #91: `src/script_helpers.py`에 통합 `setup_risk_manager()` 함수
- PR #91: `_GROUP_MAPPING` — `correlation_groups.yaml` 7개 그룹 명시적 매핑
- PR #91: regression guard 테스트 — YAML 그룹 ↔ 매핑 완전성 검증
- PR #92: Docker healthcheck (turtle-cron: 로그 수정시간, turtle-dashboard: Streamlit health)
- PR #92: Docker logging 제한 (max-size: 10m, max-file: 3)
- PR #92: cron 작업 8개 추가 (health_check, risk_limits, weekly_report, backup, 정리)
- 테스트 14개 추가 (save_trade 7개 + setup_risk_manager 7개)

### Fixed
- PR #89: `data/trades/`가 영원히 비어있는 문제 — `daily_report.py` 거래 통계 0건 해결
- PR #91: `us_tech`/`inverse` 그룹 누락으로 인한 리스크 그룹 오분류 해결
- PR #92: Dockerfile에 `app.py` COPY 누락 — dashboard 서비스 시작 실패 해결
- PR #92: `docker-compose.yaml` 미사용 named volumes 선언 제거

### Changed
- PR #91: `check_positions.py`, `check_risk_limits.py`, `weekly_report.py`의 로컬 `setup_risk_manager()` 제거 → `script_helpers` import로 교체
- PR #90: `config/notifications.yaml` → `config/notifications.yaml.example`로 이동 (코드 미사용 파일 정리)
- PR #90: `.env.example` 알림 환경변수 설명 보강

---

## [3.4.2] — 2026-02-26

`remove_position` 입력 검증 및 공유 상태 보호 패치.

### Fixed
- `remove_position` 과다 제거 시 공유 상태(group/direction/N exposure) 오염 방지 — 종목별 보유량 클램핑 적용
- `remove_position` 음수 `units`/`n_value` 입력 시 `ValueError` 가드 추가 (`add_position` 대칭)
- CHANGELOG v3.4.0 테스트 수 표기 수정 (12→21 → 12→24)

---

## [3.4.0] — 2026-02-26

인프라 강화 & 품질 게이팅 — Docker non-root 전환, mypy 전면 확대, CI 커버리지 게이팅.

### Added
- PR #63: `/release` 커맨드 — CHANGELOG/pyproject.toml 갱신 → PR → GitHub Release 자동화
- PR #63: `/security-fix` 커맨드 — 보안 계획 파일 기반 Wave별 일괄 수정 자동화
- PR #63: Docker cron non-root ADR 문서화
- PR #63: git-workflow.md에 `release/`, `security/` 브랜치 접두어 공식 추가
- PR #73: 버전 메타데이터 단일 원천 — `importlib.metadata` + `pyproject.toml` fallback
- PR #72: mypy baseline 21건→0건, CI strict 게이팅 활성화
- test_risk_manager.py 커버리지 89%→100% (12→24 테스트)
- CI 커버리지 threshold 80% 게이팅 (`--cov-fail-under=80`)
- `types-tabulate` 개발 의존성 추가

### Changed
- PR #71: Python 3.12 실행환경 정합성 확보 (`.python-version`, venv, CI 정렬)
- PR #74: Docker cron non-root 전환 — supercronic v0.2.33, `USER turtle`, entrypoint preflight
- mypy 적용 범위 `src/` → `src/ scripts/` 확대 (scripts/ 27건 타입 에러 해소)
- docker-compose.yaml 폐지 예정 `version` 키 제거

### Removed
- `pytest.ini` 삭제 — `pyproject.toml` 단일 설정으로 통합

---

## [3.3.1] — 2026-02-24

보안 리뷰 결과 반영 — SMTP SSL, KIS API 로그 마스킹, Discord URL 검증 강화.

### Security
- PR #60: 보안 리뷰 HIGH/MEDIUM 8건 수정 — SMTP SSL 컨텍스트, KIS API 로그 마스킹, Discord URL 검증
- PR #61: 보안 피드백 후속 개선 — Discord URL scheme/path 심화 검증, 운영 문서 보강

---

## [3.3.0] — 2026-02-24

Phase 2 완료 — 테스트 인프라, 타입 시스템, 코드 품질 전반 개선.

### Added
- PR #50: 테스트 유틸리티 conftest.py 승격 — 공통 fixture 중앙화
- PR #51: SerializableEnum(str, Enum) 베이스 클래스 도입 — JSON 직렬화 일관성 확보
- PR #52: health_check 테스트 환경 격리 — 외부 의존 없는 단위 테스트 보장
- PR #53: 알림 종목명 표시 개선 — 한국 종목 이름+코드 동시 표시
- PR #54: CHANGELOG.md 생성, 릴리즈 태그 규칙 수립 (v3.1.0, v3.2.0 소급 태깅)
- PR #55: Email 알림 채널 재시도 로직 추가 — `@retry_async` 데코레이터, SMTP timeout=10
- PR #56: `script_helpers.py` 모듈 추출 — 5개 스크립트 공통 알림 설정 중앙화
- PR #57: `Position` → `LivePosition` 리네이밍, `PositionSnapshot` Protocol 도입
- PR #58: README.md 전면 개정 — Phase 2 코드 변경사항 반영

---

## [3.2.1] — 2025-Q4

태그: `v3.2.1` (commit `ec37511`)

Phase 1 완료 이후 발견된 테스트 결함 및 수치 오류 핫픽스.

### Fixed
- PR #47: check_positions 통합 테스트 결함 5건 수정 — 스톱로스/청산 시나리오 엣지 케이스
- PR #49: Sortino ratio 계산 시 epsilon 가드 누락 수정 — ZeroDivisionError 방지

---

## [3.2.0] — 2025-Q4

태그: `v3.2.0` (commit `6aa9108`)

Phase 1 완료 — GitHub Flow 도입, 문서 정비, 브랜치 보호 규칙 활성화.

### Added
- PR #43: Branch Protection Rule 활성화 — 3계층 방어 체계 완성 (GitHub 서버 / 로컬 훅 / 행동 지침)
- PR #45: check_positions.py 통합 테스트 추가 — 커버리지 37% → 97% 달성

### Changed
- PR #41: 문서 정리 — 죽은 참조 제거, 버전 현행화, 중복 산출물 삭제
- PR #44: CLAUDE.md 최적화 및 운영 가이드 분리 (`docs/operations-guide.md`)

### Fixed
- PR #42: save_trade() 심볼 검증 강화 및 죽은 파일 참조 수정

---

## [3.1.0] — 2025-Q3

태그: `v3.1.0` (commit `b12fe86`)

핵심 리팩토링 — 전략 로직 전반의 타입 안전성 확보.

### Changed
- PR #11: Direction enum 마이그레이션 — 하드코딩 문자열 비교(`"LONG"`, `"SHORT"`) 전량 제거,
  `Direction.LONG` / `Direction.SHORT` Enum으로 교체
  - 영향 범위: `check_positions.py`, `position_tracker.py`, `risk_manager.py`, `auto_trader.py`

---

[Unreleased]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.5.0...HEAD
[3.5.0]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.4.2...v3.5.0
[3.4.2]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.4.1...v3.4.2
[3.4.1]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.4.0...v3.4.1
[3.4.0]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.3.1...v3.4.0
[3.3.1]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.3.0...v3.3.1
[3.3.0]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.2.1...v3.3.0
[3.2.1]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.2.0...v3.2.1
[3.2.0]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/kim-jeonghyun/turtle_trading/releases/tag/v3.1.0
