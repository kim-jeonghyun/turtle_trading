"""
차트 생성 통합 테스트
- BatchChartRenderer end-to-end 흐름
- scripts/fetch_universe_charts.py CLI 진입점
- 실제 유니버스 설정 연동
"""

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import yaml

from src.local_chart_renderer import BatchChartRenderer, calculate_indicators, render_chart
from src.universe_manager import UniverseManager


@pytest.fixture
def mini_universe(tmp_path):
    """3종목 미니 유니버스 (US + KR)"""
    yaml_content = {
        "symbols": {
            "us_equity": [
                {"symbol": "SPY", "name": "S&P 500 ETF", "group": "us_equity", "short_restricted": False},
                {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "group": "us_equity", "short_restricted": False},
            ],
            "kr_equity": [
                {"symbol": "005930.KS", "name": "삼성전자", "group": "kr_equity", "short_restricted": True},
            ],
        }
    }
    yaml_path = tmp_path / "universe.yaml"
    yaml_path.write_text(yaml.dump(yaml_content))
    return UniverseManager(yaml_path=str(yaml_path))


def _make_ohlcv(n=150):
    np.random.seed(42)
    dates = pd.date_range("2025-07-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": np.random.randint(1_000_000, 10_000_000, n),
        },
        index=dates,
    )


class TestEndToEndFlow:
    """데이터 다운로드 → 지표 계산 → 차트 렌더링 전체 파이프라인"""

    @patch("src.local_chart_renderer.yf.download")
    def test_full_pipeline_creates_png_files(self, mock_download, mini_universe, tmp_path):
        """3종목 전체 파이프라인: 각각 PNG 파일이 생성된다"""
        mock_download.return_value = _make_ohlcv()
        renderer = BatchChartRenderer(mini_universe)
        results = renderer.render_all(output_dir=str(tmp_path))

        assert len(results) == 3
        assert all(v is True for v in results.values())

        # PNG 파일이 실제 존재하는지 확인
        png_files = list(tmp_path.glob("*.png"))
        assert len(png_files) == 3

    @patch("src.local_chart_renderer.yf.download")
    def test_partial_failure_does_not_block_others(self, mock_download, mini_universe, tmp_path):
        """일부 종목 실패 시 다른 종목은 정상 처리"""
        call_count = [0]
        good_df = _make_ohlcv()

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return pd.DataFrame()  # 첫 번째 종목 실패
            return good_df

        mock_download.side_effect = side_effect
        renderer = BatchChartRenderer(mini_universe)
        results = renderer.render_all(output_dir=str(tmp_path))

        assert len(results) == 3
        assert sum(v is True for v in results.values()) == 2
        assert sum(v is False for v in results.values()) == 1


class TestRealUniverseConfig:
    """실제 config/universe.yaml 연동 테스트"""

    @pytest.fixture
    def real_universe_path(self):
        path = Path(__file__).parent.parent / "config" / "universe.yaml"
        if not path.exists():
            pytest.skip("config/universe.yaml not found")
        return path

    def test_all_symbols_are_renderable(self, real_universe_path):
        """실제 유니버스의 모든 심볼이 BatchChartRenderer에 로드된다"""
        um = UniverseManager(yaml_path=str(real_universe_path))
        symbols = um.get_enabled_symbols()
        assert len(symbols) >= 10  # 기본 유니버스 최소 종목 수

        renderer = BatchChartRenderer(um)
        assert renderer.universe_manager is um

    @patch("src.local_chart_renderer.yf.download")
    def test_korean_symbol_filename_sanitization(self, mock_download, real_universe_path, tmp_path):
        """한국 종목명에 특수문자가 있어도 파일명이 안전하게 생성된다"""
        mock_download.return_value = _make_ohlcv()
        um = UniverseManager(yaml_path=str(real_universe_path))
        renderer = BatchChartRenderer(um)
        results = renderer.render_all(output_dir=str(tmp_path), limit=3)

        assert len(results) == 3
        for png in tmp_path.glob("*.png"):
            # 파일명에 금지 문자가 없어야 함
            assert not any(c in png.name for c in r'\/*?:"<>|')


class TestScriptEntryPoint:
    """scripts/fetch_universe_charts.py CLI 테스트"""

    @patch("src.local_chart_renderer.yf.download")
    def test_script_imports_and_runs(self, mock_download, tmp_path):
        """스크립트가 import 가능하고 main()이 정상 실행된다"""
        mock_download.return_value = _make_ohlcv()

        import importlib
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent))
        mod = importlib.import_module("scripts.fetch_universe_charts")
        assert hasattr(mod, "main")
