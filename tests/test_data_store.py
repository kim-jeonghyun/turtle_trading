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
