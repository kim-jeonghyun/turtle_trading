"""
거래 기록 페이지
- 거래 목록 (R-multiple 포함)
- 개별 거래 상세 (expander)
- CSV 다운로드
- 거래 통계
"""

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st


def render(data_fetcher, data_store, universe, **kwargs):
    """거래 기록 페이지 렌더링."""
    st.header("거래 기록")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("시작일", datetime.now() - timedelta(days=30))
    with col2:
        end_date = st.date_input("종료일", datetime.now())

    trades_df = data_store.load_trades(
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
    )

    if trades_df.empty:
        st.info("해당 기간에 거래 기록이 없습니다.")
        return

    # R-multiple 컬럼 추가
    display_df = _add_r_multiple_column(trades_df)

    st.dataframe(display_df, use_container_width=True)

    # CSV 다운로드
    csv_data = display_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="CSV 다운로드",
        data=csv_data,
        file_name=f"trades_{start_date}_{end_date}.csv",
        mime="text/csv",
    )

    # 개별 거래 상세
    st.subheader("거래 상세")
    for idx, row in trades_df.iterrows():
        symbol = row.get("symbol", "N/A")
        pnl = row.get("pnl", 0) or 0
        pnl_label = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        with st.expander(f"{symbol} | {pnl_label}"):
            detail_col1, detail_col2 = st.columns(2)
            with detail_col1:
                st.write(f"**진입일**: {row.get('entry_date', 'N/A')}")
                st.write(f"**진입가**: ${row.get('entry_price', 0):.2f}")
                st.write(f"**방향**: {row.get('direction', 'N/A')}")
                st.write(f"**시스템**: System {row.get('system', 'N/A')}")
            with detail_col2:
                st.write(f"**청산일**: {row.get('exit_date', 'N/A')}")
                st.write(f"**청산가**: ${row.get('exit_price', 0):.2f}")
                st.write(f"**청산 사유**: {row.get('exit_reason', 'N/A')}")
                st.write(f"**PnL**: {pnl_label}")

    st.divider()

    # 통계
    st.subheader("거래 통계")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("총 거래", len(trades_df))
    with col2:
        if "pnl" in trades_df.columns:
            winning = len(trades_df[trades_df["pnl"] > 0])
            st.metric("승률", f"{winning / len(trades_df) * 100:.1f}%")
        else:
            st.metric("승률", "N/A")
    with col3:
        if "pnl" in trades_df.columns:
            st.metric("총 수익", f"${trades_df['pnl'].sum():,.2f}")
        else:
            st.metric("총 수익", "N/A")
    with col4:
        if "pnl" in trades_df.columns:
            st.metric("평균 수익", f"${trades_df['pnl'].mean():,.2f}")
        else:
            st.metric("평균 수익", "N/A")


def _add_r_multiple_column(trades_df: pd.DataFrame) -> pd.DataFrame:
    """거래 DataFrame에 R-multiple 컬럼 추가."""
    df = trades_df.copy()

    if "r_multiple" in df.columns:
        return df

    # entry_price, stop_loss, pnl, total_shares 가 있으면 계산
    required = {"entry_price", "stop_loss", "pnl", "total_shares"}
    if not required.issubset(set(df.columns)):
        df["R-multiple"] = "N/A"
        return df

    r_values = []
    for _, row in df.iterrows():
        entry = row.get("entry_price", 0) or 0
        stop = row.get("stop_loss", 0) or 0
        pnl = row.get("pnl", 0) or 0
        shares = row.get("total_shares", 0) or 0

        risk = abs(entry - stop) * shares
        if risk > 0:
            r_values.append(round(pnl / risk, 2))
        else:
            r_values.append(None)

    df["R-multiple"] = r_values
    return df
