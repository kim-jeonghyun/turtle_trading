# Changelog

모든 주요 변경사항은 이 파일에 기록됩니다.

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/) 기반이며,
이 프로젝트는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

---

## [Unreleased] — v3.3.0 (Phase 2 진행 중)

### Added
- PR #50: 테스트 유틸리티 conftest.py 승격 — 공통 fixture 중앙화
- PR #51: SerializableEnum(str, Enum) 베이스 클래스 도입 — JSON 직렬화 일관성 확보
- PR #52: health_check 테스트 환경 격리 — 외부 의존 없는 단위 테스트 보장
- PR #53: 알림 종목명 표시 개선 — 한국 종목 이름+코드 동시 표시

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

[Unreleased]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.2.1...HEAD
[3.2.1]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.2.0...v3.2.1
[3.2.0]: https://github.com/kim-jeonghyun/turtle_trading/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/kim-jeonghyun/turtle_trading/releases/tag/v3.1.0
