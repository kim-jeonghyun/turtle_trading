"""다통화 포트폴리오 백테스터 오케스트레이터

각 통화(USD/KRW)에 대해 독립적인 TurtleBacktester를 실행한다.
- 독립 AccountState (통화별 자본)
- 독립 PortfolioRiskManager (동일 한도, 통화 내 동질적 N값)
- 독립 CommissionModel (US: 단일 수수료, KRX: 위탁수수료 + 거래세)
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import pandas as pd

from .backtester import BacktestConfig, BacktestResult, TurtleBacktester
from .types import AssetGroup


@dataclass
class MultiCurrencyResult:
    usd_result: Optional[BacktestResult] = None
    krw_result: Optional[BacktestResult] = None

    @property
    def results(self) -> Dict[str, BacktestResult]:
        out = {}
        if self.usd_result:
            out["USD"] = self.usd_result
        if self.krw_result:
            out["KRW"] = self.krw_result
        return out


class MultiCurrencyBacktester:
    """통화별 분리 백테스터.

    N-exposure 한도: 양쪽 모두 max_total_n_exposure=10.0 사용.
    근거: 통화별로 PortfolioRiskManager가 독립이므로, 각 통화 내에서
    N값 스케일이 동질적 (USD: ATR ~$3-5, KRW: ATR ~1000-3000원).
    """

    def __init__(
        self,
        usd_config: Optional[BacktestConfig] = None,
        krw_config: Optional[BacktestConfig] = None,
        usd_symbol_groups: Optional[Dict[str, AssetGroup]] = None,
        krw_symbol_groups: Optional[Dict[str, AssetGroup]] = None,
    ):
        self.usd_backtester: Optional[TurtleBacktester] = None
        self.krw_backtester: Optional[TurtleBacktester] = None

        if usd_config:
            self.usd_backtester = TurtleBacktester(
                usd_config,
                symbol_groups=usd_symbol_groups,
                currency="USD",
            )

        if krw_config:
            self.krw_backtester = TurtleBacktester(
                krw_config,
                symbol_groups=krw_symbol_groups,
                currency="KRW",
            )

    def _split_by_currency(
        self,
        data: Dict[str, pd.DataFrame],
        currency_map: Dict[str, str],
    ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]:
        usd_data = {s: df for s, df in data.items() if currency_map.get(s, "USD") == "USD"}
        krw_data = {s: df for s, df in data.items() if currency_map.get(s) == "KRW"}
        return usd_data, krw_data

    def run(
        self,
        data: Dict[str, pd.DataFrame],
        currency_map: Dict[str, str],
    ) -> MultiCurrencyResult:
        usd_data, krw_data = self._split_by_currency(data, currency_map)
        result = MultiCurrencyResult()

        if self.usd_backtester and usd_data:
            result.usd_result = self.usd_backtester.run(usd_data)

        if self.krw_backtester and krw_data:
            result.krw_result = self.krw_backtester.run(krw_data)

        return result
