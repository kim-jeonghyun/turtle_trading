"""
터틀 트레이딩 Streamlit 대시보드
"""

import importlib.metadata
from pathlib import Path

import streamlit as st

from pages import backtest, chart_analysis, dashboard, performance, risk, signals, trades
from src.data_fetcher import DataFetcher
from src.data_store import ParquetDataStore
from src.universe_manager import UniverseManager

st.set_page_config(page_title="터틀 트레이딩 시스템", page_icon="🐢", layout="wide")


# 초기화
@st.cache_resource
def init_components():
    data_fetcher = DataFetcher()
    data_store = ParquetDataStore()
    universe_path = Path("config/universe.yaml")
    universe = UniverseManager(str(universe_path))
    return data_fetcher, data_store, universe


def _get_version() -> str:
    """패키지 버전 조회."""
    try:
        return importlib.metadata.version("turtle-trading")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


data_fetcher, data_store, universe = init_components()


def main():
    version = _get_version()
    st.title(f"터틀 트레이딩 시스템 v{version}")

    # 사이드바
    with st.sidebar:
        st.header("설정")

        page = st.radio(
            "페이지 선택",
            [
                "📊 대시보드",
                "📈 차트 분석",
                "🔔 시그널",
                "📜 거래 기록",
                "📊 성과 분석",
                "🛡️ 리스크",
                "🧪 백테스트",
            ],
        )

        st.divider()

        # 종목 선택
        symbols = universe.get_enabled_symbols()
        if not symbols:
            symbols = ["SPY", "QQQ", "GLD", "TLT"]

        selected_symbols = st.multiselect(
            "종목 선택",
            symbols,
            default=symbols[:4] if len(symbols) >= 4 else symbols,
        )

        # 기간 선택
        period = st.selectbox("데이터 기간", ["6mo", "1y", "2y", "5y"], index=1)

    # 페이지 라우팅
    if page == "📊 대시보드":
        dashboard.render(data_fetcher, data_store, universe, selected_symbols, period)
    elif page == "📈 차트 분석":
        chart_analysis.render(data_fetcher, data_store, universe, selected_symbols, period)
    elif page == "🔔 시그널":
        signals.render(data_fetcher, data_store, universe)
    elif page == "📜 거래 기록":
        trades.render(data_fetcher, data_store, universe)
    elif page == "📊 성과 분석":
        performance.render(data_fetcher, data_store, universe)
    elif page == "🛡️ 리스크":
        risk.render(data_fetcher, data_store, universe)
    elif page == "🧪 백테스트":
        backtest.render(data_fetcher, data_store, universe, selected_symbols, period)


if __name__ == "__main__":
    main()
