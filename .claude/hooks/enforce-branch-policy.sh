#!/bin/bash
# main 브랜치에 직접 commit/push 차단
# Exit 2 = 차단 (Claude에게 피드백 전달)
# rev.3: git push origin (브랜치 미명시) 우회 경로 차단

INPUT=$(cat)

# rev.1 ISSUE 3: jq 없을 때 python3 fallback
if command -v jq &>/dev/null; then
  COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
else
  COMMAND=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null || echo "")
fi

[ -z "$COMMAND" ] && exit 0

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# 1. main에서 git commit 차단 (체이닝 포함: git add . && git commit)
if echo "$COMMAND" | grep -qE '\bgit\s+commit\b'; then
  if [ "$BRANCH" = "main" ]; then
    echo "BLOCKED: main 브랜치에 직접 커밋 금지. feature 브랜치를 먼저 생성하세요." >&2
    echo "사용법: git checkout -b feature/issue-NNN-<설명>" >&2
    exit 2
  fi
fi

# 2. git push --all / --mirror 차단 (모든 브랜치 일괄 push → main 포함 위험)
#    rev.4 Momus 리뷰: feature 브랜치에서도 --all/--mirror로 main 우회 가능
if echo "$COMMAND" | grep -qE '\bgit\s+push\b.*--(all|mirror)\b'; then
  echo "BLOCKED: git push --all/--mirror 금지. 개별 브랜치를 명시하여 push하세요." >&2
  echo "허용: git push origin feature/issue-NNN-<설명>" >&2
  exit 2
fi

# 3. git push --force 계열 차단 (main/feature 공통)
if echo "$COMMAND" | grep -qE '\bgit\s+push\b.*\s(--force-with-lease|--force|-f)\b'; then
  echo "BLOCKED: git push --force 계열 금지. 강제 push 없이 개별 브랜치로 안전하게 push하세요." >&2
  echo "허용: git push origin feature/issue-NNN-<설명>" >&2
  exit 2
fi

# 4. git push ... main 명시 차단 (어떤 브랜치에서든)
if echo "$COMMAND" | grep -qE '\bgit\s+push\b.*\bmain\b'; then
  echo "BLOCKED: main 브랜치에 직접 push 금지. PR을 통해 병합하세요." >&2
  exit 2
fi

# 5. main에서 git push (브랜치 미명시 포함) 전면 차단
#    rev.2 ISSUE 4: git push origin, git push, git push -u origin 등 모두 커버
if echo "$COMMAND" | grep -qE '\bgit\s+push\b'; then
  if [ "$BRANCH" = "main" ]; then
    echo "BLOCKED: main 브랜치에서 push 금지. feature 브랜치에서 작업하세요." >&2
    echo "허용: git push origin feature/issue-NNN-<설명>" >&2
    exit 2
  fi
fi

exit 0
