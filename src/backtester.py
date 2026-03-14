"""
터틀 트레이딩 백테스터 모듈
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.trend_filter import FilterStats, TrendFilter, TrendFilterConfig
from src.types import AssetGroup, Direction, MarketRegime, SignalType

from .indicators import add_turtle_indicators, calculate_efficiency_ratio, calculate_unit_size
from .position_sizer import AccountState
from .pyramid_manager import PyramidManager
from .risk_manager import PortfolioRiskManager

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    symbol: str
    entry_date: datetime
    entry_price: float
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    direction: str = "LONG"
    quantity: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    entry_reason: str = ""
    er_at_entry: Optional[float] = None


@dataclass
class BacktestConfig:
    initial_capital: float = 100000.0
    risk_percent: float = 0.01
    system: int = 1  # 1 or 2
    max_units: int = 4
    pyramid_interval_n: float = 0.5
    stop_distance_n: float = 2.0
    use_filter: bool = True
    commission_pct: float = 0.001
    use_trend_quality_filter: bool = False
    er_threshold: float = 0.3
    regime_proxy_symbol: Optional[str] = None
    use_drawdown_reduction: bool = True


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: List[Trade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    final_equity: float = 0.0
    total_return: float = 0.0
    cagr: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    filter_stats: Optional[FilterStats] = None


class TurtleBacktester:
    def __init__(self, config: BacktestConfig, symbol_groups: Optional[Dict[str, AssetGroup]] = None):
        self.config = config
        self.account = AccountState(initial_capital=config.initial_capital)
        self.pyramid_manager = PyramidManager(max_units=config.max_units, pyramid_interval_n=config.pyramid_interval_n)
        self.trades: List[Trade] = []
        self.equity_history: List[Dict] = []
        self.last_trade_profitable: Dict[str, bool] = {}
        self._hypothetical_breakouts: Dict[str, Dict] = {}
        self.entry_reasons: Dict[str, str] = {}
        self._er_at_entry: Dict[str, Optional[float]] = {}
        self.trend_filter: Optional[TrendFilter] = None
        if config.use_trend_quality_filter:
            tf_config = TrendFilterConfig(
                er_threshold=config.er_threshold,
                sideways_er_boost=0.0,  # regime 미확인 시 boost 비적용
            )
            self.trend_filter = TrendFilter(tf_config)
        self.risk_manager: Optional[PortfolioRiskManager] = (
            PortfolioRiskManager(symbol_groups=symbol_groups or {}) if symbol_groups is not None else None
        )

    @property
    def _use_risk_limits(self) -> bool:
        return self.risk_manager is not None

    def _get_entry_exit_columns(self) -> Tuple[str, str, str, str]:
        if self.config.system == 1:
            return "dc_high_20", "dc_low_20", "dc_low_10", "dc_high_10"
        return "dc_high_55", "dc_low_55", "dc_low_20", "dc_high_20"

    def _check_entry_signal(self, row: pd.Series, prev_row: pd.Series, symbol: str) -> Optional[SignalType]:
        if self.trend_filter:
            er_value = float(row.get("er", 0.0) or 0.0)
            result = self.trend_filter.should_enter(MarketRegime.SIDEWAYS, er_value)
            if not result.allowed:
                logger.debug(f"[TrendFilter] {symbol} 진입 차단: {result.reason}")
                return None

        entry_high, entry_low, _, _ = self._get_entry_exit_columns()

        # 롱 진입 신호
        if row["high"] > prev_row[entry_high]:
            # System 1 필터: 직전 거래가 수익이면 스킵 (55일 이상 돌파 제외)
            if self.config.system == 1 and self.config.use_filter:
                if self.last_trade_profitable.get(symbol, False):
                    if row["high"] <= prev_row.get("dc_high_55", float("inf")):
                        self._record_hypothetical_breakout(
                            symbol, prev_row[entry_high], Direction.LONG,
                            n_value=float(row.get("N", row.get("atr", 0))),
                        )
                        return None
            return SignalType.ENTRY_LONG

        # 숏 진입 신호
        if row["low"] < prev_row[entry_low]:
            if self.config.system == 1 and self.config.use_filter:
                if self.last_trade_profitable.get(symbol, False):
                    if row["low"] >= prev_row.get("dc_low_55", 0):
                        self._record_hypothetical_breakout(
                            symbol, prev_row[entry_low], Direction.SHORT,
                            n_value=float(row.get("N", row.get("atr", 0))),
                        )
                        return None
            return SignalType.ENTRY_SHORT

        return None

    def _check_exit_signal(self, row: pd.Series, prev_row: pd.Series, position: Any) -> Optional[SignalType]:
        _, _, exit_low, exit_high = self._get_entry_exit_columns()

        if position.direction == Direction.LONG:
            # 스톱로스
            if row["low"] <= position.current_stop:
                return SignalType.STOP_LOSS
            # 청산 신호
            if row["low"] < prev_row[exit_low]:
                return SignalType.EXIT_LONG
        else:
            # 숏 스톱로스
            if row["high"] >= position.current_stop:
                return SignalType.STOP_LOSS
            # 숏 청산 신호
            if row["high"] > prev_row[exit_high]:
                return SignalType.EXIT_SHORT

        return None

    def _check_pyramid_signal(self, row: pd.Series, position: Any, n_value: float) -> Optional[SignalType]:
        can_pyramid, _ = position.can_pyramid(row["close"], n_value)
        if can_pyramid:
            if position.direction == Direction.LONG:
                return SignalType.PYRAMID_LONG
            return SignalType.PYRAMID_SHORT
        return None

    def _record_hypothetical_breakout(
        self, symbol: str, price: float, direction: Direction,
        n_value: float = 0.0,
    ):
        """S1 필터에 의해 스킵된 브레이크아웃의 가상 진입을 기록"""
        stop_distance = n_value * self.config.stop_distance_n
        if direction == Direction.LONG:
            stop_price = price - stop_distance
        else:
            stop_price = price + stop_distance
        self._hypothetical_breakouts[symbol] = {
            "price": price,
            "direction": direction,
            "stop_price": stop_price,
        }

    def _resolve_hypothetical(self, symbol: str, exit_price: float):
        """가상 브레이크아웃의 결과를 판정하고 필터 상태를 갱신"""
        hyp = self._hypothetical_breakouts.pop(symbol, None)
        if hyp is None:
            return
        if hyp["direction"] == Direction.LONG:
            profitable = exit_price > hyp["price"]
        else:
            profitable = exit_price < hyp["price"]
        self.last_trade_profitable[symbol] = profitable

    def run(self, data: Dict[str, pd.DataFrame]) -> BacktestResult:
        """백테스트 실행"""
        # 모든 데이터에 지표 추가
        for symbol, df in data.items():
            data[symbol] = add_turtle_indicators(df)
            if self.trend_filter:
                data[symbol]["er"] = calculate_efficiency_ratio(
                    data[symbol]["close"], period=self.trend_filter.config.er_period
                )

        # 날짜 인덱스 정렬
        date_set: set[Any] = set()
        for df in data.values():
            date_set.update(df["date"].tolist())
        all_dates: list[Any] = sorted(date_set)

        logger.info(f"백테스트 시작: {len(data)}개 종목, {len(all_dates)}일")

        for i, date in enumerate(all_dates[1:], 1):
            _daily_pnl = 0.0
            pending_entries = []

            for symbol, df in data.items():
                df_slice = df[df["date"] <= date]
                if len(df_slice) < 2:
                    continue

                row = df_slice.iloc[-1]
                prev_row = df_slice.iloc[-2]
                n_value = row.get("N", row.get("atr", 0))

                position = self.pyramid_manager.get_position(symbol)

                if position:
                    # 청산 확인 (즉시 처리)
                    exit_signal = self._check_exit_signal(row, prev_row, position)
                    if exit_signal:
                        if exit_signal == SignalType.STOP_LOSS:
                            exit_price = position.current_stop
                        elif exit_signal in (SignalType.EXIT_LONG, SignalType.EXIT_SHORT):
                            _, _, exit_low, exit_high = self._get_entry_exit_columns()
                            if position.direction == Direction.LONG:
                                exit_price = prev_row[exit_low]
                            else:
                                exit_price = prev_row[exit_high]
                        else:
                            exit_price = row["close"]
                        self._close_position(symbol, date, exit_price, exit_signal.value)
                        continue

                    # 피라미딩 확인 (즉시 처리)
                    pyramid_signal = self._check_pyramid_signal(row, position, n_value)
                    if pyramid_signal:
                        pyramid_price = position.get_next_pyramid_price(n_value)
                        self._add_pyramid(symbol, date, pyramid_price, n_value)

                else:
                    # 진입 신호 수집 (나중에 강도순 처리)
                    entry_signal = self._check_entry_signal(row, prev_row, symbol)
                    if entry_signal:
                        direction = Direction.LONG if entry_signal == SignalType.ENTRY_LONG else Direction.SHORT
                        entry_high, entry_low, _, _ = self._get_entry_exit_columns()
                        if direction == Direction.LONG:
                            entry_price = prev_row[entry_high]
                            strength = (row["high"] - entry_price) / n_value if n_value > 0 else 0
                        else:
                            entry_price = prev_row[entry_low]
                            strength = (entry_price - row["low"]) / n_value if n_value > 0 else 0
                        er_value = float(row.get("er", 0.0) or 0.0) if self.trend_filter else None
                        pending_entries.append((
                            strength, symbol, date, entry_price, n_value, direction, er_value
                        ))

            # 강도순 진입 처리
            pending_entries.sort(key=lambda x: x[0], reverse=True)
            for _, symbol, entry_date, price, n_val, direction, er_val in pending_entries:
                self._open_position(symbol, entry_date, price, n_val, direction, er_val)

            # 가상 브레이크아웃 청산 확인 (S1 필터)
            for hyp_symbol in list(self._hypothetical_breakouts.keys()):
                if hyp_symbol not in data:
                    continue
                df_slice = data[hyp_symbol][data[hyp_symbol]["date"] <= date]
                if len(df_slice) < 2:
                    continue
                hyp_row = df_slice.iloc[-1]
                hyp_prev = df_slice.iloc[-2]
                hyp = self._hypothetical_breakouts[hyp_symbol]
                _, _, exit_low, exit_high = self._get_entry_exit_columns()

                # 2N 스톱로스 확인
                if hyp["direction"] == Direction.LONG:
                    if hyp_row["low"] <= hyp["stop_price"]:
                        self._resolve_hypothetical(hyp_symbol, hyp["stop_price"])
                        continue
                    if hyp_row["low"] < hyp_prev[exit_low]:
                        self._resolve_hypothetical(hyp_symbol, hyp_prev[exit_low])
                else:
                    if hyp_row["high"] >= hyp["stop_price"]:
                        self._resolve_hypothetical(hyp_symbol, hyp["stop_price"])
                        continue
                    if hyp_row["high"] > hyp_prev[exit_high]:
                        self._resolve_hypothetical(hyp_symbol, hyp_prev[exit_high])

            # 일일 자본 기록
            self._record_equity(date, data)

        # 결과 계산
        return self._calculate_results()

    def _open_position(
        self,
        symbol: str,
        date: datetime,
        price: float,
        n_value: float,
        direction: Direction,
        er_value: Optional[float] = None,
    ):
        sizing_equity = (
            self.account.get_sizing_equity() if self.config.use_drawdown_reduction
            else self.account.current_equity
        )
        unit_size = calculate_unit_size(n_value, sizing_equity, risk_per_unit=self.config.risk_percent)
        if unit_size <= 0:
            return

        if self.risk_manager is not None:
            can_add, reason = self.risk_manager.can_add_position(
                symbol=symbol, units=1, n_value=n_value, direction=direction
            )
            if not can_add:
                logger.debug(f"리스크 한도 차단: {symbol} - {reason}")
                return

        cost = unit_size * price * (1 + self.config.commission_pct)
        if cost > self.account.cash:
            return

        self.account.cash -= cost
        self.pyramid_manager.create_position(symbol, direction, date, price, unit_size, n_value)
        if self.risk_manager is not None:
            self.risk_manager.add_position(symbol, 1, n_value, direction)
        direction_label = "롱" if direction == Direction.LONG else "숏"
        self.entry_reasons[symbol] = f"System {self.config.system} {direction_label} 진입: {price:.2f} 돌파"
        self._er_at_entry[symbol] = er_value
        logger.debug(f"진입: {symbol} {direction.value} @ {price:.2f} x {unit_size}")

    def _add_pyramid(self, symbol: str, date: datetime, price: float, n_value: float):
        position = self.pyramid_manager.get_position(symbol)
        if not position:
            return

        if self.risk_manager is not None:
            can_add, reason = self.risk_manager.can_add_position(
                symbol=symbol, units=1, n_value=n_value, direction=position.direction
            )
            if not can_add:
                logger.debug(f"리스크 한도 차단 (피라미딩): {symbol} - {reason}")
                return

        sizing_equity = (
            self.account.get_sizing_equity() if self.config.use_drawdown_reduction
            else self.account.current_equity
        )
        unit_size = calculate_unit_size(n_value, sizing_equity, risk_per_unit=self.config.risk_percent)
        cost = unit_size * price * (1 + self.config.commission_pct)
        if cost > self.account.cash:
            return

        self.account.cash -= cost
        position.add_entry(date, price, unit_size, n_value)
        if self.risk_manager is not None:
            self.risk_manager.add_position(symbol, 1, n_value, position.direction)
        logger.debug(f"피라미딩: {symbol} @ {price:.2f} x {unit_size}")

    def _close_position(self, symbol: str, date: datetime, price: float, reason: str):
        position = self.pyramid_manager.get_position(symbol)
        if not position:
            return

        total_quantity = position.total_units
        avg_entry = position.average_entry_price

        if position.direction == Direction.LONG:
            pnl = (price - avg_entry) * total_quantity
        else:
            pnl = (avg_entry - price) * total_quantity

        pnl -= price * total_quantity * self.config.commission_pct
        pnl_pct = pnl / (avg_entry * total_quantity) if avg_entry > 0 else 0

        trade = Trade(
            symbol=symbol,
            entry_date=position.entries[0].entry_date,
            entry_price=avg_entry,
            exit_date=date,
            exit_price=price,
            direction=position.direction.value,
            quantity=total_quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            entry_reason=self.entry_reasons.pop(symbol, ""),
            er_at_entry=self._er_at_entry.pop(symbol, None),
        )
        self.trades.append(trade)

        self.account.cash += price * total_quantity
        self.account.realized_pnl += pnl
        self.last_trade_profitable[symbol] = pnl > 0

        if self.risk_manager is not None:
            for entry in position.entries:
                self.risk_manager.remove_position(symbol, 1, position.direction, n_value=entry.n_at_entry)

        self.pyramid_manager.close_position(symbol)
        logger.debug(f"청산: {symbol} @ {price:.2f}, PnL: {pnl:.2f} ({reason})")

    def _record_equity(self, date: datetime, data: Optional[Dict[str, pd.DataFrame]] = None):
        unrealized = 0.0
        for symbol, position in self.pyramid_manager.positions.items():
            if data and symbol in data:
                df_slice = data[symbol][data[symbol]["date"] <= date]
                if not df_slice.empty:
                    current_price = df_slice.iloc[-1]["close"]
                    avg_entry = position.average_entry_price
                    qty = position.total_units
                    if position.direction == Direction.LONG:
                        unrealized += (current_price - avg_entry) * qty
                    else:
                        unrealized += (avg_entry - current_price) * qty

        equity = self.account.cash + unrealized
        self.account.current_equity = equity
        if equity > self.account.peak_equity:
            self.account.peak_equity = equity
        self.equity_history.append({"date": date, "equity": equity, "cash": self.account.cash})

    def _calculate_results(self) -> BacktestResult:
        equity_df = pd.DataFrame(self.equity_history)
        filter_stats = self.trend_filter.get_filter_stats() if self.trend_filter else None
        if equity_df.empty:
            return BacktestResult(config=self.config, filter_stats=filter_stats)

        final_equity = equity_df["equity"].iloc[-1]
        total_return = (final_equity - self.config.initial_capital) / self.config.initial_capital

        # 최대 낙폭
        equity_df["peak"] = equity_df["equity"].cummax()
        equity_df["drawdown"] = (equity_df["peak"] - equity_df["equity"]) / equity_df["peak"]
        max_drawdown = equity_df["drawdown"].max()

        # 거래 통계
        total_trades = len(self.trades)
        winning_trades = len([t for t in self.trades if t.pnl > 0])
        losing_trades = len([t for t in self.trades if t.pnl <= 0])
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        wins = [t.pnl for t in self.trades if t.pnl > 0]
        losses = [abs(t.pnl) for t in self.trades if t.pnl <= 0]
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        profit_factor = sum(wins) / sum(losses) if losses and sum(losses) > 0 else 0

        # CAGR
        days = (equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days
        years = days / 365.25 if days > 0 else 1
        cagr = (final_equity / self.config.initial_capital) ** (1 / years) - 1 if years > 0 else 0

        # 샤프 비율
        equity_df["returns"] = equity_df["equity"].pct_change()
        sharpe = (
            equity_df["returns"].mean() / equity_df["returns"].std() * np.sqrt(252)
            if equity_df["returns"].std() > 0
            else 0
        )

        return BacktestResult(
            config=self.config,
            trades=self.trades,
            equity_curve=equity_df,
            final_equity=final_equity,
            total_return=total_return,
            cagr=cagr,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            avg_win=avg_win,
            avg_loss=avg_loss,
            filter_stats=filter_stats,
        )
