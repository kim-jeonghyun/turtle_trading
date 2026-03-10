"""
시그널 기록 페이지
- 날짜별 시그널 조회
- 최근 7일 시그널 요약
"""

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st


def render(data_fetcher, data_store, universe, **kwargs):
    """시그널 페이지 렌더링."""
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
