"""
거래 유니버스 관리 모듈
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yaml

from src.types import AssetGroup


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
    def __init__(self, yaml_path: Optional[str] = None, csv_path: Optional[str] = None):
        self.yaml_path = Path(yaml_path) if yaml_path else None
        self.csv_path = Path(csv_path) if csv_path else None
        self.assets: Dict[str, Asset] = {}
        self._load()

    def _load(self):
        if self.yaml_path and self.yaml_path.exists():
            self._load_from_yaml()
        elif self.csv_path and self.csv_path.exists():
            self._load_from_csv()
        else:
            self._load_defaults()

    def _load_from_yaml(self):
        """YAML 파일에서 유니버스 로드"""
        with open(self.yaml_path, "r") as f:
            config = yaml.safe_load(f)

        if not config or "symbols" not in config:
            self._load_defaults()
            return

        group_mapping = {
            "us_equity": AssetGroup.US_EQUITY,
            "kr_equity": AssetGroup.KR_EQUITY,
            "crypto": AssetGroup.CRYPTO,
            "commodity": AssetGroup.COMMODITY,
            "bond": AssetGroup.BOND,
            "inverse": AssetGroup.INVERSE,
            "asia_equity": AssetGroup.ASIA_EQUITY,
            "currency": AssetGroup.CURRENCY,
        }

        for category, items in config["symbols"].items():
            for item in items:
                symbol = str(item["symbol"])
                group_str = item.get("group", category)
                asset_group = group_mapping.get(group_str, AssetGroup.US_EQUITY)

                # Determine country from symbol
                if symbol.endswith(".KS") or symbol.endswith(".KQ"):
                    country = "KR"
                else:
                    country = "US"

                # Determine leverage for inverse ETFs
                leverage = 1.0
                if asset_group == AssetGroup.INVERSE:
                    leverage = -1.0

                asset = Asset(
                    symbol=symbol,
                    name=item.get("name", symbol),
                    country=country,
                    asset_type=category,
                    group=asset_group,
                    leverage=leverage,
                    underlying=item.get("underlying"),
                    enabled=True,
                )
                self.assets[symbol] = asset

    def _load_from_csv(self):
        df = pd.read_csv(self.csv_path)
        for _, row in df.iterrows():
            symbol = str(row.get("Ticker", row.get("symbol", ""))).strip()
            asset = Asset(
                symbol=symbol,
                name=str(row.get("Name", row.get("name", ""))).strip(),
                country=str(row.get("Country", row.get("country", "US"))).strip(),
                asset_type=str(row.get("Type", row.get("type", ""))).strip(),
                group=AssetGroup.US_EQUITY,
                enabled=True,
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

    def get_all_symbols(self) -> List[str]:
        """활성화된 전체 심볼 리스트 (이름 포함 튜플이 아닌 순수 심볼)"""
        return self.get_enabled_symbols()

    def get_group_mapping(self) -> Dict[str, AssetGroup]:
        return {s: a.group for s, a in self.assets.items()}
