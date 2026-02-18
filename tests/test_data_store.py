"""
data_store.py 단위 테스트
- OHLCV 캐싱
- 거래/시그널 저장
- Atomic write
"""

import pytest
import pandas as pd
from pathlib import Path
from src.data_store import ParquetDataStore


@pytest.fixture
def data_store(temp_data_dir):
    return ParquetDataStore(base_dir=str(temp_data_dir))


class TestOHLCVCache:
    def test_save_and_load(self, data_store, sample_ohlcv_df):
        data_store.save_ohlcv("SPY", sample_ohlcv_df)
        loaded = data_store.load_ohlcv("SPY")

        assert loaded is not None
        assert len(loaded) == len(sample_ohlcv_df)

    def test_cache_miss(self, data_store):
        loaded = data_store.load_ohlcv("NONEXISTENT")
        assert loaded is None

    def test_special_symbol(self, data_store, sample_ohlcv_df):
        """특수문자 포함 심볼 (한국 주식)"""
        data_store.save_ohlcv("005930.KS", sample_ohlcv_df)
        loaded = data_store.load_ohlcv("005930.KS")
        assert loaded is not None


class TestSignalStorage:
    def test_save_signal(self, data_store):
        signal = {
            "symbol": "SPY",
            "type": "ENTRY_LONG",
            "price": 500.0,
            "n": 5.0
        }
        data_store.save_signal(signal)
        loaded = data_store.load_signals()
        assert len(loaded) == 1

    def test_multiple_signals(self, data_store):
        for i in range(3):
            data_store.save_signal({"symbol": f"SYM{i}", "type": "ENTRY_LONG"})
        loaded = data_store.load_signals()
        assert len(loaded) == 3


class TestTradeStorage:
    def test_save_trade(self, data_store):
        trade = {
            "symbol": "SPY",
            "entry_price": 500.0,
            "exit_price": 510.0,
            "pnl": 100.0
        }
        data_store.save_trade(trade)
        loaded = data_store.load_trades()
        assert len(loaded) == 1


class TestIndicatorStorage:
    def test_save_and_load_indicators(self, data_store, sample_ohlcv_df):
        data_store.save_indicators("SPY", sample_ohlcv_df)
        loaded = data_store.load_indicators("SPY")
        assert loaded is not None
        assert len(loaded) == len(sample_ohlcv_df)

    def test_load_indicators_missing(self, data_store):
        loaded = data_store.load_indicators("NONEXISTENT")
        assert loaded is None


class TestLoadTradesFiltered:
    def test_load_trades_empty(self, data_store):
        loaded = data_store.load_trades()
        assert loaded.empty

    def test_load_trades_with_start_date(self, data_store):
        trade = {"symbol": "SPY", "pnl": 100.0}
        data_store.save_trade(trade)
        # Load with a start date far in the past - should include today's trades
        loaded = data_store.load_trades(start_date="2020-01-01")
        assert len(loaded) >= 1

    def test_load_trades_with_end_date_excludes_future(self, data_store):
        trade = {"symbol": "SPY", "pnl": 100.0}
        data_store.save_trade(trade)
        # Load with an end date far in the past - should exclude today's trades
        loaded = data_store.load_trades(end_date="2020-01-01")
        assert loaded.empty

    def test_load_trades_both_dates(self, data_store):
        trade = {"symbol": "SPY", "pnl": 100.0}
        data_store.save_trade(trade)
        loaded = data_store.load_trades(start_date="2020-01-01", end_date="2030-12-31")
        assert len(loaded) >= 1


class TestLoadSignalsFiltered:
    def test_load_signals_with_date(self, data_store):
        signal = {"symbol": "SPY", "type": "ENTRY_LONG"}
        data_store.save_signal(signal)
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        loaded = data_store.load_signals(date=today)
        assert len(loaded) >= 1

    def test_load_signals_with_wrong_date(self, data_store):
        signal = {"symbol": "SPY", "type": "ENTRY_LONG"}
        data_store.save_signal(signal)
        loaded = data_store.load_signals(date="2020-01-01")
        assert loaded.empty


class TestCleanupOldCache:
    def test_cleanup_removes_old_files(self, data_store, sample_ohlcv_df):
        import os
        import time
        data_store.save_ohlcv("OLD_SYMBOL", sample_ohlcv_df)
        # Manually set file modification time to 30 days ago
        cache_path = data_store._get_cache_path("OLD_SYMBOL", "ohlcv")
        old_time = time.time() - (30 * 24 * 3600)
        os.utime(cache_path, (old_time, old_time))

        data_store.cleanup_old_cache(max_age_days=7)

        assert not cache_path.exists()

    def test_cleanup_keeps_recent_files(self, data_store, sample_ohlcv_df):
        data_store.save_ohlcv("RECENT", sample_ohlcv_df)
        data_store.cleanup_old_cache(max_age_days=7)
        cache_path = data_store._get_cache_path("RECENT", "ohlcv")
        assert cache_path.exists()


class TestCacheStats:
    def test_empty_stats(self, data_store):
        stats = data_store.get_cache_stats()
        assert stats['cache_files'] == 0
        assert stats['total_size_mb'] == 0

    def test_stats_after_save(self, data_store, sample_ohlcv_df):
        data_store.save_ohlcv("SPY", sample_ohlcv_df)
        stats = data_store.get_cache_stats()
        assert stats['cache_files'] == 1
        assert stats['total_size_mb'] > 0

    def test_stats_counts_all_types(self, data_store, sample_ohlcv_df):
        data_store.save_ohlcv("SPY", sample_ohlcv_df)
        data_store.save_signal({"symbol": "SPY", "type": "ENTRY"})
        data_store.save_trade({"symbol": "SPY", "pnl": 100})

        stats = data_store.get_cache_stats()
        assert stats['cache_files'] >= 1
        assert stats['signal_files'] >= 1
        assert stats['trade_files'] >= 1


class TestOHLCVCacheValidity:
    def test_cache_expired(self, data_store, sample_ohlcv_df):
        import os
        import time
        data_store.save_ohlcv("EXPIRED", sample_ohlcv_df)
        # Set modification time to 48 hours ago
        cache_path = data_store._get_cache_path("EXPIRED", "ohlcv")
        old_time = time.time() - (48 * 3600)
        os.utime(cache_path, (old_time, old_time))

        loaded = data_store.load_ohlcv("EXPIRED", max_age_hours=24)
        assert loaded is None
