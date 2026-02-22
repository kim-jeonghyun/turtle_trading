"""
Parquet 기반 데이터 저장소 모듈
- OHLCV 캐싱
- 거래 기록 저장
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from src.utils import validate_symbol

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    cache_dir: Path
    max_age_days: int = 1
    compression: str = "snappy"


class ParquetDataStore:
    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.cache_dir = self.base_dir / "cache"
        self.trades_dir = self.base_dir / "trades"
        self.signals_dir = self.base_dir / "signals"

        for d in [self.cache_dir, self.trades_dir, self.signals_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, symbol: str, data_type: str = "ohlcv") -> Path:
        safe_symbol = symbol.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{safe_symbol}_{data_type}.parquet"

    def _is_cache_valid(self, path: Path, max_age_hours: int = 24) -> bool:
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        age = datetime.now() - mtime
        return age < timedelta(hours=max_age_hours)

    def save_ohlcv(self, symbol: str, df: pd.DataFrame):
        symbol = validate_symbol(symbol)
        path = self._get_cache_path(symbol, "ohlcv")
        self._atomic_write_parquet(path, df)
        logger.info(f"OHLCV 저장: {symbol} -> {path}")

    def load_ohlcv(self, symbol: str, max_age_hours: int = 24) -> Optional[pd.DataFrame]:
        symbol = validate_symbol(symbol)
        path = self._get_cache_path(symbol, "ohlcv")
        if not self._is_cache_valid(path, max_age_hours):
            return None
        try:
            df = pd.read_parquet(path)
            logger.info(f"OHLCV 캐시 로드: {symbol}")
            return df
        except Exception as e:
            logger.error(f"OHLCV 로드 실패: {e}")
            return None

    def save_indicators(self, symbol: str, df: pd.DataFrame):
        symbol = validate_symbol(symbol)
        path = self._get_cache_path(symbol, "indicators")
        self._atomic_write_parquet(path, df)

    def _atomic_write_parquet(self, path: Path, df: pd.DataFrame):
        """Atomic Parquet write: temp file → rename"""
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        os.close(fd)
        try:
            df.to_parquet(tmp_path, compression="snappy")
            os.rename(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load_indicators(self, symbol: str) -> Optional[pd.DataFrame]:
        symbol = validate_symbol(symbol)
        path = self._get_cache_path(symbol, "indicators")
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def save_trade(self, trade: Dict[str, Any]):
        validate_symbol(trade.get("symbol", ""))

        today = datetime.now().strftime("%Y%m%d")
        path = self.trades_dir / f"trades_{today}.parquet"

        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, pd.DataFrame([trade])], ignore_index=True)
        else:
            df = pd.DataFrame([trade])

        self._atomic_write_parquet(path, df)
        logger.info(f"거래 기록 저장: {trade.get('symbol')}")

    def load_trades(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        all_trades = []
        for f in sorted(self.trades_dir.glob("trades_*.parquet")):
            date_str = f.stem.split("_")[1]
            if start_date and date_str < start_date.replace("-", ""):
                continue
            if end_date and date_str > end_date.replace("-", ""):
                continue
            all_trades.append(pd.read_parquet(f))

        if all_trades:
            return pd.concat(all_trades, ignore_index=True)
        return pd.DataFrame()

    def save_signal(self, signal: Dict[str, Any]):
        today = datetime.now().strftime("%Y%m%d")
        path = self.signals_dir / f"signals_{today}.parquet"

        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, pd.DataFrame([signal])], ignore_index=True)
        else:
            df = pd.DataFrame([signal])

        self._atomic_write_parquet(path, df)

    def load_signals(self, date: Optional[str] = None) -> pd.DataFrame:
        if date:
            path = self.signals_dir / f"signals_{date.replace('-', '')}.parquet"
            if path.exists():
                return pd.read_parquet(path)
            return pd.DataFrame()

        all_signals = []
        for f in sorted(self.signals_dir.glob("signals_*.parquet")):
            all_signals.append(pd.read_parquet(f))
        if all_signals:
            return pd.concat(all_signals, ignore_index=True)
        return pd.DataFrame()

    def cleanup_old_cache(self, max_age_days: int = 7):
        cutoff = datetime.now() - timedelta(days=max_age_days)
        removed = 0
        for f in self.cache_dir.glob("*.parquet"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                removed += 1
        logger.info(f"오래된 캐시 삭제: {removed}개 파일")

    def get_cache_stats(self) -> Dict[str, Any]:
        cache_files = list(self.cache_dir.glob("*.parquet"))
        trade_files = list(self.trades_dir.glob("*.parquet"))
        signal_files = list(self.signals_dir.glob("*.parquet"))

        total_size = sum(f.stat().st_size for f in cache_files + trade_files + signal_files)

        return {
            "cache_files": len(cache_files),
            "trade_files": len(trade_files),
            "signal_files": len(signal_files),
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        }
