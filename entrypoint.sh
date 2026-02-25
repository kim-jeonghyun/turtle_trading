#!/bin/bash
set -e

# Preflight: bind mount 디렉토리 쓰기 권한 확인
for dir in /app/data /app/logs; do
  if [ ! -w "$dir" ]; then
    echo "FATAL: $dir is not writable by $(whoami) (UID $(id -u))" >&2
    echo "Fix: sudo chown -R $(id -u):$(id -g) $dir" >&2
    exit 1
  fi
done

exec "$@"
