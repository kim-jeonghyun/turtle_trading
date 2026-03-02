"""
data_store.py 단위 테스트
- OHLCV 캐싱
- 거래/시그널 저장
- Atomic write
"""

import pandas as pd
import pytest

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
        signal = {"symbol": "SPY", "type": "ENTRY_LONG", "price": 500.0, "n": 5.0}
        data_store.save_signal(signal)
        loaded = data_store.load_signals()
        assert len(loaded) == 1

    def test_multiple_signals(self, data_store):
        for i in range(3):
            data_store.save_signal({"symbol": f"SYM{i}", "type": "ENTRY_LONG"})
        loaded = data_store.load_signals()
        assert len(loaded) == 3

    def test_save_signal_invalid_symbol_raises(self, data_store):
        signal = {"symbol": "'; DROP TABLE--", "type": "ENTRY"}
        with pytest.raises(ValueError):
            data_store.save_signal(signal)

    def test_save_signal_empty_symbol_raises(self, data_store):
        signal = {"symbol": "", "type": "ENTRY"}
        with pytest.raises(ValueError):
            data_store.save_signal(signal)


class TestTradeStorage:
    def test_save_trade(self, data_store):
        trade = {"symbol": "SPY", "entry_price": 500.0, "exit_price": 510.0, "pnl": 100.0}
        data_store.save_trade(trade)
        loaded = data_store.load_trades()
        assert len(loaded) == 1

    def test_save_trade_invalid_symbol_raises(self, data_store):
        trade = {"symbol": "'; DROP TABLE--", "pnl": 0.0}
        with pytest.raises(ValueError):
            data_store.save_trade(trade)

    def test_save_trade_empty_symbol_raises(self, data_store):
        trade = {"symbol": "", "pnl": 0.0}
        with pytest.raises(ValueError):
            data_store.save_trade(trade)

    def test_save_trade_missing_symbol_raises(self, data_store):
        trade = {"pnl": 0.0}
        with pytest.raises(ValueError):
            data_store.save_trade(trade)


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
        assert stats["cache_files"] == 0
        assert stats["total_size_mb"] == 0

    def test_stats_after_save(self, data_store, sample_ohlcv_df):
        data_store.save_ohlcv("SPY", sample_ohlcv_df)
        stats = data_store.get_cache_stats()
        assert stats["cache_files"] == 1
        assert stats["total_size_mb"] > 0

    def test_stats_counts_all_types(self, data_store, sample_ohlcv_df):
        data_store.save_ohlcv("SPY", sample_ohlcv_df)
        data_store.save_signal({"symbol": "SPY", "type": "ENTRY"})
        data_store.save_trade({"symbol": "SPY", "pnl": 100})

        stats = data_store.get_cache_stats()
        assert stats["cache_files"] >= 1
        assert stats["signal_files"] >= 1
        assert stats["trade_files"] >= 1


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


# ─── OHLCV Accumulation Tests ────────────────────────────────────────────────


class TestOHLCVAccumulation:
    """OHLCV 축적 저장소 테스트 (#104)"""

    def test_ohlcv_dir_created(self, temp_data_dir):
        """ParquetDataStore 초기화 시 ohlcv 디렉토리 생성"""
        store = ParquetDataStore(base_dir=str(temp_data_dir))
        assert (temp_data_dir / "ohlcv").is_dir()

    def test_initial_save(self, data_store):
        """최초 OHLCV 축적 저장"""
        df = pd.DataFrame({
            "date": pd.date_range("2026-02-25", periods=5, freq="B"),
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "volume": [1000000] * 5,
        })
        new_rows = data_store.save_ohlcv_accumulated("005930", df)
        assert new_rows == 5
        loaded = data_store.load_ohlcv_accumulated("005930")
        assert loaded is not None
        assert len(loaded) == 5

    def test_incremental_append(self, data_store):
        """증분 추가 (겹치지 않는 날짜)"""
        df1 = pd.DataFrame({
            "date": pd.date_range("2026-02-20", periods=3, freq="B"),
            "open": [100, 101, 102], "high": [101, 102, 103],
            "low": [99, 100, 101], "close": [100.5, 101.5, 102.5],
            "volume": [1000000] * 3,
        })
        df2 = pd.DataFrame({
            "date": pd.date_range("2026-02-25", periods=3, freq="B"),
            "open": [103, 104, 105], "high": [104, 105, 106],
            "low": [102, 103, 104], "close": [103.5, 104.5, 105.5],
            "volume": [1000000] * 3,
        })
        data_store.save_ohlcv_accumulated("005930", df1)
        new_rows = data_store.save_ohlcv_accumulated("005930", df2)
        loaded = data_store.load_ohlcv_accumulated("005930")
        assert len(loaded) == 6
        assert new_rows == 3

    def test_deduplication_by_date(self, data_store):
        """날짜 중복 시 최신 데이터 유지"""
        dates = pd.date_range("2026-02-25", periods=3, freq="B")
        df1 = pd.DataFrame({
            "date": dates,
            "open": [100, 101, 102], "high": [101, 102, 103],
            "low": [99, 100, 101], "close": [100.5, 101.5, 102.5],
            "volume": [1000000] * 3,
        })
        df2 = pd.DataFrame({
            "date": dates,
            "open": [200, 201, 202], "high": [201, 202, 203],
            "low": [199, 200, 201], "close": [200.5, 201.5, 202.5],
            "volume": [2000000] * 3,
        })
        data_store.save_ohlcv_accumulated("005930", df1)
        data_store.save_ohlcv_accumulated("005930", df2)
        loaded = data_store.load_ohlcv_accumulated("005930")
        assert len(loaded) == 3
        assert loaded.iloc[0]["close"] == 200.5

    def test_new_rows_with_overlap(self, data_store):
        """7일 오버랩 시 new_rows가 실제 신규 날짜만 카운트"""
        dates_old = pd.date_range("2026-02-20", periods=5, freq="B")
        df_old = pd.DataFrame({
            "date": dates_old,
            "open": range(5), "high": range(5), "low": range(5),
            "close": range(5), "volume": [1000] * 5,
        })
        dates_new = pd.date_range("2026-02-24", periods=4, freq="B")
        df_new = pd.DataFrame({
            "date": dates_new,
            "open": range(4), "high": range(4), "low": range(4),
            "close": range(4), "volume": [1000] * 4,
        })
        data_store.save_ohlcv_accumulated("005930", df_old)
        new_rows = data_store.save_ohlcv_accumulated("005930", df_new)
        assert new_rows == 1  # Only Feb 27 is genuinely new

    def test_empty_dataframe(self, data_store):
        """빈 DataFrame 저장 시도"""
        new_rows = data_store.save_ohlcv_accumulated("005930", pd.DataFrame())
        assert new_rows == 0

    def test_load_nonexistent(self, data_store):
        """존재하지 않는 종목 로드"""
        loaded = data_store.load_ohlcv_accumulated("NONEXIST")
        assert loaded is None

    def test_get_last_date(self, data_store):
        """마지막 날짜 조회"""
        df = pd.DataFrame({
            "date": pd.date_range("2026-02-25", periods=5, freq="B"),
            "open": [100.0] * 5, "high": [101.0] * 5,
            "low": [99.0] * 5, "close": [100.5] * 5,
            "volume": [1000000] * 5,
        })
        data_store.save_ohlcv_accumulated("005930", df)
        last = data_store.get_ohlcv_last_date("005930")
        assert last is not None
        assert last == df["date"].max()

    def test_get_last_date_no_data(self, data_store):
        """데이터 없을 때 None 반환"""
        assert data_store.get_ohlcv_last_date("NONEXIST") is None

    def test_cache_stats_includes_ohlcv(self, data_store):
        """cache_stats에 ohlcv_files 포함"""
        df = pd.DataFrame({
            "date": pd.date_range("2026-02-25", periods=3, freq="B"),
            "open": [100.0] * 3, "high": [101.0] * 3,
            "low": [99.0] * 3, "close": [100.5] * 3,
            "volume": [1000000] * 3,
        })
        data_store.save_ohlcv_accumulated("005930", df)
        stats = data_store.get_cache_stats()
        assert "ohlcv_files" in stats
        assert stats["ohlcv_files"] == 1

    def test_corrupted_parquet_quarantine(self, data_store):
        """손상된 Parquet 파일 격리"""
        path = data_store._get_ohlcv_path("CORRUPT")
        path.write_text("this is not a valid parquet file")
        loaded = data_store.load_ohlcv_accumulated("CORRUPT")
        assert loaded is None
        assert not path.exists()
        quarantined = list(data_store.ohlcv_dir.glob("CORRUPT_ohlcv.parquet.corrupted.*"))
        assert len(quarantined) == 1
