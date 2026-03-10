"""
Streamlit 대시보드 테스트
- 페이지 모듈 임포트 검증
- init_components 목 테스트
- performance 페이지 데이터 변환 로직
- risk 페이지 상태 파일 파싱
"""

import json
from unittest.mock import patch

import pandas as pd


class TestPageImports:
    """각 페이지 모듈이 임포트 에러 없이 로드되는지 확인."""

    def test_import_dashboard(self):
        from pages import dashboard

        assert hasattr(dashboard, "render")

    def test_import_chart_analysis(self):
        from pages import chart_analysis

        assert hasattr(chart_analysis, "render")

    def test_import_signals(self):
        from pages import signals

        assert hasattr(signals, "render")

    def test_import_trades(self):
        from pages import trades

        assert hasattr(trades, "render")

    def test_import_backtest(self):
        from pages import backtest

        assert hasattr(backtest, "render")

    def test_import_performance(self):
        from pages import performance

        assert hasattr(performance, "render")

    def test_import_risk(self):
        from pages import risk

        assert hasattr(risk, "render")

    def test_pages_package_init(self):
        import pages

        assert pages is not None


class TestPerformanceDataTransformation:
    """performance 페이지의 데이터 변환 로직 단위 테스트."""

    def test_build_monthly_heatmap_data_basic(self):
        from pages.performance import build_monthly_heatmap_data

        monthly = {
            "2025-01": 1000.0,
            "2025-02": -500.0,
            "2025-06": 2000.0,
        }

        result = build_monthly_heatmap_data(monthly)

        assert isinstance(result, pd.DataFrame)
        assert "2025" in result.index
        # 12개 월 컬럼
        assert len(result.columns) == 12
        # 1월 값 확인
        assert result.loc["2025", "1"] == 1000.0
        # 2월 값 확인
        assert result.loc["2025", "2"] == -500.0
        # 6월 값 확인
        assert result.loc["2025", "6"] == 2000.0
        # 비어있는 월은 None (pandas에서 NaN으로 표현)
        assert pd.isna(result.loc["2025", "3"])

    def test_build_monthly_heatmap_data_empty(self):
        from pages.performance import build_monthly_heatmap_data

        result = build_monthly_heatmap_data({})
        assert result.empty

    def test_build_monthly_heatmap_data_multi_year(self):
        from pages.performance import build_monthly_heatmap_data

        monthly = {
            "2024-12": 500.0,
            "2025-01": 1000.0,
        }

        result = build_monthly_heatmap_data(monthly)
        assert len(result.index) == 2
        assert "2024" in result.index
        assert "2025" in result.index

    def test_filter_by_period_none_returns_all(self):
        from pages.performance import _filter_by_period

        trades = [
            {"exit_date": "2020-01-01", "pnl": 100},
            {"exit_date": "2025-06-01", "pnl": 200},
        ]
        result = _filter_by_period(trades, None)
        assert len(result) == 2

    def test_filter_by_period_filters_old(self):
        from pages.performance import _filter_by_period

        trades = [
            {"exit_date": "2020-01-01", "pnl": 100},
            {"exit_date": "2099-06-01", "pnl": 200},
        ]
        result = _filter_by_period(trades, 1)  # 1 month
        # 2020-01-01 is way too old
        assert len(result) == 1
        assert result[0]["pnl"] == 200

    def test_filter_by_period_bad_date_skipped(self):
        from pages.performance import _filter_by_period

        trades = [
            {"exit_date": "not-a-date", "pnl": 100},
            {"exit_date": "2099-06-01", "pnl": 200},
        ]
        result = _filter_by_period(trades, 1)
        assert len(result) == 1


class TestRiskStateFileParsing:
    """risk 페이지의 상태 파일 파싱 테스트."""

    def test_load_kill_switch_status_missing_file(self):
        from pages.risk import load_kill_switch_status

        with patch("pages.risk.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            result = load_kill_switch_status()
            assert result is None

    def test_load_kill_switch_status_valid(self, tmp_path):
        from pages.risk import load_kill_switch_status

        yaml_content = "trading_enabled: true\nreason: ''\n"
        status_file = tmp_path / "system_status.yaml"
        status_file.write_text(yaml_content)

        with patch("pages.risk.Path", return_value=status_file):
            result = load_kill_switch_status()

        assert result is not None
        assert result["trading_enabled"] is True

    def test_load_trading_guard_state_missing_file(self):
        from pages.risk import load_trading_guard_state

        with patch("pages.risk.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            result = load_trading_guard_state()
            assert result is None

    def test_load_trading_guard_state_valid(self, tmp_path):
        from pages.risk import load_trading_guard_state

        state = {
            "daily_loss": -1500.0,
            "daily_order_count": 5,
            "circuit_breaker_active": False,
        }
        state_file = tmp_path / "trading_guard_state.json"
        state_file.write_text(json.dumps(state))

        with patch("pages.risk.Path", return_value=state_file):
            result = load_trading_guard_state()

        assert result is not None
        assert result["daily_loss"] == -1500.0
        assert result["daily_order_count"] == 5
        assert result["circuit_breaker_active"] is False

    def test_load_trading_guard_state_corrupt_json(self, tmp_path):
        from pages.risk import load_trading_guard_state

        state_file = tmp_path / "trading_guard_state.json"
        state_file.write_text("{corrupt json")

        with patch("pages.risk.Path", return_value=state_file):
            result = load_trading_guard_state()

        assert result is None


class TestTradesRMultiple:
    """trades 페이지의 R-multiple 계산 테스트."""

    def test_add_r_multiple_column_with_data(self):
        from pages.trades import _add_r_multiple_column

        df = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "entry_price": 100.0,
                    "stop_loss": 95.0,
                    "pnl": 500.0,
                    "total_shares": 100,
                }
            ]
        )

        result = _add_r_multiple_column(df)
        assert "R-multiple" in result.columns
        # R = 500 / (|100-95| * 100) = 500 / 500 = 1.0
        assert result.iloc[0]["R-multiple"] == 1.0

    def test_add_r_multiple_column_missing_fields(self):
        from pages.trades import _add_r_multiple_column

        df = pd.DataFrame([{"symbol": "SPY", "pnl": 500.0}])
        result = _add_r_multiple_column(df)
        assert "R-multiple" in result.columns
        assert result.iloc[0]["R-multiple"] == "N/A"

    def test_add_r_multiple_existing_column(self):
        from pages.trades import _add_r_multiple_column

        df = pd.DataFrame([{"symbol": "SPY", "r_multiple": 1.5}])
        result = _add_r_multiple_column(df)
        # Should keep existing column unchanged
        assert "r_multiple" in result.columns


class TestAppVersion:
    """app.py 버전 조회 테스트."""

    def test_get_version_fallback(self):
        """패키지 미설치 시 unknown 반환."""
        import importlib.metadata

        def _get_version_standalone():
            try:
                return importlib.metadata.version("turtle-trading")
            except importlib.metadata.PackageNotFoundError:
                return "unknown"

        with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
            result = _get_version_standalone()
            assert result == "unknown"

    def test_get_version_found(self):
        """패키지 설치 시 버전 반환."""
        import importlib.metadata

        def _get_version_standalone():
            try:
                return importlib.metadata.version("turtle-trading")
            except importlib.metadata.PackageNotFoundError:
                return "unknown"

        with patch("importlib.metadata.version", return_value="3.9.0"):
            result = _get_version_standalone()
            assert result == "3.9.0"


class TestAppRenderCallsKeywordArgs:
    """app.py의 render() 호출이 키워드 인자를 사용하는지 검증."""

    def test_all_render_calls_use_keyword_args(self):
        """app.py의 모든 render() 호출 7개가 symbols/period 키워드 인자를 사용한다"""
        import ast
        from pathlib import Path

        source = Path("app.py").read_text()
        tree = ast.parse(source)

        render_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "render":
                    render_calls.append(node)

        # 7개 페이지 모듈의 render() 호출이 모두 존재해야 한다
        assert len(render_calls) == 7, f"Expected 7 render() calls, found {len(render_calls)}"

        for node in render_calls:
            kw_names = [kw.arg for kw in node.keywords]
            # 모든 render() 호출은 symbols와 period를 키워드로 전달해야 한다
            assert "symbols" in kw_names, f"render() call at line {node.lineno} missing 'symbols' keyword"
            assert "period" in kw_names, f"render() call at line {node.lineno} missing 'period' keyword"
            # 위치 인자는 data_fetcher, data_store, universe 3개만 허용
            assert len(node.args) == 3, f"render() call at line {node.lineno} has {len(node.args)} positional args, expected 3"
