# Turtle Trading System - Claude Development Guide

## 프로젝트 개요

터틀 트레이딩 전략을 기반으로 한 반자동 투자 시스템입니다. Curtis Faith의 "Way of the Turtle"에 기반한 System 1 & 2를 구현하며, 멀티마켓(미국/한국 주식, 암호화폐, ETF)을 지원합니다.

### 핵심 전략

**System 1 (단기)**
- 진입: 20일 돌파 (필터: 최근 55일 동안 System 1 시그널이 승리했을 때만)
- 청산: 10일 이탈

**System 2 (장기)**
- 진입: 55일 돌파 (필터 없음)
- 청산: 20일 이탈

**리스크 관리**
- 포지션 사이징: 계좌의 2% 리스크 기반
- ATR(N): Wilder's 20일 ATR (변동성 지표)
- 스톱로스: 2N
- 피라미딩: 0.5N 간격, 최대 4 Units
- 포트폴리오 제한:
  - 단일 종목: 4 Units
  - 상관 그룹(예: 금속, 에너지): 6 Units
  - 단일 방향(Long/Short): 12 Units
  - 전체 N 노출: ≤ 10

## 기술 스택

- **언어**: Python 3.11+
- **데이터**: yfinance (미국), FinanceDataReader (한국), ccxt (암호화폐)
- **대시보드**: Streamlit
- **API**: 한국투자증권 OpenAPI (한국 주식 거래)
- **알림**: Telegram, Discord, Email
- **저장**: Parquet (OHLCV 캐시), JSON (거래 기록)

## 코드 작성 규칙

### 1. 도메인 용어 일관성

| 영어 | 한국어 | 설명 |
|------|--------|------|
| N | 변동성(N) | Wilder's 20일 ATR |
| Unit | 유닛 | 표준화된 포지션 단위 (계좌의 1%) |
| Breakout | 돌파 | 채널 상단 돌파 |
| Exit | 이탈 | 채널 하단 이탈 |
| Pyramiding | 피라미딩 | 수익 포지션 추가 진입 |
| Donchian Channel | 도치안 채널 | 최고가/최저가 채널 |

### 2. 코드 스타일

```python
# GOOD: 명확한 변수명과 주석
def calculate_position_size(account_balance: float, risk_percent: float, atr: float, price: float) -> int:
    """
    2% 리스크 기반 포지션 사이징

    Args:
        account_balance: 계좌 잔고
        risk_percent: 리스크 비율 (0.02 = 2%)
        atr: 20일 Wilder's ATR (N)
        price: 현재 가격

    Returns:
        매수 수량
    """
    dollar_risk = account_balance * risk_percent
    shares = (dollar_risk / (2 * atr)) * price
    return int(shares)

# BAD: 모호한 변수명
def calc_pos(bal, r, n, p):
    return int((bal * r / (2 * n)) * p)
```

### 3. 필수 검증 사항

모든 트레이딩 로직 변경 시:
- [ ] ATR(N) 계산이 Wilder's 방식인지 확인
- [ ] 포지션 사이즈가 2% 리스크 기반인지 확인
- [ ] 스톱로스가 2N인지 확인
- [ ] 피라미딩 간격이 0.5N인지 확인
- [ ] 포트폴리오 제한 준수 확인

### 4. 데이터 처리

```python
# 데이터 페칭 순서
# 1. 캐시 확인 (data/cache/*.parquet)
# 2. 캐시 미스 시 API 호출
# 3. Parquet 저장 (일별 업데이트)

from src.data_fetcher import DataFetcher

fetcher = DataFetcher()
df = fetcher.fetch("SPY", period="1y")  # 자동 캐싱
```

### 5. 에러 처리

```python
# 외부 API 호출은 항상 try-except
try:
    data = fetcher.fetch("INVALID")
except Exception as e:
    logger.error(f"데이터 페칭 실패: {e}")
    # 알림 발송
    notifier.send_error(f"[ERROR] {e}")
```

## 프로젝트 구조

```
src/
├── indicators.py        # ATR, 도치안 채널 (순수 계산, 사이드 이펙트 없음)
├── position_sizer.py    # 포지션 사이징 (순수 함수)
├── risk_manager.py      # 포트폴리오 제한 검증
├── pyramid_manager.py   # 피라미딩 로직
├── inverse_filter.py    # Inverse ETF 괴리율(decay) 감지 — 레버리지/인버스 ETF 보유일 초과 또는 기초자산 대비 괴리율 초과 시 강제 청산
├── universe_manager.py  # 거래 유니버스 관리
├── data_fetcher.py      # 멀티마켓 데이터 수집 (캐싱)
├── data_store.py        # Parquet 저장
├── kis_api.py           # 한국투자증권 API (실거래)
├── notifier.py          # 알림 시스템
└── backtester.py        # 백테스터

scripts/
├── signal_check.py      # 일일 시그널 체크 (cron)
└── daily_report.py      # 일일 리포트 (cron)
```

## 개발 워크플로우

### 1. 새 기능 추가

```bash
# 1. 브랜치 생성
git checkout -b feature/new-indicator

# 2. 개발
# src/ 하위에 모듈 추가

# 3. 테스트
pytest tests/test_new_indicator.py

# 4. 백테스트 검증
python scripts/backtest_new_feature.py

# 5. 커밋
git add .
git commit -m "feat: Add Bollinger Bands indicator"
```

### 2. 실거래 전 체크리스트

- [ ] 백테스트 수익률 > 10% (2년 기준)
- [ ] 최대 낙폭 < 30%
- [ ] 샤프 비율 > 0.5
- [ ] 시그널 알림 테스트 (Telegram/Discord)
- [ ] 종이 거래(Paper Trading) 1개월
- [ ] 소액 실거래 1개월

### 3. 알림 설정

```yaml
# config/notifications.yaml
channels:
  telegram:
    enabled: true
    events: [signal, trade, error]
  discord:
    enabled: true
    events: [daily_report]
  email:
    enabled: false
    events: [error]
```

## 중요 제약사항

### 1. API 제한

| API | 제한 | 캐싱 전략 |
|-----|------|-----------|
| yfinance | 2000 req/hour | 일별 Parquet 캐시 |
| KIS OpenAPI | 초당 20건 | Rate limiting |
| Binance | 1200 req/min | WebSocket 우선 |

### 2. 실거래 안전 장치

```python
# 실거래 전 필수 확인
if PRODUCTION:
    assert max_position_size <= account_balance * 0.04  # 단일 종목 4% 제한
    assert total_units <= 4  # 최대 4 Units
    assert stop_loss == entry_price - (2 * atr)  # 2N 스톱
```

### 3. 한국 시장 특이사항

- 상한가/하한가: 진입 불가 (유동성 부족)
- 거래 정지: 시그널 무효 처리
- 공매도 제한: Long Only (일부 종목)

## 참고 자료

### 도서
- **Way of the Turtle** (Curtis Faith) - 핵심 전략
- **Complete TurtleTrader** (Michael Covel) - 역사와 심리

### 문서
- [Original Turtle Rules](https://www.trendfollowing.com/whitepaper/turtle-rules.pdf)
- [한국투자증권 API 문서](https://apiportal.koreainvestment.com/)

### 리서치
- `research/readings/youtube/` - Martin Luk 등 트레이더 전략 분석
- `research/backtests/` - 백테스트 결과

## 자주 묻는 질문

**Q: System 1과 System 2를 동시에 운영하나요?**
A: 네, 동일 종목에 대해 양쪽 시스템을 독립적으로 운영합니다. 단, 포트폴리오 제한은 통합 관리합니다.

**Q: 피라미딩은 언제 하나요?**
A: 진입가 대비 0.5N 상승 시마다 추가 진입합니다 (최대 4 Units).

**Q: Inverse ETF 필터란?**
A: Inverse ETF(SH, PSQ, SDS, SQQQ, SPXU)의 보유일 초과 또는 기초자산 대비 괴리율(decay) 초과 시 강제 청산합니다. (VIX 기반 System 1 비활성화는 별도 미구현 기능)

## 라이선스 및 면책

MIT License. 교육 목적 프로젝트이며, 실거래 손실에 대한 책임은 사용자에게 있습니다.

---

## Claude에게

- 트레이딩 로직 변경 시 반드시 백테스트 실행을 제안하세요
- 실거래 관련 코드는 더블 체크하세요
- 알림 시스템은 에러 발생 시에도 작동해야 합니다
- 한국어 주석과 영어 변수명을 혼용합니다
- `research/` 폴더의 문서를 참고하여 전략을 이해하세요
