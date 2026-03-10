"""
차트 분석 페이지
- 캔들스틱 차트 + 도치안 채널
- N (ATR) 추이
"""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.indicators import add_turtle_indicators


def render(data_fetcher, data_store, universe, symbols, period):
    """차트 분석 페이지 렌더링."""
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

    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="가격",
        )
    )

    # 도치안 채널
    show_dc = st.checkbox("도치안 채널 표시", value=True)
    if show_dc:
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["dc_high_20"], name="20일 고가", line=dict(color="green", dash="dash"))
        )
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["dc_low_20"], name="20일 저가", line=dict(color="red", dash="dash"))
        )
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["dc_high_55"], name="55일 고가", line=dict(color="blue", dash="dot"))
        )
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["dc_low_55"], name="55일 저가", line=dict(color="orange", dash="dot"))
        )

    fig.update_layout(
        title=f"{symbol} 차트",
        xaxis_title="날짜",
        yaxis_title="가격",
        height=600,
        xaxis_rangeslider_visible=False,
    )

    st.plotly_chart(fig, use_container_width=True)

    # N (ATR) 차트
    st.subheader("N (ATR) 추이")
    fig_n = px.line(df, x="date", y="N", title="N (Wilder's ATR)")
    st.plotly_chart(fig_n, use_container_width=True)
