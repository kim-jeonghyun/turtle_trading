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

## 킬 스위치 (Kill Switch)

시스템 레벨 트레이딩 안전장치. 신규 진입(BUY)만 차단하며, 청산(SELL)은 항상 허용한다.

### 설정 우선순위

1. 환경변수 `TRADING_ENABLED` (최우선)
2. `config/system_status.yaml`
3. 기본값: `true` (Fail-Open)

### 상태 확인

```bash
python scripts/toggle_trading.py --status
```

### 긴급 중단 (킬 스위치 활성화)

```bash
# CLI를 통한 중단
python scripts/toggle_trading.py --disable --reason "시장 급변"

# 환경변수를 통한 중단 (YAML보다 우선)
export TRADING_ENABLED=false
```

### 트레이딩 재개

```bash
python scripts/toggle_trading.py --enable

# 환경변수 해제 (설정한 경우)
unset TRADING_ENABLED
```

### config/system_status.yaml

```yaml
trading_enabled: true   # false → 신규 진입 차단
reason: ""              # 비활성화 사유
disabled_at: null       # 비활성화 시각 (ISO 8601)
```

### 동작 원리

- `AutoTrader.place_order()`에서 BUY 주문 시 `check_entry_allowed()` 호출
- `scripts/auto_trade.py` 시작 시 킬 스위치 상태 사전 점검
- `scripts/check_positions.py`에서 비활성 시 경고 출력
- `scripts/health_check.py`에서 상태 점검 항목에 포함

### Fail-Open 정책

YAML 파싱 실패 또는 파일 미존재 시 `trading_enabled=true`로 간주한다.
설정 파일 오류로 거래가 중단되는 것을 방지하기 위한 의도적 설계이며,
파싱 오류 시 `WARNING` 로그를 출력한다.

### 주의사항

- 킬 스위치 활성 중에도 기존 포지션의 손절/청산은 정상 실행됨
- 환경변수 설정 후에는 프로세스 재시작 또는 `reload()` 호출 필요
- `config/system_status.yaml`은 원자적 저장(atomic write)으로 동시 접근에 안전

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

### cron 작업 스케줄

아래 테이블은 `crontab` 파일의 19개 개별 엔트리를 15개 논리 그룹으로 정리한 것입니다. 각 그룹 내 복수 cron 엔트리는 시간대 분할(DST 커버, 장시간 분할 등)에 의한 것입니다.

| 시간 (KST) | 요일 | 작업 | 스크립트 | 로그 위치 |
|------------|------|------|---------|----------|
| 02:00 | 매일 | 데이터 백업 | `backup_data.sh` | `/app/logs/backup.log` |
| 03:00 | 일 | 캐시 정리 (7일+) | `find` (crontab 직접) | `/app/logs/cleanup.log` |
| 03:30 | 매월 1일 | 시그널/거래 정리 (90일+) | `find` (crontab 직접) | `/app/logs/cleanup.log` |
| 04:00 | 일 | 로그 정리 (14일+) | `find` (crontab 직접) | `/app/logs/cleanup.log` |
| 매 4시간 | 매일 | 시스템 건강 점검 | `health_check.py` | `/app/logs/health_check.log` |
| 07:00 | 화-토 | US 시그널+포지션 체크 | `check_positions.py` | `/app/logs/check_us.log` |
| 08:00 | 매일 | 일일 리포트 | `daily_report.py` | `/app/logs/daily_report.log` |
| 07:00 | 매월 1일 | 월간 성과 리포트 | `monthly_report.py --send` | `/app/logs/monthly_report.log` |
| 09:00 | 토 | 주간 리포트 | `weekly_report.py --send` | `/app/logs/weekly_report.log` |
| 매시 09-15 | 월-금 | KR 리스크 한도 점검 (7회/일) | `check_risk_limits.py` | `/app/logs/risk_check.log` |
| 5분 간격 09:00-15:25 | 월-금 | KR 장중 모니터링 (2 cron 엔트리) | `monitor_positions.py` | Python 로깅 |
| 16:00 | 월-금 | OHLCV 일별 수집 | `collect_daily_ohlcv.py` | `/app/logs/ohlcv_collect.log` |
| 16:00 | 월-금 | KR 시그널+포지션 체크 | `check_positions.py` | `/app/logs/check_kr.log` |
| 5분 간격 22:00-06:25 | 월-토 | US 장중 모니터링 (3 cron 엔트리) | `monitor_positions.py` | Python 로깅 |
| 매시 23-06 | 월-토 | US 리스크 한도 점검 (2 cron 엔트리) | `check_risk_limits.py` | `/app/logs/risk_check.log` |

### US 시장 DST (서머타임) 처리

US 장중 모니터링과 리스크 점검은 DST 양방향을 커버하는 넓은 시간대로 설정되어 있습니다:

| 기간 | US 장시간 (KST) | cron 커버 범위 |
|------|----------------|---------------|
| 표준시 (EST, 11월~3월) | 23:30~06:00 | 22:00~06:25 |
| 서머타임 (EDT, 3월~11월) | 22:30~05:00 | 22:00~06:25 |

실제 장 시간 판별은 `monitor_positions.py` 내부의 `is_market_open()` 게이트가 수행합니다.
cron은 최대 범위로 실행하고, 장 외 시간에는 스크립트가 즉시 종료됩니다.

## 장애 복구 절차 (Disaster Recovery)

장애 발생 시 아래 시나리오별 절차를 순서대로 실행한다. 킬 스위치 ON이 첫 번째 조치인 시나리오는 즉시 신규 진입을 차단하여 추가 손실을 방지한다.

### 시나리오 1: KIS API 장애

**증상**: 토큰 발급 실패, 주문 응답 없음, `KISAPIClient` 예외 반복

**복구 절차**:

1. 킬 스위치 ON — 신규 진입 즉시 차단
   ```bash
   python -c "from src.kill_switch import KillSwitch; KillSwitch().activate(reason='KIS API 장애')"
   ```
2. KIS 상태 페이지 확인 — [https://apiportal.koreainvestment.com](https://apiportal.koreainvestment.com) 공지 확인
3. 토큰 수동 재발급 — `.env`의 `KIS_APP_KEY` / `KIS_APP_SECRET` 유효 여부 재확인 후 토큰 파일 삭제
   ```bash
   rm -f data/token_cache.json
   ```
4. 상태 점검 재실행
   ```bash
   python scripts/health_check.py
   ```

---

### 시나리오 2: 포지션 불일치

**증상**: `sync_positions.py` 경고, KIS 실제 잔고와 `positions.json` 불일치

**복구 절차**:

1. KIS 웹(HTS/MTS)에서 실제 잔고 확인 — 종목별 수량·평균단가 기록
2. `data/positions/positions.json` 수동 보정 — KIS 실잔고 기준으로 수정
3. 포지션 동기화 재실행
   ```bash
   python scripts/sync_positions.py
   ```

---

### 시나리오 3: 데이터 손상

**증상**: `validate_data.py` 실패, Parquet 파일 읽기 오류, OHLCV 이상값

**복구 절차**:

1. 최근 백업 확인
   ```bash
   ls -lth data/backups/
   ```
2. 백업에서 복원
   ```bash
   tar -xzf data/backups/backup_xxx.tar.gz -C .
   ```
3. OHLCV 데이터 재수집
   ```bash
   python scripts/collect_daily_ohlcv.py
   ```
4. 캐시 정리 후 무결성 재검증
   ```bash
   rm -rf data/cache/*.parquet
   python scripts/validate_data.py
   ```

---

### 시나리오 4: 시스템 중단

**증상**: cron 미실행, 알림 수신 없음, 프로세스 중단

**복구 절차**:

1. Docker 컨테이너 로그 확인
   ```bash
   docker logs turtle-cron --tail 50
   ```
2. 시스템 상태 점검
   ```bash
   python scripts/health_check.py
   ```
3. 컨테이너 재시작
   ```bash
   docker compose restart turtle-cron
   ```

---

### 시나리오 5: 네트워크 장애

**증상**: 외부 API 전체 타임아웃, 연결 거부, DNS 해석 실패

**복구 절차**:

1. 킬 스위치 ON — API 재시도 루프로 인한 이상 동작 방지
   ```bash
   python -c "from src.kill_switch import KillSwitch; KillSwitch().activate(reason='네트워크 장애')"
   ```
2. 네트워크 / DNS / VPN 상태 점검
   ```bash
   ping -c 3 8.8.8.8
   nslookup openapivts.koreainvestment.com
   ```
3. KIS API 엔드포인트 직접 확인
   ```bash
   curl -s https://openapivts.koreainvestment.com:29443
   ```
4. 네트워크 복구 후 킬 스위치 해제 및 상태 재점검
   ```bash
   python scripts/toggle_trading.py --enable
   python scripts/health_check.py
   ```

---

### 시나리오 6: 대량 주문 이상

**증상**: `order_log`에 비정상 주문 다수, 예상 외 종목·수량·방향으로 주문 발생

**복구 절차**:

1. **즉시** 킬 스위치 ON
   ```bash
   python -c "from src.kill_switch import KillSwitch; KillSwitch().activate(reason='대량 주문 이상')"
   ```
2. KIS HTS/MTS에서 미체결 주문 일괄 취소 — 즉시 수동 처리
3. 주문 로그 분석 — 이상 주문 범위·원인 파악
   ```bash
   python -c "import json; [print(o) for o in json.load(open('data/trades/order_log.json')) if o.get('status') != 'FILLED']"
   ```
4. 원인 파악 후 코드 수정 및 재배포 — 재발 방지 확인 후 킬 스위치 해제

---

### 시나리오 7: 일일 손실 한도 초과

**증상**: `TradingGuard` 서킷브레이커 알림, 신규 진입 차단 상태

**복구 절차**:

1. 킬 스위치 자동 활성화 확인
   ```bash
   python -c "from src.kill_switch import KillSwitch; print(KillSwitch().is_trading_enabled)"
   ```
   `False` → 정상 차단 상태. `True` → 킬 스위치 수동 활성화 필요
2. 오픈 포지션 점검 — 청산이 필요한 포지션 확인 (SELL은 킬 스위치 무관 실행 가능)
   ```bash
   python scripts/check_positions.py
   ```
3. 손실 원인 분석 — 시장 급변 vs 시스템 오류 구분
   ```bash
   python -c "import json; print(json.load(open('data/trading_guard_state.json')))"
   python scripts/daily_report.py
   ```
4. 원인 파악 후 다음 거래일 장 시작 전 킬 스위치 해제
   ```bash
   python scripts/toggle_trading.py --enable
   ```

---

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
