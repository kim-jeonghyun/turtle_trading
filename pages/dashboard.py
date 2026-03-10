"""
포트폴리오 대시보드 페이지
- 캐시 통계
- 종목별 현황
- 오픈 포지션 카드
- 오늘의 시그널 요약
- 30일 PnL 미니 차트
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from src.indicators import add_turtle_indicators
from src.position_tracker import PositionTracker

logger = logging.getLogger(__name__)


def render(data_fetcher, data_store, universe, symbols, period):
    """대시보드 페이지 렌더링."""
    st.header("포트폴리오 대시보드")

    col1, col2, col3, col4 = st.columns(4)

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

    # 오픈 포지션 카드
    _render_open_positions()

    st.divider()

    # 오늘의 시그널 요약
    _render_today_signals(data_store)

    st.divider()

    # 30일 PnL 미니 차트
    _render_pnl_mini_chart(data_store)

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

            data_list.append(
                {
                    "종목": symbol,
                    "현재가": f"{latest['close']:.2f}",
                    "N (ATR)": f"{latest['N']:.2f}",
                    "20일 고가": f"{latest['dc_high_20']:.2f}",
                    "20일 저가": f"{latest['dc_low_20']:.2f}",
                    "55일 고가": f"{latest['dc_high_55']:.2f}",
                    "상태": "상승추세" if latest["close"] > latest["dc_high_20"] else "하락추세",
                }
            )
        except Exception as e:
            st.warning(f"{symbol} 데이터 로드 실패: {e}")

    if data_list:
        df_display = pd.DataFrame(data_list)
        st.dataframe(df_display, use_container_width=True)


def _render_open_positions():
    """오픈 포지션 카드 표시."""
    st.subheader("오픈 포지션")
    try:
        tracker = PositionTracker()
        open_positions = tracker.get_open_positions()

        if not open_positions:
            st.info("현재 오픈 포지션이 없습니다.")
            return

        cols = st.columns(min(len(open_positions), 4))
        for i, pos in enumerate(open_positions):
            with cols[i % 4]:
                direction_label = "LONG" if pos.direction.value == "LONG" else "SHORT"
                st.metric(
                    label=f"{pos.symbol} ({direction_label})",
                    value=f"${pos.entry_price:.2f}",
                    delta=f"Units: {pos.units}/{pos.max_units}",
                )
                st.caption(f"Stop: ${pos.stop_loss:.2f} | System {pos.system}")
    except Exception as e:
        logger.warning(f"포지션 로드 실패: {e}", exc_info=True)
        st.info("포지션 데이터를 불러올 수 없습니다.")


def _render_today_signals(data_store):
    """오늘의 시그널 요약."""
    st.subheader("오늘의 시그널")
    today_str = datetime.now().strftime("%Y%m%d")
    signals_df = data_store.load_signals(today_str)

    if signals_df.empty:
        st.info("오늘 발생한 시그널이 없습니다.")
    else:
        st.metric("시그널 수", len(signals_df))
        st.dataframe(signals_df, use_container_width=True)


def _render_pnl_mini_chart(data_store):
    """최근 30일 PnL 미니 차트."""
    st.subheader("최근 30일 PnL")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    trades_df = data_store.load_trades(
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
    )

    if trades_df.empty:
        st.info("최근 30일 거래 기록이 없습니다.")
        return

    if "pnl" in trades_df.columns and "exit_date" in trades_df.columns:
        trades_df["exit_date"] = pd.to_datetime(trades_df["exit_date"], errors="coerce")
        daily_pnl = trades_df.groupby(trades_df["exit_date"].dt.date)["pnl"].sum().reset_index()
        daily_pnl.columns = ["날짜", "PnL"]
        daily_pnl["누적 PnL"] = daily_pnl["PnL"].cumsum()

        fig = px.line(daily_pnl, x="날짜", y="누적 PnL", title="30일 누적 PnL")
        fig.update_layout(height=250)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("PnL 데이터가 부족합니다.")
