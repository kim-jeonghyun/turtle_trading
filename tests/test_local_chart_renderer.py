"""
local_chart_renderer.py 단위 테스트
- 지표 계산 정확성 (MA, MACD)
- 차트 생성 및 파일 저장
- 에러 핸들링
- 배치 렌더러
"""

import os
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.local_chart_renderer import BatchChartRenderer, calculate_indicators, render_chart
from src.universe_manager import UniverseManager


@pytest.fixture
def sample_ohlcv():
    """150일치 가상 OHLCV 데이터 (전체 테스트 공유)"""
    np.random.seed(42)
    dates = pd.date_range("2025-07-01", periods=150, freq="B")
    close = 100 + np.cumsum(np.random.randn(150) * 2)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": np.random.randint(1_000_000, 10_000_000, 150),
        },
        index=dates,
    )


@pytest.fixture
def sample_df_with_indicators(sample_ohlcv):
    """지표가 추가된 150일 DataFrame"""
    return calculate_indicators(sample_ohlcv)


class TestCalculateIndicators:
    """지표 계산 함수 테스트"""

    def test_returns_all_indicator_columns(self, sample_ohlcv):
        """MA 4종 + MACD 3종 = 7개 컬럼 반환"""
        result = calculate_indicators(sample_ohlcv)
        expected_cols = {"ma5", "ma20", "ma60", "ma120", "macd", "macd_signal", "macd_hist"}
        assert expected_cols.issubset(set(result.columns))

    def test_ma5_calculation(self, sample_ohlcv):
        """MA5는 최근 5일 종가 평균"""
        result = calculate_indicators(sample_ohlcv)
        expected = sample_ohlcv["Close"].rolling(5).mean()
        pd.testing.assert_series_equal(result["ma5"], expected, check_names=False)

    def test_ma120_has_nans_for_first_119(self, sample_ohlcv):
        """MA120은 처음 119일이 NaN"""
        result = calculate_indicators(sample_ohlcv)
        assert result["ma120"].isna().sum() == 119

    def test_macd_signal_relationship(self, sample_ohlcv):
        """MACD hist = MACD line - Signal line"""
        result = calculate_indicators(sample_ohlcv)
        valid = result.dropna(subset=["macd_hist"])
        pd.testing.assert_series_equal(
            valid["macd_hist"],
            valid["macd"] - valid["macd_signal"],
            check_names=False,
        )


class TestRenderChart:
    """차트 렌더링 테스트"""

    def test_creates_png_file(self, sample_df_with_indicators, tmp_path):
        """PNG 파일이 생성된다"""
        output = str(tmp_path / "test_chart.png")
        assert render_chart(sample_df_with_indicators, "TEST", "Test Stock", output) is True
        assert os.path.exists(output)
        assert os.path.getsize(output) > 10_000

    def test_empty_dataframe_returns_false(self, tmp_path):
        """빈 DataFrame은 False 반환"""
        output = str(tmp_path / "empty.png")
        result = render_chart(pd.DataFrame(), "EMPTY", "Empty", output)
        assert result is False

    def test_short_dataframe_still_renders(self, tmp_path):
        """30일 미만 데이터도 렌더링 (MA120 없이)"""
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=20, freq="B")
        close = 100 + np.cumsum(np.random.randn(20))
        df = pd.DataFrame(
            {
                "Open": close - 1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.random.randint(1_000_000, 10_000_000, 20),
            },
            index=dates,
        )
        df = calculate_indicators(df)
        output = str(tmp_path / "short.png")
        assert render_chart(df, "SHORT", "Short Data", output) is True
        assert os.path.exists(output)


class TestBatchChartRenderer:
    """배치 차트 렌더러 테스트"""

    @pytest.fixture
    def mock_universe(self, tmp_path):
        """2종목 미니 유니버스"""
        import yaml

        yaml_content = {
            "symbols": {
                "us_equity": [
                    {"symbol": "SPY", "name": "S&P 500 ETF", "group": "us_equity", "short_restricted": False},
                ],
                "kr_equity": [
                    {"symbol": "005930.KS", "name": "삼성전자", "group": "kr_equity", "short_restricted": True},
                ],
            }
        }
        yaml_path = tmp_path / "test_universe.yaml"
        yaml_path.write_text(yaml.dump(yaml_content))
        return UniverseManager(yaml_path=str(yaml_path))

    def _make_mock_df(self):
        np.random.seed(42)
        dates = pd.date_range("2025-07-01", periods=150, freq="B")
        close = 100 + np.cumsum(np.random.randn(150) * 2)
        return pd.DataFrame(
            {
                "Open": close - 1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.random.randint(1_000_000, 10_000_000, 150),
            },
            index=dates,
        )

    @patch("src.local_chart_renderer.yf.download")
    def test_render_all_returns_results_dict(self, mock_download, mock_universe, tmp_path):
        """render_all은 {symbol: bool} 딕셔너리를 반환"""
        mock_download.return_value = self._make_mock_df()
        renderer = BatchChartRenderer(mock_universe)
        results = renderer.render_all(output_dir=str(tmp_path))

        assert isinstance(results, dict)
        assert len(results) == 2
        assert results["SPY"] is True
        assert results["005930.KS"] is True

    @patch("src.local_chart_renderer.yf.download")
    def test_render_all_with_limit(self, mock_download, mock_universe, tmp_path):
        """limit 파라미터로 종목 수 제한"""
        mock_download.return_value = self._make_mock_df()
        renderer = BatchChartRenderer(mock_universe)
        results = renderer.render_all(output_dir=str(tmp_path), limit=1)
        assert len(results) == 1

    @patch("src.local_chart_renderer.yf.download")
    def test_download_failure_returns_false(self, mock_download, mock_universe, tmp_path):
        """yfinance 다운로드 실패 시 해당 종목만 False"""
        mock_download.return_value = pd.DataFrame()
        renderer = BatchChartRenderer(mock_universe)
        results = renderer.render_all(output_dir=str(tmp_path))
        assert results["SPY"] is False

    @patch("src.local_chart_renderer.yf.download")
    def test_handles_multiindex_columns(self, mock_download, mock_universe, tmp_path):
        """yfinance MultiIndex 컬럼 처리 검증"""
        flat_df = self._make_mock_df()
        multi_df = flat_df.copy()
        multi_df.columns = pd.MultiIndex.from_tuples([(c, "SPY") for c in flat_df.columns])
        mock_download.return_value = multi_df

        renderer = BatchChartRenderer(mock_universe)
        results = renderer.render_all(output_dir=str(tmp_path), limit=1)
        # limit=1이므로 첫 번째 심볼만 처리, MultiIndex가 정상 처리되면 True
        assert len(results) == 1
        assert list(results.values())[0] is True
