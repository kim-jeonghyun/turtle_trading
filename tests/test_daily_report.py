"""scripts/daily_report.py 단위 테스트"""

from unittest.mock import MagicMock, patch

import pandas as pd

from scripts.daily_report import generate_pnl_summary, generate_report


class TestGenerateReport:
    def test_daily_report_includes_pnl_summary(self):
        """generate_report 결과에 pnl_summary 섹션이 포함된다"""
        mock_data_store = MagicMock()
        mock_data_store.load_signals.return_value = pd.DataFrame()
        mock_data_store.load_trades.return_value = pd.DataFrame()
        mock_data_store.get_cache_stats.return_value = {"cache_files": 0, "total_size_mb": 0.0}

        pnl_mock = {"realized_pnl": 0, "unrealized_pnl": "N/A"}
        with patch("scripts.daily_report.get_market_status", return_value="closed"):
            with patch("scripts.daily_report.generate_cost_summary", return_value={}):
                with patch("scripts.daily_report.generate_pnl_summary", return_value=pnl_mock):
                    report = generate_report(mock_data_store)

        assert "pnl_summary" in report
        assert "realized_pnl" in report["pnl_summary"]


class TestGeneratePnlSummary:
    def test_pnl_summary_no_trades(self):
        """거래가 없으면 realized_pnl=0, unrealized_pnl=N/A"""
        result = generate_pnl_summary("2026-03-10", pd.DataFrame(), None, None)
        assert result["realized_pnl"] == 0.0
        assert result["unrealized_pnl"] == "N/A"

    def test_pnl_summary_with_realized(self):
        """오늘 청산된 거래의 실현 PnL이 합산된다"""
        trades = pd.DataFrame(
            {
                "exit_date": ["2026-03-10", "2026-03-10", "2026-03-09"],
                "pnl": [100.0, 200.0, 500.0],
            }
        )
        result = generate_pnl_summary("2026-03-10", trades, None, None)
        assert result["realized_pnl"] == 300.0

    def test_daily_report_spot_price_failure_graceful(self):
        """spot_price API 실패 시 미실현 PnL은 N/A로 표시"""
        mock_tracker = MagicMock()
        mock_pos = MagicMock()
        mock_pos.symbol = "SPY"
        mock_pos.direction.value = "LONG"
        mock_pos.entry_price = 500.0
        mock_pos.total_shares = 10
        mock_tracker.get_open_positions.return_value = [mock_pos]

        with patch("scripts.daily_report.SpotPriceFetcher") as mock_fetcher_cls:
            mock_fetcher = MagicMock()
            mock_fetcher_cls.return_value = mock_fetcher

            async def _raise(*a, **kw):
                raise ConnectionError("API down")

            mock_fetcher.fetch_spot_price = _raise

            result = generate_pnl_summary("2026-03-10", pd.DataFrame(), mock_tracker, None)

        assert result["unrealized_pnl"] == "N/A"
        assert result["realized_pnl"] == 0.0
