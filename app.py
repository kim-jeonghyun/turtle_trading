"""
터틀 트레이딩 Streamlit 대시보드
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.backtester import BacktestConfig, TurtleBacktester
from src.data_fetcher import DataFetcher
from src.data_store import ParquetDataStore
from src.indicators import add_turtle_indicators
from src.universe_manager import UniverseManager

st.set_page_config(
    page_title="터틀 트레이딩 시스템",
    page_icon="🐢",
    layout="wide"
)

# 초기화
@st.cache_resource
def init_components():
    data_fetcher = DataFetcher()
    data_store = ParquetDataStore()
    universe_path = Path("config/universe.yaml")
    universe = UniverseManager(str(universe_path))
    return data_fetcher, data_store, universe


data_fetcher, data_store, universe = init_components()


def main():
    st.title("🐢 터틀 트레이딩 시스템 v3.2.1")

    # 사이드바
    with st.sidebar:
        st.header("설정")

        page = st.radio(
            "페이지 선택",
            ["📊 대시보드", "📈 차트 분석", "🔔 시그널", "📜 거래 기록", "🧪 백테스트"]
        )

        st.divider()

        # 종목 선택
        symbols = universe.get_enabled_symbols()
        if not symbols:
            symbols = ["SPY", "QQQ", "GLD", "TLT"]

        selected_symbols = st.multiselect(
            "종목 선택",
            symbols,
            default=symbols[:4] if len(symbols) >= 4 else symbols
        )

        # 기간 선택
        period = st.selectbox(
            "데이터 기간",
            ["6mo", "1y", "2y", "5y"],
            index=1
        )

    # 페이지 라우팅
    if page == "📊 대시보드":
        show_dashboard(selected_symbols, period)
    elif page == "📈 차트 분석":
        show_chart_analysis(selected_symbols, period)
    elif page == "🔔 시그널":
        show_signals()
    elif page == "📜 거래 기록":
        show_trades()
    elif page == "🧪 백테스트":
        show_backtest(selected_symbols, period)


def show_dashboard(symbols: list, period: str):
    st.header("포트폴리오 대시보드")

    col1, col2, col3, col4 = st.columns(4)

    # 캐시 통계
    cache_stats = data_store.get_cache_stats()

    with col1:
        st.metric("캐시 파일", cache_stats["cache_files"])
    with col2:
        st.metric("거래 기록", cache_stats["trade_files"])
    with col3:
        st.metric("시그널 기록", cache_stats["signal_files"])
    with col4:
        st.metric("데이터 크기", f"{cache_stats['total_size_mb']:.1f} MB")

    st.divider()

    # 종목별 현황
    st.subheader("종목 현황")

    data_list = []
    for symbol in symbols:
        try:
            df = data_fetcher.fetch(symbol, period=period)
            if df.empty:
                continue

            df = add_turtle_indicators(df)
            latest = df.iloc[-1]

            data_list.append({
                "종목": symbol,
                "현재가": f"{latest['close']:.2f}",
                "N (ATR)": f"{latest['N']:.2f}",
                "20일 고가": f"{latest['dc_high_20']:.2f}",
                "20일 저가": f"{latest['dc_low_20']:.2f}",
                "55일 고가": f"{latest['dc_high_55']:.2f}",
                "상태": "📈 상승추세" if latest['close'] > latest['dc_high_20'] else "📉 하락추세"
            })
        except Exception as e:
            st.warning(f"{symbol} 데이터 로드 실패: {e}")

    if data_list:
        df_display = pd.DataFrame(data_list)
        st.dataframe(df_display, use_container_width=True)


def show_chart_analysis(symbols: list, period: str):
    st.header("차트 분석")

    if not symbols:
        st.warning("종목을 선택해주세요.")
        return

    symbol = st.selectbox("분석 종목", symbols)

    with st.spinner(f"{symbol} 데이터 로딩..."):
        df = data_fetcher.fetch(symbol, period=period)
        if df.empty:
            st.error("데이터를 가져올 수 없습니다.")
            return

        df = add_turtle_indicators(df)

    # 캔들스틱 차트
    fig = go.Figure()

    # 캔들스틱
    fig.add_trace(go.Candlestick(
        x=df["date"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="가격"
    ))

    # 도치안 채널
    show_dc = st.checkbox("도치안 채널 표시", value=True)
    if show_dc:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["dc_high_20"],
            name="20일 고가", line=dict(color="green", dash="dash")
        ))
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["dc_low_20"],
            name="20일 저가", line=dict(color="red", dash="dash")
        ))
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["dc_high_55"],
            name="55일 고가", line=dict(color="blue", dash="dot")
        ))
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["dc_low_55"],
            name="55일 저가", line=dict(color="orange", dash="dot")
        ))

    fig.update_layout(
        title=f"{symbol} 차트",
        xaxis_title="날짜",
        yaxis_title="가격",
        height=600,
        xaxis_rangeslider_visible=False
    )

    st.plotly_chart(fig, use_container_width=True)

    # N (ATR) 차트
    st.subheader("N (ATR) 추이")
    fig_n = px.line(df, x="date", y="N", title="N (Wilder's ATR)")
    st.plotly_chart(fig_n, use_container_width=True)


def show_signals():
    st.header("시그널 기록")

    # 날짜 선택
    date = st.date_input("날짜 선택", datetime.now())
    date_str = date.strftime("%Y%m%d")

    signals_df = data_store.load_signals(date_str)

    if signals_df.empty:
        st.info(f"{date} 에 발생한 시그널이 없습니다.")
    else:
        st.dataframe(signals_df, use_container_width=True)

    # 최근 7일 시그널 요약
    st.subheader("최근 7일 시그널 요약")

    recent_signals = []
    for i in range(7):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        df = data_store.load_signals(d)
        if not df.empty:
            recent_signals.append({"날짜": d, "시그널 수": len(df)})

    if recent_signals:
        st.dataframe(pd.DataFrame(recent_signals), use_container_width=True)


def show_trades():
    st.header("거래 기록")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("시작일", datetime.now() - timedelta(days=30))
    with col2:
        end_date = st.date_input("종료일", datetime.now())

    trades_df = data_store.load_trades(
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )

    if trades_df.empty:
        st.info("해당 기간에 거래 기록이 없습니다.")
    else:
        st.dataframe(trades_df, use_container_width=True)

        # 통계
        st.subheader("거래 통계")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("총 거래", len(trades_df))
        with col2:
            winning = len(trades_df[trades_df["pnl"] > 0])
            st.metric("승률", f"{winning/len(trades_df)*100:.1f}%")
        with col3:
            st.metric("총 수익", f"${trades_df['pnl'].sum():,.2f}")
        with col4:
            st.metric("평균 수익", f"${trades_df['pnl'].mean():,.2f}")


def show_backtest(symbols: list, period: str):
    st.header("백테스트")

    col1, col2 = st.columns(2)

    with col1:
        initial_capital = st.number_input("초기 자본금", value=100000, step=10000)
        risk_percent = st.slider("리스크 비율 (%)", 0.5, 3.0, 1.0, 0.5) / 100
        system = st.selectbox("시스템", [1, 2])

    with col2:
        max_units = st.number_input("최대 Unit", value=4, min_value=1, max_value=10)
        use_filter = st.checkbox("System 1 필터 사용", value=True)

    if st.button("백테스트 실행", type="primary"):
        config = BacktestConfig(
            initial_capital=initial_capital,
            risk_percent=risk_percent,
            system=system,
            max_units=max_units,
            use_filter=use_filter
        )

        with st.spinner("백테스트 실행 중..."):
            # 데이터 수집
            data = {}
            for symbol in symbols:
                df = data_fetcher.fetch(symbol, period=period)
                if not df.empty:
                    data[symbol] = df

            if not data:
                st.error("데이터를 가져올 수 없습니다.")
                return

            # 백테스트 실행
            backtester = TurtleBacktester(config)
            result = backtester.run(data)

        # 결과 표시
        st.subheader("백테스트 결과")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("총 수익률", f"{result.total_return*100:.2f}%")
        with col2:
            st.metric("CAGR", f"{result.cagr*100:.2f}%")
        with col3:
            st.metric("최대 낙폭", f"{result.max_drawdown*100:.2f}%")
        with col4:
            st.metric("샤프 비율", f"{result.sharpe_ratio:.2f}")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("총 거래", result.total_trades)
        with col2:
            st.metric("승률", f"{result.win_rate*100:.1f}%")
        with col3:
            st.metric("Profit Factor", f"{result.profit_factor:.2f}")
        with col4:
            st.metric("최종 자산", f"${result.final_equity:,.0f}")

        # 자산 곡선
        if not result.equity_curve.empty:
            st.subheader("자산 곡선")
            fig = px.line(result.equity_curve, x="date", y="equity")
            st.plotly_chart(fig, use_container_width=True)

        # 거래 내역
        if result.trades:
            st.subheader("거래 내역")
            trades_data = [
                {
                    "종목": t.symbol,
                    "방향": t.direction,
                    "진입일": t.entry_date,
                    "진입가": f"{t.entry_price:.2f}",
                    "청산일": t.exit_date,
                    "청산가": f"{t.exit_price:.2f}" if t.exit_price else "-",
                    "수익": f"${t.pnl:.2f}",
                    "수익률": f"{t.pnl_pct*100:.2f}%",
                    "사유": t.exit_reason
                }
                for t in result.trades
            ]
            st.dataframe(pd.DataFrame(trades_data), use_container_width=True)


if __name__ == "__main__":
    main()
