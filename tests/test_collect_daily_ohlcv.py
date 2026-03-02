"""
collect_daily_ohlcv.py 단위 테스트
- 설정 로드
- 심볼 추출 (market 페어 반환)
- 증분 수집 로직
- 에러 핸들링
- 공휴일 스킵 (B1)
- 마켓 힌트 yfinance 폴백 (B2)
- 데이터 유효성 검증 (B4)
- 알림 전송
"""

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (scripts/는 패키지가 아니므로 sys.path 필요)
# 기존 test_check_positions.py와 동일한 패턴
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import yaml

from scripts.collect_daily_ohlcv import (
    CollectionResult,
    collect_symbol,
    determine_start_date,
    get_collection_symbols,
    load_collection_config,
    parse_args,
    run_collection,
    send_collection_summary,
    validate_ohlcv,
)
from src.data_store import ParquetDataStore
from src.notifier import NotificationLevel


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def sample_config(tmp_path):
    """테스트용 수집 설정 파일 생성"""
    config = {
        "collection": {
            "rate_limit_seconds": 0.0,
            "max_retries": 1,
            "initial_lookback_days": 30,
            "storage_dir": "data/ohlcv",
        },
        "symbols": {
            "kospi_200": ["005930", "000660", "035420"],
            "kosdaq_150": ["247540", "091990"],
        },
    }
    config_path = tmp_path / "ohlcv_collection.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


@pytest.fixture
def sample_config_dict():
    """설정 딕셔너리 (파일 없이)"""
    return {
        "collection": {
            "rate_limit_seconds": 0.0,
            "max_retries": 1,
            "initial_lookback_days": 30,
        },
        "symbols": {
            "kospi_200": ["005930", "000660"],
            "kosdaq_150": ["247540"],
        },
    }


@pytest.fixture
def ohlcv_data_store(tmp_path):
    """OHLCV 테스트용 ParquetDataStore"""
    return ParquetDataStore(base_dir=str(tmp_path))


@pytest.fixture
def sample_fdr_df():
    """FDR 반환 형태의 OHLCV DataFrame"""
    dates = pd.date_range("2026-02-25", periods=5, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "high": [101.0, 102.0, 103.0, 104.0, 105.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "volume": [1000000] * 5,
        }
    )


# ─── Config Loading ────────────────────────────────────────────────────────


class TestLoadCollectionConfig:
    def test_load_valid_config(self, sample_config):
        config = load_collection_config(sample_config)
        assert "collection" in config
        assert "symbols" in config

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_collection_config(tmp_path / "nonexistent.yaml")

    def test_load_empty_config(self, tmp_path):
        empty_path = tmp_path / "empty.yaml"
        empty_path.write_text("")
        with pytest.raises(ValueError):
            load_collection_config(empty_path)


# ─── Symbol Extraction ─────────────────────────────────────────────────────


class TestGetCollectionSymbols:
    def test_all_symbols_from_config(self, sample_config_dict):
        """설정에서 (symbol, market) 튜플 리스트 반환"""
        symbols = get_collection_symbols(sample_config_dict)
        assert len(symbols) == 3
        symbol_codes = [s[0] for s in symbols]
        assert "005930" in symbol_codes
        assert "247540" in symbol_codes

    def test_market_hint_from_group(self, sample_config_dict):
        """kospi 그룹은 kospi, kosdaq 그룹은 kosdaq 마켓 할당"""
        symbols = get_collection_symbols(sample_config_dict)
        symbol_map = {s[0]: s[1] for s in symbols}
        assert symbol_map["005930"] == "kospi"
        assert symbol_map["247540"] == "kosdaq"

    def test_override_symbols(self, sample_config_dict):
        """CLI 오버라이드 시 기본 market은 kospi"""
        symbols = get_collection_symbols(sample_config_dict, ["999999", "888888"])
        assert symbols == [("999999", "kospi"), ("888888", "kospi")]

    def test_deduplication(self):
        config = {"symbols": {"group_a": ["005930", "000660"], "group_b": ["005930"]}}
        symbols = get_collection_symbols(config)
        symbol_codes = [s[0] for s in symbols]
        assert symbol_codes.count("005930") == 1
        assert len(symbols) == 2

    def test_empty_config(self):
        config = {"symbols": {}}
        symbols = get_collection_symbols(config)
        assert symbols == []

    def test_no_symbols_key(self):
        config = {}
        symbols = get_collection_symbols(config)
        assert symbols == []


# ─── Data Validation (B4) ─────────────────────────────────────────────────


class TestValidateOHLCV:
    def test_valid_data_passes(self, sample_fdr_df):
        """유효한 데이터는 그대로 반환"""
        result = validate_ohlcv(sample_fdr_df.copy())
        assert len(result) == len(sample_fdr_df)

    def test_drops_null_close(self):
        """close가 null인 행 제거"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=3),
                "open": [100, 101, 102],
                "high": [101, 102, 103],
                "low": [99, 100, 101],
                "close": [100.5, None, 102.5],
                "volume": [1000] * 3,
            }
        )
        result = validate_ohlcv(df)
        assert len(result) == 2

    def test_drops_negative_prices(self):
        """음수 가격 행 제거"""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=3),
                "open": [100, -1, 102],
                "high": [101, 102, 103],
                "low": [99, 100, 101],
                "close": [100.5, 101.5, 102.5],
                "volume": [1000] * 3,
            }
        )
        result = validate_ohlcv(df)
        assert len(result) == 2

    def test_raises_on_missing_columns(self):
        """필수 컬럼 누락 시 ValueError"""
        df = pd.DataFrame({"date": [1], "open": [1], "close": [1]})
        with pytest.raises(ValueError, match="필수 컬럼 누락"):
            validate_ohlcv(df)

    def test_column_normalization(self):
        """대문자 컬럼명도 소문자로 정규화"""
        df = pd.DataFrame(
            {
                "Date": pd.date_range("2026-01-01", periods=1),
                "Open": [100],
                "High": [101],
                "Low": [99],
                "Close": [100.5],
                "Volume": [1000],
            }
        )
        result = validate_ohlcv(df)
        assert all(c.islower() for c in result.columns)
        assert len(result) == 1


# ─── Start Date Determination ──────────────────────────────────────────────


class TestDetermineStartDate:
    def test_no_existing_data(self, ohlcv_data_store):
        """기존 데이터 없으면 lookback_days 만큼 과거"""
        start = determine_start_date("005930", ohlcv_data_store, 30)
        expected = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        assert start == expected

    def test_with_existing_data(self, ohlcv_data_store, sample_fdr_df):
        """기존 데이터 있으면 마지막 날짜 - 7일 (B3)"""
        ohlcv_data_store.save_ohlcv_accumulated("005930", sample_fdr_df)
        start = determine_start_date("005930", ohlcv_data_store, 730)
        last = sample_fdr_df["date"].max()
        expected = (last - timedelta(days=7)).strftime("%Y-%m-%d")
        assert start == expected

    def test_target_date_overrides(self, ohlcv_data_store, sample_fdr_df):
        """--date 옵션이 있으면 해당 날짜 사용"""
        ohlcv_data_store.save_ohlcv_accumulated("005930", sample_fdr_df)
        start = determine_start_date("005930", ohlcv_data_store, 730, target_date="2026-01-15")
        assert start == "2026-01-15"


# ─── Single Symbol Collection ─────────────────────────────────────────────


class TestCollectSymbol:
    def test_successful_fdr_collection(self, ohlcv_data_store, sample_fdr_df):
        """FDR 성공 시 저장"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.return_value = sample_fdr_df

        success, rows, msg = collect_symbol(
            "005930", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01",
        )
        assert success is True
        assert rows == 5
        assert msg == "ok"

    def test_fdr_fallback_to_yfinance_ks_for_kospi(self, ohlcv_data_store, sample_fdr_df):
        """KOSPI 종목: FDR 실패 시 yfinance .KS 먼저 폴백 (B2)"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.return_value = pd.DataFrame()
        fetcher.fetch_yfinance.side_effect = [sample_fdr_df]

        success, rows, msg = collect_symbol(
            "005930", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01", market="kospi",
        )
        assert success is True
        fetcher.fetch_yfinance.assert_called_once_with("005930.KS", start="2026-02-25", end="2026-03-01")

    def test_fdr_fallback_to_yfinance_kq_for_kosdaq(self, ohlcv_data_store, sample_fdr_df):
        """KOSDAQ 종목: FDR 실패 시 yfinance .KQ 먼저 폴백 (B2)"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.return_value = pd.DataFrame()
        fetcher.fetch_yfinance.side_effect = [sample_fdr_df]

        success, rows, msg = collect_symbol(
            "247540", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01", market="kosdaq",
        )
        assert success is True
        fetcher.fetch_yfinance.assert_called_once_with("247540.KQ", start="2026-02-25", end="2026-03-01")

    def test_fdr_fallback_second_suffix(self, ohlcv_data_store, sample_fdr_df):
        """첫 yfinance 접미사 실패 시 두 번째 접미사 시도"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.return_value = pd.DataFrame()
        fetcher.fetch_yfinance.side_effect = [pd.DataFrame(), sample_fdr_df]

        success, rows, msg = collect_symbol(
            "247540", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01", market="kospi",
        )
        assert success is True
        assert fetcher.fetch_yfinance.call_count == 2

    def test_all_sources_empty_returns_skip(self, ohlcv_data_store):
        """B1: 모든 소스 빈 데이터 시 None 반환 (skip)"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.return_value = pd.DataFrame()
        fetcher.fetch_yfinance.return_value = pd.DataFrame()

        success, rows, msg = collect_symbol(
            "999999", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01",
        )
        assert success is None
        assert rows == 0
        assert msg == "no-data"

    def test_dry_run_no_save(self, ohlcv_data_store, sample_fdr_df):
        """dry-run 시 저장 안 함"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.return_value = sample_fdr_df

        success, rows, msg = collect_symbol(
            "005930", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01", dry_run=True,
        )
        assert success is True
        assert msg == "dry-run"
        assert ohlcv_data_store.load_ohlcv_accumulated("005930") is None

    def test_retry_on_exception(self, ohlcv_data_store, sample_fdr_df):
        """예외 발생 시 재시도"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.side_effect = [ConnectionError("network"), sample_fdr_df]

        with patch("scripts.collect_daily_ohlcv.time.sleep"):
            success, rows, msg = collect_symbol(
                "005930", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01", max_retries=1,
            )
        assert success is True
        assert fetcher.fetch_fdr.call_count == 2

    def test_retry_exhausted(self, ohlcv_data_store):
        """재시도 소진 시 실패"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.side_effect = ConnectionError("persistent")

        with patch("scripts.collect_daily_ohlcv.time.sleep"):
            success, rows, msg = collect_symbol(
                "005930", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01", max_retries=1,
            )
        assert success is False
        assert "persistent" in msg

    def test_exponential_backoff(self, ohlcv_data_store):
        """R4: 지수 백오프 적용 확인"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.side_effect = [
            ConnectionError("err1"), ConnectionError("err2"), ConnectionError("err3"),
        ]

        with patch("scripts.collect_daily_ohlcv.time.sleep") as mock_sleep:
            collect_symbol(
                "005930", fetcher, ohlcv_data_store, "2026-02-25", "2026-03-01", max_retries=2,
            )
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.5)
        mock_sleep.assert_any_call(1.0)


# ─── Batch Collection ──────────────────────────────────────────────────────


class TestRunCollection:
    @pytest.mark.asyncio
    async def test_full_batch(self, ohlcv_data_store, sample_fdr_df):
        """배치 수집 통합 테스트"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.return_value = sample_fdr_df

        result = await run_collection(
            symbols=[("005930", "kospi"), ("000660", "kospi"), ("035420", "kospi")],
            fetcher=fetcher,
            data_store=ohlcv_data_store,
            rate_limit=0.0,
            max_retries=0,
            initial_lookback_days=30,
        )
        assert result.total_symbols == 3
        assert result.success_count == 3
        assert result.fail_count == 0
        assert result.skip_count == 0
        assert result.new_rows_total > 0
        assert result.elapsed_seconds >= 0

    @pytest.mark.asyncio
    async def test_partial_failure_with_skip(self, ohlcv_data_store, sample_fdr_df):
        """B1: 빈 데이터는 skip, 나머지는 계속 수집"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.side_effect = [sample_fdr_df, pd.DataFrame(), sample_fdr_df]
        fetcher.fetch_yfinance.return_value = pd.DataFrame()

        result = await run_collection(
            symbols=[("005930", "kospi"), ("SKIP01", "kospi"), ("035420", "kospi")],
            fetcher=fetcher,
            data_store=ohlcv_data_store,
            rate_limit=0.0,
        )
        assert result.success_count == 2
        assert result.skip_count == 1
        assert result.fail_count == 0

    @pytest.mark.asyncio
    async def test_date_end_date_offset(self, ohlcv_data_store, sample_fdr_df):
        """B6: --date 사용 시 end_date가 target_date + 1일"""
        fetcher = MagicMock()
        fetcher.fetch_fdr.return_value = sample_fdr_df

        result = await run_collection(
            symbols=[("005930", "kospi")],
            fetcher=fetcher,
            data_store=ohlcv_data_store,
            rate_limit=0.0,
            target_date="2026-02-28",
        )
        assert result.success_count == 1


# ─── Notification ──────────────────────────────────────────────────────────


class TestCollectionSummary:
    @pytest.mark.asyncio
    async def test_success_notification(self):
        """성공 시 INFO 알림"""
        notifier = MagicMock()
        notifier.send_message = AsyncMock(return_value={})

        result = CollectionResult(
            total_symbols=3, success_count=3, fail_count=0, skip_count=0,
            new_rows_total=15, elapsed_seconds=3.5,
        )
        await send_collection_summary(notifier, result)

        notifier.send_message.assert_awaited_once()
        msg = notifier.send_message.call_args[0][0]
        assert msg.level == NotificationLevel.INFO

    @pytest.mark.asyncio
    async def test_partial_failure_notification(self):
        """일부 실패 시 WARNING 알림"""
        notifier = MagicMock()
        notifier.send_message = AsyncMock(return_value={})

        result = CollectionResult(
            total_symbols=3, success_count=2, fail_count=1, skip_count=0,
            new_rows_total=10, elapsed_seconds=3.0,
            failed_symbols=["999999: connection error"],
        )
        await send_collection_summary(notifier, result)

        msg = notifier.send_message.call_args[0][0]
        assert msg.level == NotificationLevel.WARNING
        assert "999999" in msg.body

    @pytest.mark.asyncio
    async def test_skip_count_in_notification(self):
        """B1: 알림에 스킵 카운트 포함"""
        notifier = MagicMock()
        notifier.send_message = AsyncMock(return_value={})

        result = CollectionResult(
            total_symbols=5, success_count=3, fail_count=0, skip_count=2,
            new_rows_total=15, elapsed_seconds=2.0,
        )
        await send_collection_summary(notifier, result)

        msg = notifier.send_message.call_args[0][0]
        assert "스킵: 2" in msg.body
        assert msg.data["스킵"] == 2

    @pytest.mark.asyncio
    async def test_dry_run_notification(self):
        """dry-run 시 INFO + 제목에 DRY-RUN 표시"""
        notifier = MagicMock()
        notifier.send_message = AsyncMock(return_value={})

        result = CollectionResult(total_symbols=1, success_count=1)
        await send_collection_summary(notifier, result, dry_run=True)

        msg = notifier.send_message.call_args[0][0]
        assert "DRY-RUN" in msg.title


# ─── CLI Arguments ─────────────────────────────────────────────────────────


class TestParseArgs:
    def test_default_args(self):
        with patch("sys.argv", ["collect_daily_ohlcv.py"]):
            args = parse_args()
        assert args.dry_run is False
        assert args.symbols is None
        assert args.date is None

    def test_dry_run(self):
        with patch("sys.argv", ["collect_daily_ohlcv.py", "--dry-run"]):
            args = parse_args()
        assert args.dry_run is True

    def test_symbols_override(self):
        with patch("sys.argv", ["collect_daily_ohlcv.py", "--symbols", "005930", "000660"]):
            args = parse_args()
        assert args.symbols == ["005930", "000660"]

    def test_date_arg(self):
        with patch("sys.argv", ["collect_daily_ohlcv.py", "--date", "2026-02-28"]):
            args = parse_args()
        assert args.date == "2026-02-28"
