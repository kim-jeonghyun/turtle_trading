# 🐢 터틀 트레이딩 시스템 v2.0

터틀 트레이딩 전략을 기반으로 한 반자동 투자 시스템입니다.

## 📋 주요 기능

### 트레이딩 시스템
- **System 1**: 20일 돌파 진입 / 10일 이탈 청산 (필터 적용)
- **System 2**: 55일 돌파 진입 / 20일 이탈 청산 (필터 없음)
- **Wilder's ATR (N)**: 변동성 기반 포지션 사이징

### 리스크 관리
- 1% 리스크 기반 포지션 사이징
- 피라미딩: 0.5N 간격, 최대 4 Units
- 스톱로스: 2N
- 포트폴리오 리스크 한도:
  - 단일 종목: 4 Units
  - 상관 그룹: 6 Units
  - 단일 방향: 12 Units
  - 전체 N 노출: ≤ 10

### 지원 시장
- 🇺🇸 미국 주식 (yfinance)
- 🇰🇷 한국 주식 (FinanceDataReader, KIS API)
- 🪙 암호화폐 (ccxt/Binance)
- 📦 원자재/채권 ETF

### 알림 시스템
- Telegram
- Discord
- Email

## 🚀 빠른 시작

### 1. 설치

```bash
git clone https://github.com/kim-jeonghyun/turtle_trading.git
cd turtle_trading
pip install -r requirements.txt
```

### 2. 환경 변수 설정

```bash
cp .env.example .env
# .env 파일을 편집하여 API 키 설정
```

### 3. 실행

```bash
# Streamlit 대시보드
streamlit run app.py

# 시그널 체크 (수동)
python scripts/signal_check.py

# 일일 리포트
python scripts/daily_report.py
```

### 4. Docker 실행

```bash
docker-compose up -d
```

## 📁 프로젝트 구조

```
turtle_trading/
├── src/
│   ├── __init__.py
│   ├── indicators.py        # Wilder's ATR, 도치안 채널
│   ├── position_sizer.py    # 1% 리스크 기반 사이징
│   ├── risk_manager.py      # 포트폴리오 리스크 관리
│   ├── pyramid_manager.py   # 피라미딩 로직
│   ├── inverse_filter.py    # Inverse ETF 필터
│   ├── universe_manager.py  # 거래 유니버스 관리
│   ├── data_fetcher.py      # 멀티마켓 데이터 수집
│   ├── data_store.py        # Parquet 데이터 저장
│   ├── kis_api.py           # 한국투자증권 API
│   ├── notifier.py          # 알림 시스템
│   └── backtester.py        # 백테스터
├── scripts/
│   ├── signal_check.py      # 시그널 체크 스크립트
│   └── daily_report.py      # 일일 리포트 스크립트
├── config/
│   └── notifications.yaml   # 알림 설정
├── data/
│   ├── cache/               # OHLCV 캐시
│   ├── trades/              # 거래 기록
│   └── signals/             # 시그널 기록
├── logs/                    # 로그 파일
├── app.py                   # Streamlit 대시보드
├── Dockerfile
├── docker-compose.yaml
├── crontab
├── requirements.txt
└── .env.example
```

## ⚙️ 설정

### 알림 채널 설정

#### Telegram
1. @BotFather로 봇 생성
2. 봇 토큰과 Chat ID를 `.env`에 설정

#### Discord
1. 서버 설정 → 연동 → 웹훅 생성
2. 웹훅 URL을 `.env`에 설정

#### Email
1. Gmail 앱 비밀번호 생성
2. SMTP 설정을 `.env`에 입력

### 한국투자증권 API
1. [한국투자증권 OpenAPI](https://apiportal.koreainvestment.com/) 가입
2. 앱 키 발급
3. `.env`에 설정

## 📊 백테스트

```python
from src.backtester import TurtleBacktester, BacktestConfig
from src.data_fetcher import DataFetcher

config = BacktestConfig(
    initial_capital=100000,
    risk_percent=0.01,
    system=1,
    max_units=4
)

fetcher = DataFetcher()
data = fetcher.fetch_multiple(["SPY", "QQQ", "GLD"], period="2y")

backtester = TurtleBacktester(config)
result = backtester.run(data)

print(f"총 수익률: {result.total_return*100:.2f}%")
print(f"최대 낙폭: {result.max_drawdown*100:.2f}%")
print(f"샤프 비율: {result.sharpe_ratio:.2f}")
```

## 📝 참고 자료

- [Way of the Turtle - Curtis Faith](https://www.amazon.com/Way-Turtle-Methods-Ordinary-Legendary/dp/007148664X)
- [Original Turtle Trading Rules](https://www.trendfollowing.com/whitepaper/turtle-rules.pdf)

## ⚠️ 면책 조항

이 프로젝트는 교육 목적으로만 제공됩니다. 실제 투자에 사용할 경우 발생하는 모든 손실에 대한 책임은 사용자에게 있습니다.

## 📜 라이선스

MIT License
