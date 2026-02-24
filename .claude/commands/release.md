# 릴리즈 자동화 스킬

새 버전을 릴리즈한다. 버전 번호는 인자로 받는다.

## 사용법

```
/release 3.4.0
```

## 전제 조건

- 작업 전 `main` 브랜치가 최신 상태인지 확인한다.
- `$ARGUMENTS`에 버전 번호(예: `3.4.0`)가 포함되어 있어야 한다.

---

## 실행 단계

### 1단계: 인자 확인 및 검증

`$ARGUMENTS`가 비어 있으면 즉시 중단하고 다음 메시지를 출력한다.

```
오류: 버전 번호가 필요합니다.
사용법: /release 3.4.0
```

버전 번호를 `VERSION` 변수로 저장한다. 오늘 날짜를 `YYYY-MM-DD` 형식으로 `TODAY` 변수로 저장한다.

**형식 검증:** `VERSION`이 `X.Y.Z` 형식(숫자.숫자.숫자)이 아니면 즉시 중단한다.

```
오류: 버전 형식이 올바르지 않습니다. 형식: X.Y.Z (예: 3.4.0)
```

**중복 검증:** 원격 태그를 동기화한 뒤 중복을 확인한다.

```bash
git fetch --tags
git tag -l "vVERSION"
```

태그가 이미 존재하면 즉시 중단한다.

```
오류: 태그 vVERSION이 이미 존재합니다. 이미 릴리즈된 버전입니다.
```

### 2단계: CHANGELOG.md — [Unreleased] 섹션 존재 확인

`CHANGELOG.md`를 읽는다.

- `## [Unreleased]` 헤더가 없으면 중단하고 다음을 출력한다.
  ```
  오류: CHANGELOG.md에 [Unreleased] 섹션이 없습니다.
  릴리즈할 변경사항을 먼저 [Unreleased] 섹션에 기록하세요.
  ```
- `## [Unreleased]` 헤더 아래에 실제 내용(Added/Changed/Fixed/Removed/Security 등)이 한 줄 이상 없으면 중단하고 다음을 출력한다.
  ```
  오류: [Unreleased] 섹션이 비어 있습니다.
  릴리즈할 변경사항을 먼저 기록하세요.
  ```

### 3단계: CHANGELOG.md 수정

다음 세 가지를 수행한다.

**3-1. [Unreleased] 헤더 교체**

```
## [Unreleased]
```
를 아래 두 줄로 교체한다.

```
## [Unreleased]

---

## [VERSION] — TODAY
```

여기서 `VERSION`과 `TODAY`는 1단계에서 저장한 실제 값으로 대체한다.

**3-2. 비교 링크 추가**

파일 맨 아래의 비교 링크 블록을 찾는다. 현재 최신 버전(직전 릴리즈)을 `PREV_VERSION`으로 식별한다.

기존 링크 블록 맨 위에 다음 줄을 추가한다.

```
[VERSION]: https://github.com/kim-jeonghyun/turtle_trading/compare/vPREV_VERSION...vVERSION
```

`VERSION`과 `PREV_VERSION`은 실제 값으로 대체한다.

**3-3. 파일 저장**

수정된 내용을 `CHANGELOG.md`에 저장한다.

### 4단계: pyproject.toml 버전 갱신

`pyproject.toml`을 열어 `version = "..."` 줄을 찾아 `VERSION` 값으로 교체한다.

```toml
version = "VERSION"
```

파일을 저장한다.

### 5단계: 변경 내용 검토

수정된 두 파일의 diff를 출력하고, 사용자에게 확인을 요청한다.

```
다음 변경사항을 릴리즈합니다:

[CHANGELOG.md diff 요약]
[pyproject.toml diff 요약]

계속 진행하려면 'y'를 입력하세요.
```

사용자가 'y' 또는 'yes'를 입력하지 않으면 중단하고 "릴리즈가 취소되었습니다."를 출력한다.

### 6단계: main 동기화 및 릴리즈 브랜치 생성

먼저 main이 최신 상태이고 작업 트리가 깨끗한지 확인한다.

```bash
git checkout main
git pull --ff-only
git status --porcelain
```

`git status --porcelain` 출력이 비어있지 않으면 중단한다.

```
오류: 작업 트리에 커밋되지 않은 변경사항이 있습니다. 정리 후 다시 시도하세요.
```

릴리즈 브랜치를 생성하고 커밋한다.

```bash
git checkout -b release/vVERSION
git add CHANGELOG.md pyproject.toml
git commit -m "[release] Release vVERSION"
git push -u origin release/vVERSION
```

### 7단계: PR 생성

```bash
gh pr create \
  --title "Release vVERSION" \
  --body "## Release vVERSION — TODAY

CHANGELOG.md의 [Unreleased] 섹션을 [VERSION]으로 전환하고 pyproject.toml 버전을 갱신합니다.

### 변경 파일
- \`CHANGELOG.md\`: [Unreleased] → [VERSION] 전환, 비교 링크 추가
- \`pyproject.toml\`: version → VERSION

Fixes #NNN (릴리즈 이슈가 있는 경우 번호를 대체한다. 없으면 이 줄을 제거한다.)

### 체크리스트
- [x] CHANGELOG.md [Unreleased] 내용 확인
- [x] 버전 번호 Semantic Versioning 준수 확인
- [x] pyproject.toml 버전 일치 확인" \
  --base main
```

PR URL을 출력한다.

### 8단계: CI 통과 대기 및 merge

```bash
gh pr checks --watch
```

모든 CI 체크가 통과하면:

```bash
gh pr merge --squash --delete-branch
```

merge 실패 시 중단하고 PR URL과 함께 다음을 출력한다.

```
오류: PR merge에 실패했습니다.
PR을 수동으로 확인하세요: [PR URL]
```

### 9단계: main 동기화 및 태그 확인

```bash
git checkout main
git pull origin main
git fetch --tags
```

### 10단계: GitHub 릴리즈 생성

CHANGELOG.md에서 `## [VERSION]` 헤더와 다음 `## [` 헤더 사이의 내용을 추출해 `RELEASE_NOTES` 변수에 저장한다. 헤더 줄 자체(`## [VERSION] — TODAY`)와 구분선(`---`)은 제외한다.

추출한 내용을 릴리즈 노트로 사용한다.

```bash
gh release create vVERSION \
  --title "vVERSION" \
  --notes "$RELEASE_NOTES"
```

릴리즈 URL을 출력한다.

---

## 완료 메시지

```
릴리즈 완료: vVERSION (TODAY)
- CHANGELOG.md: [VERSION] 섹션 생성 완료
- pyproject.toml: version = "VERSION"
- GitHub Release: [릴리즈 URL]
```

## 오류 처리 원칙

- 각 단계에서 명령이 실패하면 즉시 중단하고 실패한 단계와 오류 내용을 출력한다.
- `git push` 또는 `gh` 명령 실패 시 브랜치/PR 상태를 함께 출력한다.
- CI 실패 시 실패한 체크 이름과 로그 URL을 출력한다.
