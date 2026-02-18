"""
inverse_filter.py 단위 테스트
- is_inverse_etf() 감지
- Decay 계산
- 강제 청산 조건 (최대 보유일, 괴리율 임계)
- 비 Inverse ETF는 트리거 안됨
"""

import pytest
from datetime import datetime
from src.inverse_filter import InverseETFFilter, InverseETFConfig, InverseHolding, ExitReason


class TestInverseETFConfig:
    def test_dataclass_fields(self):
        config = InverseETFConfig(
            symbol="SH",
            leverage=-1,
            underlying="SPY",
            max_holding_days=20,
            decay_threshold_pct=5.0,
        )
        assert config.symbol == "SH"
        assert config.leverage == -1
        assert config.underlying == "SPY"
        assert config.max_holding_days == 20
        assert config.decay_threshold_pct == 5.0


class TestInverseHolding:
    def test_default_values(self):
        holding = InverseHolding(
            symbol="SH",
            entry_date=datetime(2025, 1, 1),
            entry_inverse_price=100.0,
            entry_underlying_price=500.0,
        )
        assert holding.holding_days == 0
        assert holding.current_decay_pct == 0.0


class TestExitReason:
    def test_values(self):
        assert ExitReason.MAX_HOLDING_DAYS.value == "max_holding_days"
        assert ExitReason.DECAY_THRESHOLD.value == "decay_threshold"


class TestIsInverseETF:
    def test_known_inverse_etfs(self):
        f = InverseETFFilter()
        assert f.is_inverse_etf("SH")
        assert f.is_inverse_etf("PSQ")
        assert f.is_inverse_etf("SDS")
        assert f.is_inverse_etf("SQQQ")
        assert f.is_inverse_etf("SPXU")

    def test_non_inverse_etfs(self):
        f = InverseETFFilter()
        assert not f.is_inverse_etf("SPY")
        assert not f.is_inverse_etf("QQQ")
        assert not f.is_inverse_etf("AAPL")
        assert not f.is_inverse_etf("BTC-USD")

    def test_get_config_known(self):
        f = InverseETFFilter()
        config = f.get_config("SH")
        assert config is not None
        assert config.leverage == -1
        assert config.underlying == "SPY"
        assert config.max_holding_days == 20

    def test_get_config_unknown(self):
        f = InverseETFFilter()
        assert f.get_config("SPY") is None

    def test_get_config_sqqq(self):
        f = InverseETFFilter()
        config = f.get_config("SQQQ")
        assert config.leverage == -3
        assert config.underlying == "QQQ"
        assert config.max_holding_days == 10
        assert config.decay_threshold_pct == 3.0


class TestOnEntry:
    def test_entry_creates_holding(self):
        f = InverseETFFilter()
        f.on_entry("SH", datetime(2025, 1, 1), 30.0, 500.0)
        assert "SH" in f.holdings
        assert f.holdings["SH"].entry_inverse_price == 30.0
        assert f.holdings["SH"].entry_underlying_price == 500.0

    def test_entry_non_inverse_ignored(self):
        f = InverseETFFilter()
        f.on_entry("SPY", datetime(2025, 1, 1), 500.0, 500.0)
        assert "SPY" not in f.holdings


class TestDecayCalculation:
    def test_no_decay(self):
        """기초자산 변동 없으면 decay 없음"""
        f = InverseETFFilter()
        # leverage=-1, entry_inv=100, curr_inv=100, entry_und=500, curr_und=500
        # underlying_return = 0, theoretical = 0, actual = 0 -> decay = 0
        decay = f._calculate_decay(-1, 100.0, 100.0, 500.0, 500.0)
        assert decay == 0.0

    def test_theoretical_tracking(self):
        """완벽한 추적 (decay 없음)"""
        f = InverseETFFilter()
        # underlying up 10%: 500 -> 550
        # leverage=-1 -> theoretical=-10%
        # inverse should be 90: actual_return = (90-100)/100 = -10%
        decay = f._calculate_decay(-1, 100.0, 90.0, 500.0, 550.0)
        assert abs(decay) < 0.01

    def test_positive_decay(self):
        """실제 수익률이 이론보다 높은 경우"""
        f = InverseETFFilter()
        # underlying up 10%: 500 -> 550
        # theoretical = -1 * 0.1 = -0.1 = -10%
        # actual: entry_inv=100, curr_inv=92 -> actual = -8%
        # decay = (-0.08 - (-0.10)) * 100 = 2%
        decay = f._calculate_decay(-1, 100.0, 92.0, 500.0, 550.0)
        assert abs(decay - 2.0) < 0.01

    def test_negative_decay(self):
        """실제 수익률이 이론보다 낮은 경우"""
        f = InverseETFFilter()
        # underlying up 10%: 500 -> 550
        # theoretical = -10%
        # actual: entry_inv=100, curr_inv=88 -> actual = -12%
        # decay = (-0.12 - (-0.10)) * 100 = -2%
        decay = f._calculate_decay(-1, 100.0, 88.0, 500.0, 550.0)
        assert abs(decay - (-2.0)) < 0.01

    def test_zero_entry_prices(self):
        f = InverseETFFilter()
        assert f._calculate_decay(-1, 0.0, 100.0, 500.0, 550.0) == 0.0
        assert f._calculate_decay(-1, 100.0, 100.0, 0.0, 550.0) == 0.0

    def test_3x_leverage_decay(self):
        """3배 레버리지 decay"""
        f = InverseETFFilter()
        # underlying up 5%: 500 -> 525
        # theoretical = -3 * 0.05 = -15%
        # actual: entry_inv=100, curr_inv=82 -> actual = -18%
        # decay = (-0.18 - (-0.15)) * 100 = -3%
        decay = f._calculate_decay(-3, 100.0, 82.0, 500.0, 525.0)
        assert abs(decay - (-3.0)) < 0.01


class TestOnDailyUpdate:
    def test_update_increments_holding_days(self):
        f = InverseETFFilter()
        f.on_entry("SH", datetime(2025, 1, 1), 30.0, 500.0)
        f.on_daily_update("SH", 29.5, 505.0)
        assert f.holdings["SH"].holding_days == 1

    def test_update_multiple_days(self):
        f = InverseETFFilter()
        f.on_entry("SH", datetime(2025, 1, 1), 30.0, 500.0)
        for i in range(5):
            f.on_daily_update("SH", 29.5 - i * 0.1, 505.0 + i)
        assert f.holdings["SH"].holding_days == 5

    def test_update_nonexistent_symbol(self):
        f = InverseETFFilter()
        # Should not raise
        f.on_daily_update("NONEXIST", 100.0, 500.0)

    def test_update_calculates_decay(self):
        f = InverseETFFilter()
        f.on_entry("SH", datetime(2025, 1, 1), 100.0, 500.0)
        # Perfect tracking: underlying +10%, inverse -10%
        f.on_daily_update("SH", 90.0, 550.0)
        assert f.holdings["SH"].current_decay_pct == pytest.approx(0.0, abs=0.01)


class TestShouldForceExit:
    def test_max_holding_days_exceeded(self):
        f = InverseETFFilter()
        f.on_entry("SH", datetime(2025, 1, 1), 30.0, 500.0)
        # SH has max_holding_days=20, entry_date is far in the past (>413 days)
        # should_force_exit uses max(holding.holding_days, (now - entry_date).days)

        should_exit, reason, msg = f.should_force_exit("SH", 30.0, 500.0)
        assert should_exit
        assert reason == ExitReason.MAX_HOLDING_DAYS
        assert "최대 보유일" in msg

    def test_within_holding_limit(self):
        from datetime import timedelta
        f = InverseETFFilter()
        # Use today's date so actual_holding_days = 0
        f.on_entry("SH", datetime.now(), 30.0, 500.0)
        for _ in range(10):
            f.on_daily_update("SH", 30.0, 500.0)

        should_exit, reason, msg = f.should_force_exit("SH", 30.0, 500.0)
        assert not should_exit
        assert reason is None

    def test_decay_threshold_exceeded(self):
        f = InverseETFFilter()
        # SH: decay_threshold=5.0%, use today's date to avoid max_holding_days trigger
        f.on_entry("SH", datetime.now(), 100.0, 500.0)
        f.on_daily_update("SH", 100.0, 500.0)

        # Create large decay by having actual diverge from theoretical
        # underlying up 10%: 500 -> 550, theoretical = -10%, actual = -3%
        # decay = (-0.03 - (-0.10)) * 100 = 7% (exceeds 5% threshold)
        should_exit, reason, msg = f.should_force_exit("SH", 97.0, 550.0)
        assert should_exit
        assert reason == ExitReason.DECAY_THRESHOLD
        assert "괴리율" in msg

    def test_unknown_symbol(self):
        f = InverseETFFilter()
        should_exit, reason, msg = f.should_force_exit("SPY", 500.0, 500.0)
        assert not should_exit
        assert reason is None
        assert msg == ""

    def test_no_holding_for_symbol(self):
        f = InverseETFFilter()
        should_exit, reason, msg = f.should_force_exit("SH", 30.0, 500.0)
        assert not should_exit

    def test_sqqq_shorter_holding_limit(self):
        """SQQQ: max_holding_days=10, 더 짧은 제한"""
        f = InverseETFFilter()
        f.on_entry("SQQQ", datetime(2025, 1, 1), 20.0, 400.0)
        for _ in range(10):
            f.on_daily_update("SQQQ", 20.0, 400.0)

        should_exit, reason, msg = f.should_force_exit("SQQQ", 20.0, 400.0)
        assert should_exit
        assert reason == ExitReason.MAX_HOLDING_DAYS


class TestOnExit:
    def test_exit_removes_holding(self):
        f = InverseETFFilter()
        f.on_entry("SH", datetime(2025, 1, 1), 30.0, 500.0)
        assert "SH" in f.holdings
        f.on_exit("SH")
        assert "SH" not in f.holdings

    def test_exit_nonexistent_no_error(self):
        f = InverseETFFilter()
        f.on_exit("NONEXIST")  # Should not raise


class TestKnownInverseETFs:
    def test_all_known_etfs_have_configs(self):
        f = InverseETFFilter()
        for symbol in ["SH", "PSQ", "SDS", "SQQQ", "SPXU"]:
            config = f.get_config(symbol)
            assert config is not None
            assert config.leverage < 0
            assert config.max_holding_days > 0
            assert config.decay_threshold_pct > 0

    def test_leverage_values(self):
        f = InverseETFFilter()
        assert f.get_config("SH").leverage == -1
        assert f.get_config("PSQ").leverage == -1
        assert f.get_config("SDS").leverage == -2
        assert f.get_config("SQQQ").leverage == -3
        assert f.get_config("SPXU").leverage == -3
