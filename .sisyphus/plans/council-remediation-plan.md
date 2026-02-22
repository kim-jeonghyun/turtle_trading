# Council Remediation Plan: v3.2.1 마감 및 v3.3.0 후속 조치

**Status:** Phase 1 완료 + 릴리즈 게이트 완료, Phase 2 대기
**Version:** 1.3
**Created:** 2026-02-22
**Updated:** 2026-02-22 (릴리즈 게이트 조건 충족: 롤백 문서, 사전 검증, 배포 스크립트)
**Context:** Agent Council 4위원 만장일치 CONDITIONAL APPROVE → 조건 충족을 위한 실행 계획

---

## 변경 이력

| 버전 | 변경 내용 |
|------|-----------|
| 1.0 | 초안 작성 |
| 1.1 | Council 피드백 반영: crontab 전환 검증 체크리스트 추가, 알림 채널 회귀 대응, KR 중복 시그널 방침, Task 2.1 3단계 분할 + 롤백 기준, 오픈 이슈 트리아지 |
| 1.2 | Phase 1 실행 완료: PR #32-34 머지, signal_check.py 삭제, Issue #29 수정, Issue #6 분할(→#35), v3.2.1 마일스톤 마감. Post-deployment 체크리스트에 Docker 재빌드 단계 추가. |
| 1.3 | 릴리즈 게이트 완료: 롤백 절차서 작성, 사전 배포 검증 실행 (655 passed, ruff clean, signal_check 0건), 배포 스크립트 생성. Council Review: CONDITIONAL APPROVE (4.0/5.0). |

---

## 배경

Agent Council이 PR #32 머지와 v3.2.1 마감에 대해 3가지 조건부 승인 조건을 제시:

1. **signal_check.py가 crontab에서 System 1 필터 없이 활성 실행 중** — v3.2.1이 수정한 버그(#4)가 이 스크립트에는 여전히 존재
2. **Issue #29 (`_find_matching_fill()` 시간 필터)** — critical 라벨이지만 v3.2.1에 미할당
3. **`_run_checks()` 통합 테스트 부재** — check_positions.py 커버리지 37%

---

## Phase 1: v3.2.1 마감 조건 충족 — ✅ 완료

### Task 1.1: PR #32 수정 및 머지 — ✅ 완료

**PR:** #32 → MERGED
**작업 완료:**
- PR #32 본문에서 `Fixes #6` → `Ref #6` 변경 완료
- PR #32에 milestone `v3.2.1` 태그 추가 완료
- PR #32 머지 완료

---

### Task 1.2: signal_check.py 완전 삭제 및 crontab 전환 — ✅ 완료

**PR:** #33 → MERGED
**브랜치:** `chore/remove-deprecated-signal-check`

**변경 파일:**

| 파일 | 변경 내용 | 상태 |
|------|-----------|------|
| `scripts/signal_check.py` | **삭제** | ✅ |
| `crontab` (lines 10, 13) | signal_check.py → check_positions.py로 교체 | ✅ |
| `CLAUDE.md` (line 120) | scripts 테이블에서 signal_check.py 행 제거 | ✅ |
| `CLAUDE.md` (line 167) | 실행 명령에서 signal_check.py → check_positions.py | ✅ |
| `README.md` (line 57) | 시그널 체크 명령 갱신 | ✅ |
| `README.md` (line 87) | 프로젝트 구조 트리에서 제거 | ✅ |
| `scripts/README.md` (line 342) | 잘못된 참조 수정/제거 | ✅ |

#### Task 1.2.1: 알림 채널 동등성 확인 — ✅ 완료

**결과:** `artifacts/task-1.2.1-notifier-audit.json`
- 운영 환경: Telegram-only
- Discord/Email: check_positions.py 미설정, signal_check.py에서만 코드 존재했으나 운영 미사용 확인
- 회귀 리스크: 없음 (현재 Telegram-only 운영)

#### Task 1.2.2: KR 중복 시그널 방침 — ✅ 완료

**채택 방침:** 옵션 B (중복 허용, 문서화)
- 모니터링 템플릿: `logs/phase1-task1.2.2-kr-duplication.md`
- crontab 주석에 중복 설명 추가 완료
- v3.3.0에서 `--market` CLI 인자로 해소 예정

#### Task 1.2.3: Crontab 전환 검증 체크리스트

**Pre-deployment (crontab 변경 전):**
- [ ] 심볼 유니버스 동등성 확인: `data/turtle_universe_full.csv` vs `config/universe.yaml`
- [ ] 알림 채널 동등성 확인 (Task 1.2.1) ✅
- [ ] Dry-run (16:00 KST 시뮬레이션): KR 처리, US 스킵 확인
- [ ] Dry-run (07:00 KST 시뮬레이션): US 처리 확인 + KR 재처리 확인
- [ ] 포지션 파일 백업: `data/positions/positions.json`
- [ ] 파일 잠금 테스트: 동시 실행 시 두 번째 인스턴스가 차단되는지 확인
- [ ] 사전 증적 보관: 각 dry-run/점검 항목의 실행 커맨드·로그/결과 스냅샷 저장

**권장 증적 형식(예시):**
- `artifacts/task1.2.3-precheck.txt`
- 항목: 실행일시/타임존/KST, 실행 명령, `grep` 핵심 로그(필수 패턴 4개), 처리 심볼 수, 건너뛴 심볼 수

**기준 패턴(필수 로그 키워드):**
- `signal_check` 문자열 미출현
- `check completed` 또는 동등 문구
- `positions snapshot` 로드/저장
- lock file 획득/해제 메시지

**crontab 변경 내용 (적용 완료):**
```
# 한국 시장 시그널+포지션 체크 (장 마감 후 16:00)
0 16 * * 1-5 cd /app && python scripts/check_positions.py >> /app/logs/check_kr.log 2>&1

# 미국 시장 시그널+포지션 체크 (한국시간 07:00)
# NOTE: KR 심볼도 재처리됨 (should_check_signals 통과). 무해 — v3.3.0에서 --market 인자로 분리 예정
0 7 * * 2-6 cd /app && python scripts/check_positions.py >> /app/logs/check_us.log 2>&1
```

**Post-deployment (첫 1주 모니터링):**
- [ ] Docker 이미지 재빌드: `docker build -t turtle-trading .` && `docker-compose up -d turtle-cron`
- [ ] 첫 KR 실행 (16:00) 로그 확인: KR 심볼 처리, US 스킵, "체크 완료" 확인
- [ ] 첫 US 실행 (07:00) 로그 확인: US 심볼 처리 확인
- [ ] Telegram 알림 수신 확인 (KR/US 각각)
- [ ] 수동 Donchian 채널 계산과 시그널 대조 (2-3 종목)
- [ ] `grep -r "signal_check" .` 결과 0건 확인 (backup 제외)
- [ ] 전체 테스트 통과 (`pytest`)
- [ ] ruff lint 통과

---

### Task 1.3: Issue #29 해결 — `_find_matching_fill()` 시간 필터 — ✅ 완료

**PR:** #34 → MERGED (Fixes #29)
**브랜치:** `bugfix/issue-29-fill-time-filter`

**구현 내용:**
- `_find_matching_fill()` 메서드에 `ord_tmd` 기반 시간 필터 추가
- `_extract_hhmmss()` 헬퍼 추가: ISO timestamp → HHMMSS 변환
- 하위 호환: `ord_tmd` 누락/빈 값/비정상 길이 시 기존 동작 유지
- 경계값(동일 시각) 매칭 허용

**테스트:** 17건 추가
- `TestExtractHhmmss` (7건): HHMMSS 변환 단위 테스트
- `TestFindMatchingFillTimeFilter` (10건): 시간 필터 통합 테스트 (피라미딩 시나리오 포함)

---

### Task 1.4: Issue #29를 v3.2.1 마일스톤에 배정 — ✅ 완료

---

### Task 1.5: Issue #6 분할 — 후속 이슈 생성 — ✅ 완료

**완료 내용:**
- Issue #6에 PR #32, #33 완료 코멘트 추가
- Issue #6 닫기 (핵심 acceptance criteria 충족)
- 후속 이슈 #35 생성: `[#6 후속] check_positions.py _run_checks() 통합 테스트 추가 (커버리지 80%)`
  - 마일스톤: v3.3.0
  - 라벨: enhancement

---

### Task 1.6: v3.2.1 마일스톤 마감 — ✅ 완료

- v3.2.1 마일스톤 내 모든 이슈 CLOSED 확인 (9/9)
- 마일스톤 닫기 완료

---

## Phase 1 실행 결과 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| PR #32 머지 | ✅ | 45개 테스트 추가 |
| PR #33 머지 | ✅ | signal_check.py 삭제, crontab 전환 |
| PR #34 머지 | ✅ | Issue #29 시간 필터 수정, 17개 테스트 추가 |
| signal_check.py 삭제 | ✅ | `grep -r "signal_check"` 0건 |
| 알림 채널 감사 | ✅ | Telegram-only 확인 |
| Issue #6 닫기 | ✅ | 후속 #35 생성 |
| Issue #29 닫기 | ✅ | Fixes #29 자동 닫기 |
| v3.2.1 마일스톤 마감 | ✅ | 9/9 이슈 CLOSED |
| 전체 테스트 | ✅ | 655 passed, 0 failed |
| 배포 환경 | Docker (Linux cron) | launchd/systemd 불필요 |

---

## Phase 2: v3.3.0 코드 품질 개선 — 대기

### Task 2.1: check_positions.py 커버리지 80% 달성 (3단계)

**이슈:** #35
**예상 기간:** 4-6 working days

#### 3단계 분할 + 게이트 기준

| 단계 | 대상 | 테스트 수 | 목표 커버리지 | 기간 | 게이트 |
|------|------|----------|-------------|------|--------|
| **2.1.A** | Setup 함수 + 유틸리티 | 16 | 37% → 55% | 1-2일 | 50% 미달 시 원인 분석 |
| **2.1.B** | `_run_checks()` Happy path | 6 | 55% → 70% | 1.5-2일 | 65% 미달 시 폴백 전략 |
| **2.1.C** | Edge cases + 마무리 | 6-8 | 70% → 80%+ | 1-1.5일 | 최종 검증 |

#### Task 2.1 최종 승인 기준

- **중간 게이트 수용(진행 허용):**
  - 2.1.A 커버리지 ≥ 50%
  - 2.1.B 커버리지 ≥ 65%
  - 2.1.C 병목 1개 이하, 장애도 점검 통과
- **최종 완료(목표):**
  - 2.1.C 포함 커버리지 ≥ 80%
  - 크리티컬/높은 중요도 회귀 0건
  - CI 안정성(연속 실행 3회 pass)
- **조건부 수용(예외 허용, 관리 승인 필요):**
  - 커버리지 65~79% 구간에서 1~2개 비핵심 엣지 테스트 미달 시, 이슈로 분해해 7일 내 remediation 의무화

#### 롤백 기준

| 시점 | 조건 | 조치 |
|------|------|------|
| 2.1.A 완료 후 | 커버리지 < 50% | 원인 분석 — patch 경로 오류 가능 |
| 2.1.B 완료 후 | 커버리지 < 65% | **폴백**: `_run_checks()`를 의존성 주입 방식으로 리팩터링 후 재시도 |
| 2.1.B 진행 중 | patch 10개 이상 + 테스트 불안정 | **폴백**: `CheckRunner` 클래스 추출 + DI 방식 전환 |
| 최종 | 커버리지 65-79% | **수용 가능** — 65%는 운영 오케스트레이션 happy path 포함 |

---

### Task 2.2: Sortino ratio epsilon 수정

**변경:** `src/analytics.py` — `if downside_std == 0:` → `if downside_std < 1e-10:`
**예상 규모:** 1줄 코드 + 3줄 테스트

---

### Task 2.3: check_stop_loss() Direction Enum 가드

**의존:** Issue #11 (Direction enum 전환) 완료 후 진행

---

### Task 2.4: `--market` CLI 인자 추가

**목적:** crontab에서 KR/US 실행을 명시적으로 분리하여 중복 시그널 제거

---

## 위험 및 완화 조치

| 위험 | 영향 | 확률 | 완화 | 상태 |
|------|------|------|------|------|
| crontab 전환 시 시그널 누락 | 매매 기회 손실 | 중 | Task 1.2.3 체크리스트로 사전 검증 | 코드 완료, 배포 전 검증 대기 |
| 알림 채널 회귀 (Discord/Email 누락) | 운영자 알림 미수신 | 중 | Task 1.2.1에서 Telegram-only 확인 | ✅ 해소 |
| 07:00 실행 시 KR 중복 시그널 | 알림 노이즈 | 높 | v3.2.1 한시 허용 + 모니터링, v3.3.0에서 --market 해소 | 모니터링 중 |
| _find_matching_fill 시간 비교 시 타임존 불일치 | false negative | 저 | KIS API ord_tmd는 KST 고정, record.timestamp도 KST 통일 확인 | ✅ 해소 |
| _run_checks() 모킹 복잡성 | 테스트 불안정 | 중 | 공유 fixture로 중앙화, 65% 최소 수용 기준 설정 | Phase 2 대기 |
| Task 2.1 일정 초과 | Phase 2 지연 | 중 | 3단계 분할 + 게이트로 조기 감지 | Phase 2 대기 |

---

## 오픈 이슈 트리아지

| # | 라이브 차단? | 근거 | 상태 |
|---|-------------|------|------|
| 6 | **예** | 시그널 스크립트 테스트 부재 | ✅ CLOSED |
| 29 | **예** | 피라미딩 fill 매칭 오류 가능 | ✅ CLOSED |
| 30 | 아니오 | `save_trade()`는 로깅 전용 | OPEN |
| 31 | 아니오 | `health_check`는 진단 도구 | OPEN |
| 35 | 아니오 | 커버리지 향상 (v3.3.0) | OPEN (후속) |

**결론:** 라이브 차단 이슈 #6, #29 모두 Phase 1에서 해결 완료.

---

## 성공 기준

### Phase 1 완료 기준 — ✅ 전체 충족
- [x] PR #32 머지 완료
- [x] signal_check.py 삭제 PR 머지 완료
- [x] 알림 채널 동등성 확인 완료 (Task 1.2.1)
- [x] `grep -r "signal_check" .` 결과 0건 (backup 제외)
- [x] Issue #29 PR 머지 완료, acceptance criteria 충족
- [x] Issue #6, #29 모두 CLOSED
- [x] v3.2.1 마일스톤 모든 이슈 CLOSED (9/9)
- [x] 전체 테스트 통과 (655 tests)
- [x] crontab 전환 검증 체크리스트 (Task 1.2.3) — 사전 배포 검증 완료 (`artifacts/task-1.2.3-precheck.md`)
- [x] 롤백 절차서 작성 (`.sisyphus/reviews/v3.2.1-rollback-procedure.md`)
- [x] 배포 스크립트 준비 (`scripts/deploy-v3.2.1.sh`)
- [ ] Docker 데몬 실행 후 실제 빌드/태깅 (`bash scripts/deploy-v3.2.1.sh`)

### Phase 2 완료 기준 — 대기
- [ ] check_positions.py 커버리지: ≥80% (목표) 또는 ≥65% + 조건부 수용
- [ ] Sortino ratio epsilon 수정 완료
- [ ] (Issue #11 완료 후) Direction Enum 가드 적용
- [ ] `--market` CLI 인자 추가 완료
