"""
터틀 트레이딩 백테스터 모듈
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

from .indicators import add_turtle_indicators, calculate_unit_size
from .position_sizer import PositionDirection, AccountState
from .pyramid_manager import PyramidManager, PyramidDirection

logger = logging.getLogger(__name__)


class SignalType(Enum):
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"
    PYRAMID_LONG = "pyramid_long"
    PYRAMID_SHORT = "pyramid_short"
    STOP_LOSS = "stop_loss"


@dataclass
class Trade:
    symbol: str
    entry_date: datetime
    entry_price: float
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    direction: str = "long"
    quantity: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""


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


class TurtleBacktester:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.account = AccountState(initial_capital=config.initial_capital)
        self.pyramid_manager = PyramidManager(
            max_units=config.max_units,
            pyramid_interval_n=config.pyramid_interval_n
        )
        self.trades: List[Trade] = []
        self.equity_history: List[Dict] = []
        self.last_trade_profitable: Dict[str, bool] = {}

    def _get_entry_exit_columns(self) -> Tuple[str, str, str, str]:
        if self.config.system == 1:
            return "dc_high_20", "dc_low_20", "dc_low_10", "dc_high_10"
        return "dc_high_55", "dc_low_55", "dc_low_20", "dc_high_20"

    def _check_entry_signal(
        self,
        row: pd.Series,
        prev_row: pd.Series,
        symbol: str
    ) -> Optional[SignalType]:
        entry_high, entry_low, _, _ = self._get_entry_exit_columns()

        # 롱 진입 신호
        if row["high"] > prev_row[entry_high]:
            # System 1 필터: 직전 거래가 수익이면 스킵 (55일 이상 돌파 제외)
            if self.config.system == 1 and self.config.use_filter:
                if self.last_trade_profitable.get(symbol, False):
                    if row["high"] <= prev_row.get("dc_high_55", float("inf")):
                        return None
            return SignalType.ENTRY_LONG

        # 숏 진입 신호
        if row["low"] < prev_row[entry_low]:
            if self.config.system == 1 and self.config.use_filter:
                if self.last_trade_profitable.get(symbol, False):
                    if row["low"] >= prev_row.get("dc_low_55", 0):
                        return None
            return SignalType.ENTRY_SHORT

        return None

    def _check_exit_signal(
        self,
        row: pd.Series,
        prev_row: pd.Series,
        position: Any
    ) -> Optional[SignalType]:
        _, _, exit_low, exit_high = self._get_entry_exit_columns()

        if position.direction == PyramidDirection.LONG:
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

    def _check_pyramid_signal(
        self,
        row: pd.Series,
        position: Any,
        n_value: float
    ) -> Optional[SignalType]:
        can_pyramid, _ = position.can_pyramid(row["close"], n_value)
        if can_pyramid:
            if position.direction == PyramidDirection.LONG:
                return SignalType.PYRAMID_LONG
            return SignalType.PYRAMID_SHORT
        return None

    def run(self, data: Dict[str, pd.DataFrame]) -> BacktestResult:
        """백테스트 실행"""
        # 모든 데이터에 지표 추가
        for symbol, df in data.items():
            data[symbol] = add_turtle_indicators(df)

        # 날짜 인덱스 정렬
        all_dates = set()
        for df in data.values():
            all_dates.update(df["date"].tolist())
        all_dates = sorted(all_dates)

        logger.info(f"백테스트 시작: {len(data)}개 종목, {len(all_dates)}일")

        for i, date in enumerate(all_dates[1:], 1):
            daily_pnl = 0.0

            for symbol, df in data.items():
                df_slice = df[df["date"] <= date]
                if len(df_slice) < 2:
                    continue

                row = df_slice.iloc[-1]
                prev_row = df_slice.iloc[-2]
                n_value = row.get("N", row.get("atr", 0))

                position = self.pyramid_manager.get_position(symbol)

                if position:
                    # 청산 확인
                    exit_signal = self._check_exit_signal(row, prev_row, position)
                    if exit_signal:
                        self._close_position(symbol, date, row["close"], exit_signal.value)
                        continue

                    # 피라미딩 확인
                    pyramid_signal = self._check_pyramid_signal(row, position, n_value)
                    if pyramid_signal:
                        self._add_pyramid(symbol, date, row["close"], n_value)

                else:
                    # 진입 신호 확인
                    entry_signal = self._check_entry_signal(row, prev_row, symbol)
                    if entry_signal:
                        direction = PyramidDirection.LONG if entry_signal == SignalType.ENTRY_LONG else PyramidDirection.SHORT
                        self._open_position(symbol, date, row["close"], n_value, direction)

            # 일일 자본 기록
            self._record_equity(date)

        # 결과 계산
        return self._calculate_results()

    def _open_position(
        self,
        symbol: str,
        date: datetime,
        price: float,
        n_value: float,
        direction: PyramidDirection
    ):
        unit_size = calculate_unit_size(self.account.current_equity, n_value, self.config.risk_percent)
        if unit_size <= 0:
            return

        cost = unit_size * price * (1 + self.config.commission_pct)
        if cost > self.account.cash:
            return

        self.account.cash -= cost
        position = self.pyramid_manager.create_position(
            symbol, direction, date, price, unit_size, n_value
        )
        logger.debug(f"진입: {symbol} {direction.value} @ {price:.2f} x {unit_size}")

    def _add_pyramid(self, symbol: str, date: datetime, price: float, n_value: float):
        position = self.pyramid_manager.get_position(symbol)
        if not position:
            return

        unit_size = calculate_unit_size(self.account.current_equity, n_value, self.config.risk_percent)
        cost = unit_size * price * (1 + self.config.commission_pct)
        if cost > self.account.cash:
            return

        self.account.cash -= cost
        position.add_entry(date, price, unit_size, n_value)
        logger.debug(f"피라미딩: {symbol} @ {price:.2f} x {unit_size}")

    def _close_position(self, symbol: str, date: datetime, price: float, reason: str):
        position = self.pyramid_manager.get_position(symbol)
        if not position:
            return

        total_quantity = position.total_units
        avg_entry = position.average_entry_price

        if position.direction == PyramidDirection.LONG:
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
            exit_reason=reason
        )
        self.trades.append(trade)

        self.account.cash += price * total_quantity
        self.account.realized_pnl += pnl
        self.last_trade_profitable[symbol] = pnl > 0

        self.pyramid_manager.close_position(symbol)
        logger.debug(f"청산: {symbol} @ {price:.2f}, PnL: {pnl:.2f} ({reason})")

    def _record_equity(self, date: datetime):
        # 미실현 손익 계산
        unrealized = 0.0
        for symbol, position in self.pyramid_manager.positions.items():
            # 실제로는 현재가가 필요하지만 간단히 평균 진입가 사용
            pass

        equity = self.account.cash + unrealized
        self.equity_history.append({
            "date": date,
            "equity": equity,
            "cash": self.account.cash
        })

    def _calculate_results(self) -> BacktestResult:
        equity_df = pd.DataFrame(self.equity_history)
        if equity_df.empty:
            return BacktestResult(config=self.config)

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
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        profit_factor = sum(wins) / sum(losses) if losses and sum(losses) > 0 else 0

        # CAGR
        days = (equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days
        years = days / 365.25 if days > 0 else 1
        cagr = (final_equity / self.config.initial_capital) ** (1 / years) - 1 if years > 0 else 0

        # 샤프 비율
        equity_df["returns"] = equity_df["equity"].pct_change()
        sharpe = equity_df["returns"].mean() / equity_df["returns"].std() * np.sqrt(252) if equity_df["returns"].std() > 0 else 0

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
            avg_loss=avg_loss
        )
