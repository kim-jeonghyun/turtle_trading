"""
성과 분석 페이지
- 에쿼티 커브 (드로다운 포함)
- MDD 게이지
- 승률 / Profit Factor / Expectancy 메트릭
- R-multiple 히스토그램
- 종목별 PnL 바 차트
- 월별 PnL 히트맵
- System 1 vs 2 비교 테이블
"""

import logging
from collections import defaultdict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.analytics import TradeAnalytics
from src.position_tracker import PositionTracker

logger = logging.getLogger(__name__)

# 기간 필터 매핑 (월 수)
PERIOD_MAP = {
    "1개월": 1,
    "3개월": 3,
    "6개월": 6,
    "1년": 12,
    "전체": None,
}


def render(data_fetcher, data_store, universe, **kwargs):
    """성과 분석 페이지 렌더링."""
    st.header("성과 분석")

    # 사이드바 기간 필터
    period_label = st.sidebar.selectbox("분석 기간", list(PERIOD_MAP.keys()), index=4)

    # 거래 데이터 로드
    trades = _load_closed_trades()

    if not trades:
        st.info("분석할 청산 완료 거래가 없습니다.")
        return

    # 기간 필터 적용
    trades = _filter_by_period(trades, PERIOD_MAP[period_label])

    if not trades:
        st.info(f"선택한 기간({period_label})에 해당하는 거래가 없습니다.")
        return

    analytics = TradeAnalytics(trades)

    # 메트릭 카드 행
    _render_metric_cards(analytics)

    st.divider()

    # 에쿼티 커브 + 드로다운
    _render_equity_curve(analytics)

    st.divider()

    # R-multiple 히스토그램
    _render_r_histogram(analytics)

    st.divider()

    # 종목별 PnL 바 차트
    _render_per_symbol_pnl(analytics)

    st.divider()

    # 월별 PnL 히트맵
    _render_monthly_heatmap(analytics)

    st.divider()

    # System 1 vs 2 비교
    _render_system_comparison(analytics)


@st.cache_data(ttl=300)
def _load_closed_trades():
    """청산 완료 거래 로드 (캐시 적용)."""
    try:
        tracker = PositionTracker()
        all_positions = tracker.get_all_positions()
        closed = [p.to_dict() for p in all_positions if p.status == "closed"]
        return closed
    except Exception as e:
        logger.warning(f"거래 데이터 로드 실패: {e}")
        return []


def _filter_by_period(trades, months):
    """기간 필터."""
    if months is None:
        return trades

    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=months * 30)
    filtered = []
    for t in trades:
        exit_date_str = str(t.get("exit_date", ""))
        try:
            exit_date = datetime.strptime(exit_date_str[:10], "%Y-%m-%d")
            if exit_date >= cutoff:
                filtered.append(t)
        except (ValueError, TypeError):
            continue
    return filtered


def _render_metric_cards(analytics):
    """메트릭 카드 행."""
    stats = analytics.get_win_loss_stats()
    expectancy = analytics.get_expectancy()
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("총 거래", stats["total_trades"])
    with col2:
        st.metric("승률", f"{stats['win_rate'] * 100:.1f}%")
    with col3:
        st.metric("Profit Factor", f"{stats['profit_factor']:.2f}")
    with col4:
        st.metric("기대값 (E)", f"{expectancy:.3f}R")
    with col5:
        # MDD 게이지
        equity_curve = analytics.get_equity_curve(initial_capital=100000)
        if equity_curve:
            equity_values = [p["equity"] for p in equity_curve]
            dd_analysis = analytics.get_drawdown_analysis(equity_values)
            st.metric("MDD", f"{dd_analysis['max_drawdown_pct']:.1f}%")
        else:
            st.metric("MDD", "N/A")


def _render_equity_curve(analytics):
    """에쿼티 커브 + 드로다운 영역."""
    st.subheader("에쿼티 커브")

    curve_data = analytics.get_equity_curve(initial_capital=100000)
    if not curve_data:
        st.info("에쿼티 커브를 생성할 수 없습니다.")
        return

    df = pd.DataFrame(curve_data)

    fig = go.Figure()

    # 에쿼티 라인
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["equity"],
            name="자산",
            line=dict(color="blue"),
        )
    )

    # 드로다운 영역 (보조 y축)
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["drawdown_pct"],
            name="드로다운 (%)",
            fill="tozeroy",
            line=dict(color="red"),
            opacity=0.3,
            yaxis="y2",
        )
    )

    fig.update_layout(
        title="에쿼티 커브 & 드로다운",
        yaxis=dict(title="자산 ($)"),
        yaxis2=dict(title="드로다운 (%)", overlaying="y", side="right", autorange="reversed"),
        height=400,
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_r_histogram(analytics):
    """R-multiple 히스토그램."""
    st.subheader("R-배수 분포")

    r_multiples = analytics.calculate_r_multiples()
    if not r_multiples:
        st.info("R-배수 데이터가 없습니다.")
        return

    df = pd.DataFrame({"R-multiple": r_multiples})

    fig = px.histogram(
        df,
        x="R-multiple",
        nbins=30,
        title="R-배수 분포",
        color_discrete_sequence=["steelblue"],
    )
    fig.add_vline(x=0, line_dash="dash", line_color="red")
    fig.update_layout(height=350)
    st.plotly_chart(fig, use_container_width=True)


def _render_per_symbol_pnl(analytics):
    """종목별 PnL 수평 바 차트."""
    st.subheader("종목별 PnL")

    symbol_pnl = analytics.get_per_symbol_pnl()
    if not symbol_pnl:
        st.info("종목별 PnL 데이터가 없습니다.")
        return

    df = pd.DataFrame(
        [
            {"종목": symbol, "PnL": data["total_pnl"], "거래 수": data["trade_count"]}
            for symbol, data in sorted(symbol_pnl.items(), key=lambda x: x[1]["total_pnl"])
        ]
    )

    colors = ["green" if v >= 0 else "red" for v in df["PnL"]]

    fig = go.Figure(
        go.Bar(
            x=df["PnL"],
            y=df["종목"],
            orientation="h",
            marker_color=colors,
            text=[f"${v:,.0f}" for v in df["PnL"]],
            textposition="auto",
        )
    )
    fig.update_layout(title="종목별 PnL", xaxis_title="PnL ($)", height=max(300, len(df) * 30))
    st.plotly_chart(fig, use_container_width=True)


def _render_monthly_heatmap(analytics):
    """월별 PnL 히트맵."""
    st.subheader("월별 PnL 히트맵")

    monthly = analytics.get_monthly_returns()
    if not monthly:
        st.info("월별 데이터가 없습니다.")
        return

    heatmap_data = build_monthly_heatmap_data(monthly)
    if heatmap_data.empty:
        st.info("히트맵 데이터를 생성할 수 없습니다.")
        return

    fig = go.Figure(
        go.Heatmap(
            z=heatmap_data.values,
            x=heatmap_data.columns.tolist(),
            y=heatmap_data.index.tolist(),
            colorscale="RdYlGn",
            text=[[f"${v:,.0f}" if pd.notna(v) else "" for v in row] for row in heatmap_data.values],
            texttemplate="%{text}",
            hovertemplate="Year: %{y}<br>Month: %{x}<br>PnL: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="월별 PnL 히트맵",
        xaxis_title="월",
        yaxis_title="연도",
        height=300,
    )
    st.plotly_chart(fig, use_container_width=True)


def build_monthly_heatmap_data(monthly_returns: dict) -> pd.DataFrame:
    """월별 수익 딕셔너리를 히트맵용 DataFrame으로 변환.

    Args:
        monthly_returns: {"YYYY-MM": pnl, ...}

    Returns:
        DataFrame (index=year, columns=month 1-12)
    """
    if not monthly_returns:
        return pd.DataFrame()

    data: dict[str, dict[int, float]] = defaultdict(dict)
    for key, pnl in monthly_returns.items():
        try:
            parts = key.split("-")
            year = parts[0]
            month = int(parts[1])
            data[year][month] = pnl
        except (IndexError, ValueError):
            continue

    if not data:
        return pd.DataFrame()

    month_labels = [str(m) for m in range(1, 13)]
    rows = {}
    for year in sorted(data.keys()):
        rows[year] = [data[year].get(m) for m in range(1, 13)]

    return pd.DataFrame(rows, index=month_labels).T


def _render_system_comparison(analytics):
    """System 1 vs 2 비교 테이블."""
    st.subheader("System 1 vs System 2 비교")

    comparison = analytics.get_system_comparison()

    rows = []
    for sys_key, label in [("system_1", "System 1"), ("system_2", "System 2")]:
        s = comparison[sys_key]
        rows.append(
            {
                "시스템": label,
                "거래 수": s["total_trades"],
                "승률": f"{s['win_rate'] * 100:.1f}%",
                "Profit Factor": f"{s['profit_factor']:.2f}",
                "기대값": f"{s['expectancy']:.3f}R",
                "평균 R": f"{s['mean_r']:.2f}",
                "총 PnL": f"${s['total_pnl']:,.2f}",
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
