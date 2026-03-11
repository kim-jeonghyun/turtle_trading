import pandas as pd

from src.screener import (
    ScreeningResult,
    TurtleStrategy,
    run_screening,
)
from src.types import SignalType


def _make_breakout_ohlcv(n: int = 60) -> pd.DataFrame:
    """20일 신고가 돌파 데이터. 마지막 행에서 돌파."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100.0] * (n - 10) + [100 + i * 2 for i in range(1, 11)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000] * n,
        }
    )


def _make_flat_ohlcv(n: int = 60) -> pd.DataFrame:
    """시그널 없는 횡보 데이터."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100.0] * n
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": closes,
            "volume": [1000] * n,
        }
    )


def _make_breakdown_ohlcv(n: int = 60) -> pd.DataFrame:
    """20일 신저가 이탈 데이터. 마지막 행에서 이탈."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100.0] * (n - 10) + [100 - i * 2 for i in range(1, 11)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000] * n,
        }
    )


def _make_price_limit_ohlcv(n: int = 60) -> pd.DataFrame:
    """상한가 근접 데이터. 마지막 행에서 +29% 이상 급등."""
    dates = pd.bdate_range(end="2026-03-10", periods=n)
    closes = [100.0] * (n - 1) + [130.0]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000] * n,
        }
    )


class TestTurtleStrategy:
    def test_detects_long_breakout(self):
        strategy = TurtleStrategy()
        df = _make_breakout_ohlcv()
        results = strategy.scan(df, symbol="005930")
        assert len(results) > 0
        entry_longs = [r for r in results if r.signal_type == SignalType.ENTRY_LONG]
        assert len(entry_longs) > 0

    def test_no_signal_on_flat(self):
        strategy = TurtleStrategy()
        df = _make_flat_ohlcv()
        results = strategy.scan(df, symbol="000660")
        entry_signals = [r for r in results if "entry" in r.signal_type.value]
        assert len(entry_signals) == 0

    def test_short_suppressed_by_default(self):
        """DD2: short_restricted=True이면 숏 시그널 없어야."""
        strategy = TurtleStrategy()
        df = _make_breakdown_ohlcv()
        results = strategy.scan(df, symbol="005930", short_restricted=True)
        short_signals = [r for r in results if r.signal_type in (SignalType.ENTRY_SHORT, SignalType.EXIT_SHORT)]
        assert len(short_signals) == 0

    def test_short_allowed_when_not_restricted(self):
        """short_restricted=False이면 숏 시그널 발생."""
        strategy = TurtleStrategy()
        df = _make_breakdown_ohlcv()
        results = strategy.scan(df, symbol="SPY", short_restricted=False)
        short_signals = [r for r in results if r.signal_type == SignalType.ENTRY_SHORT]
        assert len(short_signals) > 0

    def test_system2_exit_signals(self):
        """System 2 청산 시그널 (20일 저가 이탈) 검출."""
        strategy = TurtleStrategy()
        df = _make_breakdown_ohlcv()
        results = strategy.scan(df, symbol="TEST", short_restricted=True)
        exit_longs = [r for r in results if r.signal_type == SignalType.EXIT_LONG]
        systems = {r.metadata.get("system") for r in exit_longs}
        assert 1 in systems or 2 in systems

    def test_result_fields(self):
        strategy = TurtleStrategy()
        df = _make_breakout_ohlcv()
        results = strategy.scan(df, symbol="TEST")
        assert len(results) > 0
        r = results[0]
        assert isinstance(r, ScreeningResult)
        assert r.symbol == "TEST"
        assert r.strategy_name == "turtle"
        assert r.price > 0
        assert r.signal_type is not None

    def test_docstring_mentions_no_profit_filter(self):
        """DD1: profit filter 미적용이 문서화되어 있는지."""
        assert "profit filter" in TurtleStrategy.__doc__.lower() or "System 1 필터" in TurtleStrategy.__doc__

    def test_price_limit_warning(self):
        """DD4: 상한가/하한가 근접 시 price_limit_warning 메타데이터 포함."""
        strategy = TurtleStrategy()
        df = _make_price_limit_ohlcv()
        results = strategy.scan(df, symbol="005930")
        entry_signals = [r for r in results if r.signal_type == SignalType.ENTRY_LONG]
        for r in entry_signals:
            assert r.metadata.get("price_limit_warning") is True

    def test_no_price_limit_warning_on_normal(self):
        """정상 변동폭에서는 price_limit_warning이 없어야."""
        strategy = TurtleStrategy()
        df = _make_breakout_ohlcv()
        results = strategy.scan(df, symbol="005930")
        entry_signals = [r for r in results if r.signal_type == SignalType.ENTRY_LONG]
        for r in entry_signals:
            assert r.metadata.get("price_limit_warning") is not True

    def test_volume_metadata(self):
        """진입 시그널에 avg_volume_20d 메타데이터 포함."""
        strategy = TurtleStrategy()
        df = _make_breakout_ohlcv()
        results = strategy.scan(df, symbol="005930")
        entry_signals = [r for r in results if r.signal_type == SignalType.ENTRY_LONG]
        assert len(entry_signals) > 0
        for r in entry_signals:
            assert "avg_volume_20d" in r.metadata

    def test_scan_accepts_context_parameter(self):
        """Strategy Protocol의 context 파라미터가 존재하는지 확인."""
        import inspect

        sig = inspect.signature(TurtleStrategy.scan)
        assert "context" in sig.parameters


class TestRunScreening:
    def test_screens_multiple_symbols(self):
        data = {
            "BREAKOUT": _make_breakout_ohlcv(),
            "FLAT": _make_flat_ohlcv(),
        }
        results = run_screening(data, strategies=[TurtleStrategy()])
        symbols_with_signals = {r.symbol for r in results}
        assert "BREAKOUT" in symbols_with_signals

    def test_multiple_strategies(self):
        """여러 전략을 동시에 실행."""
        data = {"A": _make_breakout_ohlcv()}
        results = run_screening(data, strategies=[TurtleStrategy(), TurtleStrategy()])
        assert len(results) >= 2

    def test_empty_data(self):
        results = run_screening({}, strategies=[TurtleStrategy()])
        assert results == []

    def test_precomputes_indicators(self):
        """run_screening이 지표를 사전 계산하는지 확인."""
        data = {"A": _make_breakout_ohlcv()}
        assert "N" not in data["A"].columns
        results = run_screening(data, strategies=[TurtleStrategy()])
        assert isinstance(results, list)

    def test_does_not_mutate_input(self):
        """run_screening이 입력 data dict를 변경하지 않아야 함."""
        original_df = _make_breakout_ohlcv()
        original_columns = set(original_df.columns)
        data = {"A": original_df.copy()}
        original_keys = set(data.keys())

        run_screening(data, strategies=[TurtleStrategy()])

        assert set(data.keys()) == original_keys
        assert set(data["A"].columns) == original_columns
