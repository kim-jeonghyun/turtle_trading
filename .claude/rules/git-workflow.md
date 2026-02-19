# GitHub Flow 워크플로우 규칙

## 핵심 원칙
- main은 항상 배포 가능한 상태 유지
- 모든 변경은 feature 브랜치 → PR → CI 통과 → merge
- Issue가 모든 작업의 출발점

## 브랜치 네이밍
- feature/issue-NNN-<설명>: 신규 기능
- bugfix/issue-NNN-<설명>: 버그 수정
- hotfix/<설명>: 긴급 수정

## 커밋 메시지 형식
[#NNN] 제목 (50자 이내)

선택적 본문: 무엇을, 왜 변경했는지

## PR 필수 조건
1. PR 본문에 Fixes #NNN 포함 (이슈 자동 닫기)
2. CI 통과 (lint + type check + test)
3. PR 템플릿 체크리스트 완료

## 금지 사항
- main에 직접 commit/push
- force push, rebase -i
- .env/credentials 커밋
- 테스트 없는 코드 변경
