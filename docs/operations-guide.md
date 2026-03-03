# 운영 가이드

## 개발 환경 구성

### Python 3.12 가상환경 재구성

`.python-version`에 선언된 Python 3.12 버전과 로컬 가상환경이 일치해야 합니다.

```bash
# 1. 기존 venv 삭제 후 재생성
rm -rf .venv
uv venv --python 3.12 .venv

# 2. 의존성 설치
source .venv/bin/activate
uv pip install -e ".[dev]"

# 3. 검증
python --version  # Python 3.12.x 확인
pytest tests/ -q  # 전체 테스트 통과 확인
```

### 버전 드리프트 감지

`scripts/health_check.py`가 `.python-version`과 실행 중인 Python 버전 일치 여부를 자동 점검합니다.
불일치 시 `[WARN] Python version: running 3.11, .python-version declares 3.12`로 경고합니다.

```bash
python scripts/health_check.py  # Python Version 항목 확인
```

### 버전 정책

- **Single Source of Truth**: `pyproject.toml`의 `[project] version` 필드
- `src/__version__`은 `importlib.metadata`를 통해 동적 조회 (하드코딩 금지)
- 로컬 개발 시 (`pip install -e .` 미실행) `pyproject.toml` 직접 파싱으로 fallback
- `/release` 커맨드 실행 시 `pyproject.toml`만 갱신하면 자동 반영

## 실거래 전 체크리스트

- 백테스트 성능 임계치 재확인(수익/드로우다운/거래빈도)
- 모의 거래 or paper trading 기간 확인
- 알림 누락 여부 점검
- 롤백/중단 절차 테스트

## 실거래 중

- 주문 전: 리스크 상한, 레버리지/노출, 가격 제한, API 상태 확인
- 주문 후: 체결 상태 동기화, 미체결 추적, 이탈/스톱 이벤트 재검토
- 오작동 징후: 빈번한 재시도 실패, stop-loss 미반영, 동일 심볼 다중 청산 오판

## 문제 대응

- 알림 수신 즉시 이벤트 원인 분리: 데이터/계산/API/알림
- `git bisect` 이전 동작으로 되돌릴 수 있는지 사전 준비
- 장애 발생 시 영향 범위(종목/자산군/계좌) 즉시 확정

## 백테스트/시뮬레이션

- 사용 구간: 기본 최근 2~3년 + 스트레스 구간(강한 변동성 구간)
- 핵심 지표: CAGR, max drawdown, Sharpe, hit ratio, turnover
- 검토 항목:
  - 전략별 기여도(System1/System2)
  - Inverse ETF 필터 기여(청산 개선 vs 거래비용)
  - 상관군 제한이 수익/위험에 미치는 영향
  - 비용/슬리피지 민감도
- 결과 문서화: 일자, 입력 데이터 버전, 파라미터, 사용 브랜치

## 알림/모니터링 정책

### 이벤트 분류

| 유형 | 대상 |
|------|------|
| signal | 조건 성립 및 진입/청산 판단 |
| trade | 주문/체결/상태 전이 |
| error | API 실패, 데이터 누락, 예외 |
| risk | 상한 초과, 규칙 위반, 위험 급증 |

### 알림 규칙

- 실패성 알림은 채널 손실 없이 우선 전송
- 동일 이벤트 중복 노이즈 방지 위해 집계/디바운스 적용
- 장애 상황에서는 "조치 항목 + 대상 symbol + 즉시성"을 반드시 함께 발송

## Streamlit 대시보드 배포 정책

- `docker-compose.yaml`에서 Streamlit 포트는 `127.0.0.1:8501:8501`로 로컬 전용 바인딩됨
- 개발/로컬 환경에서는 현재 설정으로 충분
- 외부 접근이 필요한 프로덕션 배포 시:
  1. nginx 또는 caddy 역방향 프록시 설정
  2. 프록시에 인증 레이어 추가 (Basic Auth 또는 OAuth)
  3. `0.0.0.0`으로 직접 변경하지 말 것 — 인증 없이 포트폴리오 정보가 외부에 노출될 위험

## Docker cron 스케줄러

### supercronic 전환 (Docker cron)

v3.4.0부터 Docker 컨테이너의 cron 스케줄러가 `apt cron`(root)에서 `supercronic`(non-root `turtle` 유저)로 전환되었습니다.

**현재 구조:**
- 스케줄러: supercronic v0.2.43 (`/usr/local/bin/supercronic`)
- 크론탭: `/app/crontab`
- 실행 유저: `turtle` (non-root)
- 아키텍처: TARGETARCH 자동 감지 (amd64/arm64)

**호스트 디렉토리 권한 설정 (최초 배포 / root→non-root 마이그레이션):**

컨테이너가 non-root 유저(기본 UID 1000)로 실행되므로, bind mount 대상 디렉토리의 소유권을 맞춰야 합니다.
`entrypoint.sh`가 시작 시 쓰기 권한을 자동 검증하며, 권한 불일치 시 즉시 종료됩니다.

```bash
# 최초 배포 시
mkdir -p ./data ./logs
chown -R 1000:1000 ./data ./logs

# 기존 root cron → supercronic 마이그레이션 시
sudo chown -R 1000:1000 ./data ./logs

# UID가 1000이 아닌 환경에서는 환경변수로 오버라이드
DOCKER_UID=$(id -u) DOCKER_GID=$(id -g) docker compose up -d
```

**롤백 절차** (긴급 시):
1. Dockerfile에서 `cron` 패키지 재설치, supercronic 설치 블록 제거
2. `COPY crontab /etc/cron.d/turtle-cron` + `RUN crontab /etc/cron.d/turtle-cron`으로 복원
3. `USER turtle` 제거, `CMD ["cron", "-f"]`로 복원
4. `docker-compose build && docker-compose up -d`

## KIS API 로그 마스킹 정책

`kis_api.py`의 `_sanitize_response_for_log()` 함수가 DEBUG 로그에 안전 필드만 출력한다.
허용 필드 목록은 `_SAFE_LOG_KEYS`에 정의되어 있으며, 그 외 필드는 자동으로 제외된다.

| 필드 | 용도 | 안전 여부 |
|------|------|-----------|
| `rt_cd` | 응답 코드 (0=성공, 1=실패) | 안전 |
| `msg_cd` | 메시지 코드 | 안전 |
| `msg1` | 에러 메시지 | 안전 |
| `output` | 계좌/주문 상세 데이터 | **제외 (민감)** |
| `CANO` | 계좌번호 | **제외 (민감)** |

### 운영 지침

- 새 응답 필드를 로그에 추가할 때는 반드시 `_SAFE_LOG_KEYS`에 추가하고 민감 여부를 검토할 것
- 프로덕션 로그 수집기는 DEBUG 레벨을 수집하지 않도록 설정 권장
