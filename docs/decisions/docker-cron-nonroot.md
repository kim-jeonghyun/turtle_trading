# ADR: Docker Cron Non-Root 실행

## 상태: Accepted

- 구현일: 2026-02-25
- 적용 버전: supercronic v0.2.43

---

## 컨텍스트

현재 `Dockerfile`에서 cron 데몬은 root로 실행된다 (`CMD ["cron", "-f"]`). 데이터 디렉토리와 로그 디렉토리는 `turtle` 유저 소유로 설정되어 있지만, cron 프로세스 자체는 root 권한을 요구한다.

```dockerfile
# 기본 명령어 (cron requires root — data dirs owned by turtle)
CMD ["cron", "-f"]
```

이 구성은 보안 리뷰에서 MEDIUM 이슈로 지적되었다. cron 데몬 특성상 non-root 실행이 기술적으로 제약되어 이슈가 보류된 상태다.

**현재 운영 환경:**
- 1인 개발 프로젝트
- 로컬 및 개발 환경 위주 사용
- 실거래는 미도입 (단계적 승인 대기)
- `python:3.12-slim` 기반 Docker 컨테이너

---

## 결정

**supercronic v0.2.43으로 전환하여 non-root 실행을 구현한다.**

근거:
1. 실거래 도입 전 인프라 보안 강화의 필수 항목으로 등록되어 있었다.
2. supercronic은 Kubernetes 생태계에서 검증된 경량 cron 대체 바이너리로, non-root 실행이 기본 지원된다.
3. 표준 crontab 문법을 그대로 사용하므로 기존 crontab 자산을 재활용할 수 있다.
4. 단일 바이너리로 apt 패키지 의존 없이 설치 가능하며, TARGETARCH를 통해 amd64/arm64 멀티아키텍처를 지원한다.
5. SHA1 체크섬 검증으로 바이너리 무결성을 보장한다.

---

## 대안

### 1. supercronic (채택)

**설명:** Kubernetes 생태계에서 검증된 경량 cron 대체 바이너리. non-root로 동작하며 표준 crontab 문법을 그대로 사용한다.

**장점:**
- non-root 실행 가능 (핵심 요구사항 충족)
- 표준 crontab 문법 그대로 사용 — 기존 `/etc/cron.d/turtle-cron` 재사용 가능
- 단일 바이너리, `python:3.12-slim` 기반 이미지에서 apt 설치 없이 동작 가능
- stdout/stderr 로그 출력 (Docker 로그 수집 친화적)
- 활발한 유지보수 (https://github.com/aptible/supercronic)

**단점:**
- apt `cron` 패키지 교체 필요 → Dockerfile 수정
- 동작 검증 필요 (특히 환경변수 전달 방식 확인)

**전환 난이도:** 낮음. Dockerfile에서 `cron` 설치 제거 후 supercronic 바이너리 추가, `CMD` 교체만 필요.

```dockerfile
# 전환 예시
ARG SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.43/supercronic-linux-amd64
RUN curl -fsSLo /usr/local/bin/supercronic "$SUPERCRONIC_URL" && chmod +x /usr/local/bin/supercronic

USER turtle
CMD ["supercronic", "/etc/cron.d/turtle-cron"]
```

### 2. Python APScheduler (코드 내장 스케줄러)

**설명:** Python 프로세스 내부에서 스케줄을 관리하는 라이브러리. `check_positions.py`, `daily_report.py` 등을 단일 프로세스로 통합 실행.

**장점:**
- non-root 실행 당연히 가능
- cron 데몬 불필요 — `apt install cron` 제거로 이미지 경량화
- Python 코드로 스케줄 관리 (타입 안전, 테스트 가능)
- 실패 시 예외 처리 및 알림 통합이 용이

**단점:**
- 현재 스크립트 구조를 APScheduler 진입점으로 리팩토링 필요 (중간 규모 변경)
- 프로세스 충돌 시 모든 스케줄이 동시 중단
- 기존 crontab 문법 자산 폐기

**결론:** 장기적으로 고려할 만하지만 현재 단계에서는 변경 범위가 과도하다.

### 3. systemd timer

**설명:** systemd unit 파일로 주기적 작업을 관리.

**단점:**
- Docker 컨테이너 내부에서 systemd를 실행하는 것은 비표준이며 `--privileged` 또는 복잡한 설정 필요
- 실질적으로 비현실적

**결론:** 기각.

### 4. gosu/su-exec로 개별 작업만 non-root 실행

**설명:** cron 데몬은 root로 유지하되, crontab 각 항목에서 `gosu turtle python ...` 형태로 실제 작업을 non-root로 실행.

**장점:**
- Dockerfile 변경 최소화
- 작업 프로세스 자체는 non-root

**단점:**
- cron 데몬 자체는 여전히 root → 이슈의 근본 해결 아님
- 각 crontab 항목마다 `gosu` 래핑 필요 — 관리 복잡도 증가
- `gosu` 추가 설치 필요

**결론:** 근본 해결책이 아니므로 기각. supercronic이 더 나은 해결책.

---

## 결과

### 구현 내역 (2026-02-25)

- `Dockerfile`: apt `cron` 제거, `curl` 추가, supercronic v0.2.43 설치 (SHA1 체크섬 검증, TARGETARCH 멀티아키텍처)
- `Dockerfile`: TARGETARCH를 `dpkg --print-architecture` fallback으로 안전화 (docker build 시 TARGETARCH 미설정 대비)
- `Dockerfile`: turtle UID/GID 1000 고정 (`groupadd --gid 1000`, `useradd --uid 1000 --gid 1000`) — 호스트 bind mount 소유권과 일관성 확보, `docker-compose.yaml`에서 `DOCKER_UID`/`DOCKER_GID` 환경변수로 오버라이드 가능
- `entrypoint.sh`: preflight check로 `/app/data`, `/app/logs` 디렉토리의 쓰기 권한을 컨테이너 시작 시 즉시 검증 — 권한 불일치 시 명확한 에러 메시지와 함께 즉시 종료하여 런타임 권한 오류 사전 차단
- 크론탭 경로: `/etc/cron.d/turtle-cron` → `/app/crontab`으로 단순화
- `USER turtle` + `CMD ["supercronic", "/app/crontab"]`로 non-root 실행
- `ENV PYTHONPATH=/app` 명시 추가
- `docker-compose.yaml`: `user: "${DOCKER_UID:-1000}:${DOCKER_GID:-1000}"`으로 유연한 UID/GID 매핑

### v0.2.43 업그레이드 (2026-03-02)

- **원인**: v0.2.33의 reaper가 PID 1 환경에서 `os.Args[0]` (bare name)으로 `syscall.ForkExec`를 호출하여 "Failed to fork exec: no such file or directory" fatal 에러 발생 (aptible/supercronic#177)
- **수정**: supercronic v0.2.33 → v0.2.43 업그레이드 (v0.2.36에서 `os.Executable()` 절대 경로로 수정됨)
- **추가 방어**: `docker-compose.yaml`에 `init: true` 추가 (tini가 PID 1, supercronic은 PID >1로 실행)

### 롤백 절차 (긴급 시)

1. Dockerfile에서 `cron` 패키지 재설치, supercronic 설치 블록 제거
2. `COPY crontab /etc/cron.d/turtle-cron` + `RUN crontab /etc/cron.d/turtle-cron`으로 복원
3. `USER turtle` 제거, `CMD ["cron", "-f"]`로 복원
4. `docker-compose build && docker-compose up -d`

### 관련 파일

- `Dockerfile` — supercronic 설치 및 non-root 실행 설정
- `entrypoint.sh` — bind mount 쓰기 권한 preflight check
- `crontab` — 스케줄 정의 (프로젝트 루트, Docker 내 `/app/crontab`으로 복사됨)
- `docker-compose.yaml` — `user: "${DOCKER_UID:-1000}:${DOCKER_GID:-1000}"` 유연한 UID/GID 매핑
- `scripts/` — cron이 호출하는 스크립트들

---

*작성일: 2026-02-25*
*작성자: 1인 개발 (momo)*
