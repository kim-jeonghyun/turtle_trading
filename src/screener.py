"""
멀티 전략 스크리너 모듈.

Strategy Protocol 기반 확장 가능 설계:
- TurtleStrategy: 터틀 트레이딩 브레이크아웃/청산 (raw screener)
- (향후) MinerviniStrategy: SEPA/VCP 패턴
- (향후) PatternStrategy: 차트 패턴 인식

사용법:
    results = run_screening(data, strategies=[TurtleStrategy()])

Design Decisions:
- DD1: TurtleStrategy는 System 1 profit filter를 의도적으로 생략합니다.
  PositionTracker 의존 없이 모든 기계적 브레이크아웃을 보여줍니다.
  check_positions.py의 Curtis Faith 필터와 다른 결과를 냅니다.
- DD2: short_restricted 파라미터로 숏 시그널을 제어합니다.
  한국 시장 종목은 기본 True (숏 시그널 억제).
- DD4: price_limit_pct 파라미터로 상한가/하한가 근접 종목에 경고를 추가합니다.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import pandas as pd

from src.indicators import add_turtle_indicators, calculate_sma
from src.types import SignalType

logger = logging.getLogger(__name__)


@dataclass
class ScreeningResult:
    """스크리닝 결과 단일 시그널."""

    symbol: str
    strategy_name: str
    signal_type: SignalType
    price: float
    current_close: float
    n_value: float = 0.0
    stop_loss: float = 0.0
    message: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy_name,
            "signal_type": self.signal_type.value,
            "price": round(self.price, 2),
            "current_close": round(self.current_close, 2),
            "n_value": round(self.n_value, 2),
            "stop_loss": round(self.stop_loss, 2),
            "message": self.message,
            "metadata": self.metadata,
        }


@runtime_checkable
class Strategy(Protocol):
    """스크리닝 전략 프로토콜.

    새 전략 추가 시 이 Protocol을 구현하면 run_screening()에 바로 사용 가능.
    context 파라미터는 universe-level 정보(레짐, 브레드스 등)를 전달하기 위한
    확장 포인트로, 향후 전략이 시장 상황을 참고할 수 있도록 설계.
    """

    name: str

    def scan(
        self,
        df: pd.DataFrame,
        symbol: str,
        short_restricted: bool = True,
        price_limit_pct: float = 0.30,
        context: dict | None = None,
    ) -> list[ScreeningResult]:
        ...


class TurtleStrategy:
    """터틀 트레이딩 브레이크아웃 스크리닝 전략.

    Raw screener — System 1 profit filter를 의도적으로 생략합니다.
    check_positions.py와 달리 PositionTracker에 의존하지 않으며,
    모든 기계적 브레이크아웃을 보여줍니다. 사용자가 직접 필터링 판단.

    검출 시그널:
    - System 1 (20일) / System 2 (55일) 롱·숏 진입
    - System 1 (10일) / System 2 (20일) 롱·숏 청산

    DD4: 상한가/하한가 근접 시 price_limit_warning 메타데이터 추가.
    DD12: 진입 시그널에 avg_volume_20d 메타데이터 추가 (정보 제공용).
    """

    name: str = "turtle"

    def scan(
        self,
        df: pd.DataFrame,
        symbol: str,
        short_restricted: bool = True,
        price_limit_pct: float = 0.30,
        context: dict | None = None,
    ) -> list[ScreeningResult]:
        if len(df) < 56:
            return []

        if "N" not in df.columns:
            df = add_turtle_indicators(df)

        results: list[ScreeningResult] = []
        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        if pd.isna(today["N"]) or pd.isna(yesterday.get("dc_high_20")):
            return []

        n_val = float(today["N"])
        current_close = float(today["close"])

        # 가격 제한 근접 판단 (DD4)
        yesterday_close = float(yesterday["close"])
        daily_change_pct = (
            (current_close - yesterday_close) / yesterday_close
            if yesterday_close != 0
            else 0.0
        )
        near_price_limit = abs(daily_change_pct) >= (price_limit_pct - 0.01)

        # 평균 거래량 20일
        avg_volume_20d = float(calculate_sma(df["volume"], 20).iloc[-1]) if len(df) >= 20 else 0.0
        volume_meta = {"avg_volume_20d": round(avg_volume_20d, 0)}

        # === 롱 진입 시그널 ===
        if today["high"] > yesterday["dc_high_20"]:
            entry_price = float(yesterday["dc_high_20"])
            meta = {"system": 1, **volume_meta}
            if near_price_limit:
                meta["price_limit_warning"] = True
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.ENTRY_LONG,
                price=entry_price, current_close=current_close,
                n_value=n_val, stop_loss=entry_price - 2 * n_val,
                message=f"S1 롱 진입: {entry_price:.0f} 돌파 (20일)",
                metadata=meta,
            ))

        if today["high"] > yesterday["dc_high_55"]:
            entry_price = float(yesterday["dc_high_55"])
            meta = {"system": 2, **volume_meta}
            if near_price_limit:
                meta["price_limit_warning"] = True
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.ENTRY_LONG,
                price=entry_price, current_close=current_close,
                n_value=n_val, stop_loss=entry_price - 2 * n_val,
                message=f"S2 롱 진입: {entry_price:.0f} 돌파 (55일)",
                metadata=meta,
            ))

        # === 숏 진입 시그널 (DD2) ===
        if not short_restricted:
            if today["low"] < yesterday["dc_low_20"]:
                entry_price = float(yesterday["dc_low_20"])
                meta = {"system": 1, **volume_meta}
                if near_price_limit:
                    meta["price_limit_warning"] = True
                results.append(ScreeningResult(
                    symbol=symbol, strategy_name=self.name,
                    signal_type=SignalType.ENTRY_SHORT,
                    price=entry_price, current_close=current_close,
                    n_value=n_val, stop_loss=entry_price + 2 * n_val,
                    message=f"S1 숏 진입: {entry_price:.0f} 이탈 (20일)",
                    metadata=meta,
                ))

            if today["low"] < yesterday["dc_low_55"]:
                entry_price = float(yesterday["dc_low_55"])
                meta = {"system": 2, **volume_meta}
                if near_price_limit:
                    meta["price_limit_warning"] = True
                results.append(ScreeningResult(
                    symbol=symbol, strategy_name=self.name,
                    signal_type=SignalType.ENTRY_SHORT,
                    price=entry_price, current_close=current_close,
                    n_value=n_val, stop_loss=entry_price + 2 * n_val,
                    message=f"S2 숏 진입: {entry_price:.0f} 이탈 (55일)",
                    metadata=meta,
                ))

        # === 롱 청산 시그널 ===
        if today["low"] < yesterday["dc_low_10"]:
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.EXIT_LONG,
                price=float(yesterday["dc_low_10"]),
                current_close=current_close, n_value=n_val,
                message=f"S1 롱 청산: {yesterday['dc_low_10']:.0f} 이탈 (10일)",
                metadata={"system": 1},
            ))

        if today["low"] < yesterday["dc_low_20"]:
            results.append(ScreeningResult(
                symbol=symbol, strategy_name=self.name,
                signal_type=SignalType.EXIT_LONG,
                price=float(yesterday["dc_low_20"]),
                current_close=current_close, n_value=n_val,
                message=f"S2 롱 청산: {yesterday['dc_low_20']:.0f} 이탈 (20일)",
                metadata={"system": 2},
            ))

        # === 숏 청산 시그널 (short_restricted=True이면 억제) ===
        if not short_restricted:
            if today["high"] > yesterday["dc_high_10"]:
                results.append(ScreeningResult(
                    symbol=symbol, strategy_name=self.name,
                    signal_type=SignalType.EXIT_SHORT,
                    price=float(yesterday["dc_high_10"]),
                    current_close=current_close, n_value=n_val,
                    message=f"S1 숏 청산: {yesterday['dc_high_10']:.0f} 돌파 (10일)",
                    metadata={"system": 1},
                ))

            if today["high"] > yesterday["dc_high_20"]:
                results.append(ScreeningResult(
                    symbol=symbol, strategy_name=self.name,
                    signal_type=SignalType.EXIT_SHORT,
                    price=float(yesterday["dc_high_20"]),
                    current_close=current_close, n_value=n_val,
                    message=f"S2 숏 청산: {yesterday['dc_high_20']:.0f} 돌파 (20일)",
                    metadata={"system": 2},
                ))

        return results


def run_screening(
    data: dict[str, pd.DataFrame],
    strategies: list[Strategy] | None = None,
    short_restricted_symbols: set[str] | None = None,
    context: dict | None = None,
) -> list[ScreeningResult]:
    """복수 심볼에 복수 전략 적용하여 스크리닝.

    지표를 심볼당 1회만 사전 계산하여 중복 연산 방지.
    입력 data dict를 변경하지 않음 (로컬 복사본 사용).
    """
    if strategies is None:
        strategies = [TurtleStrategy()]

    all_results: list[ScreeningResult] = []

    # 지표 사전 계산용 로컬 딕셔너리 (입력 data 변경 방지)
    prepared: dict[str, pd.DataFrame] = {}

    for symbol, df in data.items():
        if "N" not in df.columns:
            try:
                prepared[symbol] = add_turtle_indicators(df)
            except Exception as e:
                logger.warning(f"지표 계산 실패: {symbol} - {e}")
                continue
        else:
            prepared[symbol] = df

    # 저유동성 판단을 위한 전체 평균 거래량 50th percentile 계산
    all_avg_volumes: list[float] = []
    for symbol, df in prepared.items():
        if len(df) >= 20:
            avg_vol = float(calculate_sma(df["volume"], 20).iloc[-1])
            if not pd.isna(avg_vol):
                all_avg_volumes.append(avg_vol)

    volume_median = sorted(all_avg_volumes)[len(all_avg_volumes) // 2] if all_avg_volumes else 0.0

    for symbol, df in prepared.items():
        short_restricted = (
            short_restricted_symbols is None or symbol in short_restricted_symbols
        )

        for strategy in strategies:
            try:
                results = strategy.scan(
                    df, symbol, short_restricted=short_restricted, context=context,
                )
                for r in results:
                    avg_vol = r.metadata.get("avg_volume_20d", 0)
                    if avg_vol > 0 and avg_vol < volume_median:
                        r.metadata["low_volume"] = True
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"스크리닝 실패: {symbol}/{strategy.name} - {e}")

    return all_results
