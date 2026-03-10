"""
리스크 상태 페이지
- N 노출 게이지
- 방향별 유닛 현황
- 상관그룹 히트맵
- 킬스위치 상태
- TradingGuard 상태
- 비용 예산 현황
"""

import json
import logging
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
import yaml

from src.position_tracker import PositionTracker
from src.types import Direction

logger = logging.getLogger(__name__)


def render(data_fetcher, data_store, universe, **kwargs):
    """리스크 상태 페이지 렌더링."""
    st.header("리스크 상태")

    # 킬스위치 + TradingGuard 상태
    col1, col2 = st.columns(2)
    with col1:
        _render_kill_switch_status()
    with col2:
        _render_trading_guard_status()

    st.divider()

    # 포지션 기반 리스크 현황
    positions = _load_open_positions()

    if not positions:
        st.info("오픈 포지션이 없어 리스크 현황을 표시할 수 없습니다.")
        return

    # N 노출 게이지
    _render_n_exposure(positions)

    st.divider()

    # 방향별 유닛
    _render_directional_units(positions)

    st.divider()

    # 상관그룹 히트맵
    _render_correlation_group_heatmap(positions, universe)

    st.divider()

    # 비용 예산
    _render_cost_budget()


def _load_open_positions():
    """오픈 포지션 로드."""
    try:
        tracker = PositionTracker()
        return tracker.get_open_positions()
    except Exception as e:
        logger.warning(f"포지션 로드 실패: {e}")
        return []


def _render_kill_switch_status():
    """킬스위치 상태 표시."""
    st.subheader("킬스위치")
    status = load_kill_switch_status()

    if status is None:
        st.warning("킬스위치 상태 파일을 읽을 수 없습니다.")
        return

    enabled = status.get("trading_enabled", True)
    if enabled:
        st.success("거래 활성화")
    else:
        st.error("거래 정지 (킬스위치 ON)")
        reason = status.get("reason", "")
        if reason:
            st.caption(f"사유: {reason}")


def load_kill_switch_status():
    """킬스위치 YAML 파일 파싱.

    Returns:
        dict or None if file cannot be read.
    """
    path = Path("config/system_status.yaml")
    try:
        if not path.exists():
            return None
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _render_trading_guard_status():
    """TradingGuard 상태 표시."""
    st.subheader("TradingGuard")
    state = load_trading_guard_state()

    if state is None:
        st.info("TradingGuard 상태 파일이 없습니다.")
        return

    daily_loss = state.get("daily_loss", 0)
    daily_orders = state.get("daily_order_count", 0)
    cb_active = state.get("circuit_breaker_active", False)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("일일 손실", f"${daily_loss:,.2f}")
    with col2:
        st.metric("일일 주문 수", daily_orders)
    with col3:
        if cb_active:
            st.error("서킷브레이커 작동 중")
        else:
            st.success("정상")


def load_trading_guard_state():
    """TradingGuard JSON 상태 파일 파싱.

    Returns:
        dict or None if file cannot be read.
    """
    path = Path("data/trading_guard_state.json")
    try:
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _render_n_exposure(positions):
    """N 노출 게이지."""
    st.subheader("N 노출")

    total_n = sum(pos.entry_n * pos.units for pos in positions)
    limit = 10.0

    progress = min(total_n / limit, 1.0)
    st.progress(progress, text=f"N 노출: {total_n:.2f} / {limit:.1f}")

    if total_n > limit * 0.8:
        st.warning(f"N 노출이 한도의 {total_n / limit * 100:.0f}%에 도달했습니다.")


def _render_directional_units(positions):
    """방향별 유닛 현황."""
    st.subheader("방향별 유닛")

    long_units = sum(pos.units for pos in positions if pos.direction == Direction.LONG)
    short_units = sum(pos.units for pos in positions if pos.direction == Direction.SHORT)
    limit = 12

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Long 유닛", f"{long_units} / {limit}")
        st.progress(min(long_units / limit, 1.0))
    with col2:
        st.metric("Short 유닛", f"{short_units} / {limit}")
        st.progress(min(short_units / limit, 1.0))


def _render_correlation_group_heatmap(positions, universe):
    """상관그룹 히트맵."""
    st.subheader("상관그룹별 유닛 현황")

    # 그룹별 유닛 집계
    group_units = {}
    for pos in positions:
        try:
            group = universe.get_group(pos.symbol)
        except Exception:
            group = "기타"
        group_name = group if isinstance(group, str) else str(group)
        group_units[group_name] = group_units.get(group_name, 0) + pos.units

    if not group_units:
        st.info("그룹별 데이터가 없습니다.")
        return

    limit = 6
    groups = sorted(group_units.keys())
    units = [group_units[g] for g in groups]
    colors = ["green" if u <= limit * 0.5 else "orange" if u <= limit * 0.8 else "red" for u in units]

    fig = go.Figure(
        go.Bar(
            x=units,
            y=groups,
            orientation="h",
            marker_color=colors,
            text=[f"{u}/{limit}" for u in units],
            textposition="auto",
        )
    )
    fig.add_vline(x=limit, line_dash="dash", line_color="red", annotation_text="한도")
    fig.update_layout(title="상관그룹별 유닛", xaxis_title="유닛 수", height=max(300, len(groups) * 35))
    st.plotly_chart(fig, use_container_width=True)


def _render_cost_budget():
    """비용 예산 현황."""
    st.subheader("비용 예산")
    try:
        cost_path = Path("data/cost_budget.json")
        if not cost_path.exists():
            st.info("비용 예산 데이터가 없습니다.")
            return

        with open(cost_path) as f:
            cost_data = json.load(f)

        budget = cost_data.get("budget", 0)
        used = cost_data.get("used", 0)

        if budget > 0:
            st.progress(min(used / budget, 1.0), text=f"비용: ${used:,.2f} / ${budget:,.2f}")
        else:
            st.metric("비용 사용", f"${used:,.2f}")
    except Exception:
        st.info("비용 예산 데이터를 불러올 수 없습니다.")
