"""
거래 유니버스 관리 모듈
"""

import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum


class AssetGroup(Enum):
    KR_EQUITY = "kr_equity"
    US_EQUITY = "us_equity"
    ASIA_EQUITY = "asia_equity"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    BOND = "bond"
    INVERSE = "inverse"


@dataclass
class Asset:
    symbol: str
    name: str
    country: str
    asset_type: str
    group: AssetGroup
    leverage: float = 1.0
    underlying: Optional[str] = None
    enabled: bool = True

    @property
    def is_inverse(self) -> bool:
        return self.leverage < 0


class UniverseManager:
    def __init__(self, csv_path: Optional[str] = None):
        self.csv_path = Path(csv_path) if csv_path else None
        self.assets: Dict[str, Asset] = {}
        self._load()

    def _load(self):
        if self.csv_path and self.csv_path.exists():
            self._load_from_csv()
        else:
            self._load_defaults()

    def _load_from_csv(self):
        df = pd.read_csv(self.csv_path)
        for _, row in df.iterrows():
            symbol = str(row.get('Ticker', row.get('symbol', ''))).strip()
            asset = Asset(
                symbol=symbol,
                name=str(row.get('Name', row.get('name', ''))).strip(),
                country=str(row.get('Country', row.get('country', 'US'))).strip(),
                asset_type=str(row.get('Type', row.get('type', ''))).strip(),
                group=AssetGroup.US_EQUITY,
                enabled=True
            )
            self.assets[symbol] = asset

    def _load_defaults(self):
        defaults = [
            Asset("SPY", "S&P 500 ETF", "US", "Index ETF", AssetGroup.US_EQUITY),
            Asset("QQQ", "Nasdaq 100 ETF", "US", "Index ETF", AssetGroup.US_EQUITY),
            Asset("DIA", "Dow Jones ETF", "US", "Index ETF", AssetGroup.US_EQUITY),
            Asset("IWM", "Russell 2000 ETF", "US", "Index ETF", AssetGroup.US_EQUITY),
            Asset("GLD", "Gold ETF", "US", "Commodity ETF", AssetGroup.COMMODITY),
            Asset("TLT", "Treasury 20+ ETF", "US", "Bond ETF", AssetGroup.BOND),
            Asset("SH", "S&P 500 Inverse", "US", "Inverse ETF", AssetGroup.INVERSE, -1, "SPY"),
            Asset("SQQQ", "Nasdaq 3x Inverse", "US", "Inverse ETF", AssetGroup.INVERSE, -3, "QQQ"),
        ]
        for asset in defaults:
            self.assets[asset.symbol] = asset

    def get_enabled_symbols(self) -> List[str]:
        return [s for s, a in self.assets.items() if a.enabled]

    def get_symbols_by_group(self, group: AssetGroup) -> List[str]:
        return [s for s, a in self.assets.items() if a.group == group and a.enabled]

    def get_inverse_etfs(self) -> List[str]:
        return [s for s, a in self.assets.items() if a.is_inverse and a.enabled]

    def get_group_mapping(self) -> Dict[str, AssetGroup]:
        return {s: a.group for s, a in self.assets.items()}
