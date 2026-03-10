"""
백테스트 페이지
- 백테스트 설정 및 실행
- 결과 표시 (자산 곡선, 거래 내역)
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.backtester import BacktestConfig, TurtleBacktester


def render(data_fetcher, data_store, universe, symbols, period):
    """백테스트 페이지 렌더링."""
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
            use_filter=use_filter,
        )

        with st.spinner("백테스트 실행 중..."):
            data = {}
            for symbol in symbols:
                df = data_fetcher.fetch(symbol, period=period)
                if not df.empty:
                    data[symbol] = df

            if not data:
                st.error("데이터를 가져올 수 없습니다.")
                return

            backtester = TurtleBacktester(config)
            result = backtester.run(data)

        # 결과 표시
        st.subheader("백테스트 결과")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("총 수익률", f"{result.total_return * 100:.2f}%")
        with col2:
            st.metric("CAGR", f"{result.cagr * 100:.2f}%")
        with col3:
            st.metric("최대 낙폭", f"{result.max_drawdown * 100:.2f}%")
        with col4:
            st.metric("샤프 비율", f"{result.sharpe_ratio:.2f}")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("총 거래", result.total_trades)
        with col2:
            st.metric("승률", f"{result.win_rate * 100:.1f}%")
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
                    "수익률": f"{t.pnl_pct * 100:.2f}%",
                    "사유": t.exit_reason,
                }
                for t in result.trades
            ]
            st.dataframe(pd.DataFrame(trades_data), use_container_width=True)
