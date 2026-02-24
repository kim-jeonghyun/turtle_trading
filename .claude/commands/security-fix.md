# 보안 수정 일괄 적용 커맨드

보안 계획 파일을 읽고 파일별 수정사항을 Wave별로 적용한 뒤, 테스트와 lint를 통과시킨다.

## 사용법

```
/security-fix [보안 계획 파일 경로]
```

기본값: `.omc/plans/security-fix-plan.md`

---

## 실행 단계

### 1단계: 인자 확인 및 계획 파일 로드

`$ARGUMENTS`가 비어 있으면 기본값 `.omc/plans/security-fix-plan.md`를 사용한다.
`PLAN_FILE` 변수에 경로를 저장한다.

계획 파일이 존재하지 않으면 즉시 중단하고 다음을 출력한다.

```
오류: 계획 파일을 찾을 수 없습니다: PLAN_FILE
사용법: /security-fix .omc/plans/security-fix-plan.md
```

계획 파일을 읽고 다음을 파싱한다.
- `## Implementation Steps` 섹션의 Wave 1 태스크 목록 (코드 변경)
- `## Implementation Steps` 섹션의 Wave 2 태스크 목록 (테스트 추가/수정)

파일 이름에서 확장자를 제외한 부분을 `PLAN_NAME`으로 저장한다.
예: `security-fix-plan.md` → `PLAN_NAME = security-fix-plan`

### 2단계: 보안 브랜치 생성

```bash
git checkout -b security/fix-PLAN_NAME
```

브랜치 생성 실패 시 (이미 존재하는 경우) 해당 브랜치로 전환한다.

```bash
git checkout security/fix-PLAN_NAME
```

### 3단계: Wave 1 — 코드 변경

계획 파일의 `### Wave 1` 섹션에 정의된 각 태스크를 순서대로 처리한다.

각 태스크마다:
1. 대상 파일 경로(`File:` 항목)를 확인한다.
2. 계획의 `# BEFORE` / `# AFTER` 코드 블록을 기준으로 실제 파일을 수정한다.
3. 수정 후 해당 파일에 lsp_diagnostics를 실행해 타입 오류가 없는지 확인한다.
4. 오류가 있으면 즉시 수정하고 다음 태스크로 진행한다.

> **주의**: 계획 파일(`.omc/plans/`)은 읽기 전용이다. 절대 수정하지 않는다.

### 4단계: Wave 2 — 테스트 추가/수정

Wave 1 완료 후, 계획 파일의 `### Wave 2` 섹션에 정의된 각 태스크를 처리한다.

각 태스크마다:
1. 대상 테스트 파일을 확인한다.
2. 계획에 명시된 테스트 케이스를 추가한다.
3. 기존 테스트를 깨지 않도록 주의한다.

### 5단계: 전체 테스트 실행

```bash
pytest -q
```

실패 시: 실패한 테스트를 분석하고 프로덕션 코드를 수정한다. 테스트 자체를 우회하거나 skip 처리하지 않는다.

모든 테스트가 통과할 때까지 Wave 1/2 수정을 반복한다.

### 6단계: Lint 확인

```bash
ruff check src/ scripts/ tests/
```

실패 시: ruff 지적 사항을 수정한다. `# noqa` 주석은 이유가 명확한 경우에만 허용한다.

### 7단계: (선택) Docker 빌드 확인

Dockerfile 또는 docker-compose.yaml 변경이 포함된 경우에만 실행한다.

```bash
docker build -t turtle-test . 2>&1 | tail -10
```

빌드 실패 시 오류 내용을 출력하고 수정 후 재시도한다.

### 8단계: 변경 요약 출력

```
## 보안 수정 완료 요약

브랜치: security/fix-PLAN_NAME
계획 파일: PLAN_FILE

### Wave 1: 코드 변경
- [v/x] <파일 경로> — <태스크 요약>
  ...

### Wave 2: 테스트
- [v/x] <파일 경로> — <태스크 요약>
  ...

### 검증
- pytest: PASS / FAIL (실패 N건)
- ruff: PASS / FAIL
- docker build: PASS / FAIL / SKIP

다음 단계:
  git add <수정된 파일들>
  git commit -m "[security] 보안 수정 적용 — PLAN_NAME"
  git push -u origin security/fix-PLAN_NAME
  gh pr create ...
```

---

## 오류 처리 원칙

- 각 단계에서 명령이 실패하면 즉시 중단하고 실패한 단계와 오류 내용을 출력한다.
- 테스트 실패는 프로덕션 코드 버그의 신호로 처리한다. 테스트를 수정해 통과시키지 않는다.
- 민감 정보(API 키, 시크릿, 토큰)를 로그, 코드, 커밋에 노출하지 않는다.
- 커밋과 PR은 이 커맨드가 자동 생성하지 않는다. 요약 출력 후 사용자가 직접 검토하고 진행한다.
