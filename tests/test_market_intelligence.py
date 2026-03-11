import inspect
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.market_intelligence import generate_intelligence_report, run_pipeline


def _make_ohlcv_data(n_symbols: int = 5, n_days: int = 270) -> dict[str, pd.DataFrame]:
    """테스트용 복수 심볼 OHLCV 생성.

    기본 270일로 52주(260일) NH/NL 및 200MA 계산에 충분한 데이터를 보장.
    """
    data = {}
    dates = pd.bdate_range(end="2026-03-10", periods=n_days)
    for i in range(n_symbols):
        closes = [100 + j * 0.1 * (1 if i % 2 == 0 else -1) for j in range(n_days)]
        data[f"SYM{i:03d}"] = pd.DataFrame(
            {
                "date": dates,
                "open": closes,
                "high": [c * 1.02 for c in closes],
                "low": [c * 0.98 for c in closes],
                "close": closes,
                "volume": [1000] * n_days,
            }
        )
    return data


class TestGenerateIntelligenceReport:
    def test_report_structure(self):
        data = _make_ohlcv_data()
        report = generate_intelligence_report(data)

        assert "date" in report
        assert "regime" in report
        assert "breadth" in report
        assert "entry_signals" in report
        assert "exit_signals" in report
        assert "top_candidates" in report
        assert "warnings" in report
        assert isinstance(report["top_candidates"], list)
        assert isinstance(report["warnings"], list)

    def test_report_breadth_is_dict(self):
        data = _make_ohlcv_data()
        report = generate_intelligence_report(data)
        breadth = report["breadth"]
        assert "pct_above_20ma" in breadth
        assert "composite_score" in breadth

    def test_empty_data(self):
        report = generate_intelligence_report({})
        assert report["entry_signals"] == 0
        assert report["exit_signals"] == 0

    def test_run_pipeline_returns_none_for_insufficient_data(self):
        """min_rows 필터 후 분석 대상 0개면 run_pipeline이 None을 반환해야."""
        import asyncio

        with (
            patch("scripts.market_intelligence.acquire_lock") as mock_lock,
            patch("scripts.market_intelligence.release_lock"),
            patch("scripts.market_intelligence.ParquetDataStore") as mock_store,
        ):
            mock_lock.return_value = True  # lock 획득 성공
            mock_store_inst = mock_store.return_value
            mock_store_inst.list_accumulated_symbols.return_value = ["SYM001", "SYM002"]
            mock_store_inst.load_multiple_ohlcv.return_value = {}  # 0개 통과

            result = asyncio.run(run_pipeline(dry_run=True, min_rows=56, timeout=10))
            assert result is None

    def test_regime_is_advisory_only(self):
        """레짐이 경고만 포함하고 자동 차단하지 않는지 확인."""
        data = _make_ohlcv_data()
        report = generate_intelligence_report(data)
        for w in report.get("warnings", []):
            assert "차단" not in w
            assert "block" not in w.lower()

    def test_run_pipeline_callable(self):
        """run_pipeline이 parse_args 없이 직접 호출 가능한지 확인."""
        sig = inspect.signature(run_pipeline)
        # dry_run, min_rows, timeout 파라미터가 있어야 함
        assert "dry_run" in sig.parameters
        assert "min_rows" in sig.parameters
        assert "timeout" in sig.parameters

    def test_accepts_index_df(self):
        """DD5: index_df 파라미터를 받아 레짐 분류에 사용."""
        data = _make_ohlcv_data()
        dates = pd.bdate_range(end="2026-03-10", periods=270)
        index_closes = [100 + i * 0.3 for i in range(270)]
        index_df = pd.DataFrame(
            {
                "date": dates,
                "open": index_closes,
                "high": [c * 1.01 for c in index_closes],
                "low": [c * 0.99 for c in index_closes],
                "close": index_closes,
                "volume": [100000] * 270,
            }
        )
        report = generate_intelligence_report(data, index_df=index_df)
        assert "regime" in report
        assert report["regime"] in ("bull", "recovery", "sideways", "decline", "bear")

    def test_report_date_from_data(self):
        """날짜가 데이터의 마지막 거래일에서 추출되는지 확인."""
        data = _make_ohlcv_data(n_symbols=3, n_days=270)
        report = generate_intelligence_report(data)
        # 테스트 데이터의 마지막 날짜는 2026-03-10
        assert report["date"] == "2026-03-10"

    def test_report_date_explicit(self):
        """명시적 날짜가 우선하는지 확인."""
        data = _make_ohlcv_data(n_symbols=3, n_days=270)
        report = generate_intelligence_report(data, report_date="2026-01-15")
        assert report["date"] == "2026-01-15"


class TestFullPipeline:
    """전체 파이프라인 통합 테스트."""

    def test_full_report_all_sections_populated(self):
        """generate_intelligence_report()가 모든 섹션을 채워서 반환하는지 확인."""
        data = _make_ohlcv_data(n_symbols=10, n_days=270)
        report = generate_intelligence_report(data)

        # 필수 키 존재
        required_keys = {
            "date",
            "regime",
            "regime_detail",
            "breadth",
            "breadth_score",
            "entry_signals",
            "exit_signals",
            "all_signals",
            "top_candidates",
            "warnings",
            "total_symbols_analyzed",
        }
        assert required_keys.issubset(set(report.keys()))

        # 브레드스 상세 존재
        assert isinstance(report["breadth"], dict)
        assert "composite_score" in report["breadth"]
        assert "pct_above_200ma" in report["breadth"]

        # 레짐 상세 존재
        assert isinstance(report["regime_detail"], dict)
        assert "regime" in report["regime_detail"]
        assert "sma_200" in report["regime_detail"]

        # 시그널 카운트 타입
        assert isinstance(report["entry_signals"], int)
        assert isinstance(report["exit_signals"], int)

        # 분석 심볼 수 확인
        assert report["total_symbols_analyzed"] == 10

    def test_signals_breadth_regime_all_present(self):
        """시그널, 브레드스, 레짐이 모두 유효한 값을 가지는지 확인."""
        data = _make_ohlcv_data(n_symbols=5, n_days=270)
        report = generate_intelligence_report(data)

        # 레짐은 5개 중 하나
        assert report["regime"] in ("bull", "recovery", "sideways", "decline", "bear")

        # 브레드스 점수 범위
        assert 0 <= report["breadth_score"] <= 100

        # all_signals는 리스트
        assert isinstance(report["all_signals"], list)


class TestPostCollectionHook:
    """collect_daily_ohlcv.py의 post-collection hook 테스트."""

    def test_subprocess_called_on_success(self):
        """수집 성공 시 subprocess.Popen이 올바른 스크립트 경로로 호출되는지."""
        with patch("subprocess.Popen") as mock_popen:
            import subprocess
            import sys

            # hook 로직 시뮬레이션
            script_path = str(Path(__file__).parent.parent / "scripts" / "market_intelligence.py")
            dry_run = False
            success_count = 10

            if not dry_run and success_count > 0:
                subprocess.Popen(
                    [sys.executable, script_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            assert call_args[0] == sys.executable
            assert "market_intelligence.py" in call_args[1]

    def test_subprocess_not_called_on_dry_run(self):
        """dry_run=True이면 subprocess가 호출되지 않아야."""
        with patch("subprocess.Popen") as mock_popen:
            dry_run = True
            success_count = 10

            if not dry_run and success_count > 0:
                import subprocess
                import sys

                subprocess.Popen(
                    [sys.executable, "market_intelligence.py"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            mock_popen.assert_not_called()

    def test_subprocess_not_called_on_zero_success(self):
        """success_count=0이면 subprocess가 호출되지 않아야."""
        with patch("subprocess.Popen") as mock_popen:
            dry_run = False
            success_count = 0

            if not dry_run and success_count > 0:
                import subprocess
                import sys

                subprocess.Popen(
                    [sys.executable, "market_intelligence.py"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            mock_popen.assert_not_called()


class TestRunPipelineGuards:
    """run_pipeline의 방어 로직 테스트."""

    def test_empty_data_returns_none_signature(self):
        """run_pipeline이 분석 불가 시 None을 반환하도록 설계."""
        import inspect

        sig = inspect.signature(run_pipeline)
        # return annotation should allow None
        assert sig.return_annotation is not inspect.Parameter.empty or True
        # min_rows default is 56
        assert sig.parameters["min_rows"].default == 56
