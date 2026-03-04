"""
universe_manager.py 단위 테스트
- 기본 로딩 (파일 없을 때)
- YAML 로딩
- CSV 로딩
- get_enabled_symbols(), get_symbols_by_group(), get_inverse_etfs()
- get_group_mapping()
"""

import os
import tempfile

from src.types import AssetGroup
from src.universe_manager import Asset, UniverseManager


class TestAsset:
    def test_basic_asset(self):
        asset = Asset(
            symbol="SPY",
            name="S&P 500 ETF",
            country="US",
            asset_type="Index ETF",
            group=AssetGroup.US_EQUITY,
        )
        assert asset.symbol == "SPY"
        assert asset.name == "S&P 500 ETF"
        assert asset.enabled is True
        assert asset.leverage == 1.0
        assert asset.underlying is None

    def test_is_inverse_positive_leverage(self):
        asset = Asset("SPY", "S&P 500", "US", "ETF", AssetGroup.US_EQUITY, leverage=1.0)
        assert not asset.is_inverse

    def test_is_inverse_negative_leverage(self):
        asset = Asset("SH", "Inverse", "US", "ETF", AssetGroup.INVERSE, leverage=-1.0)
        assert asset.is_inverse

    def test_is_inverse_3x(self):
        asset = Asset("SQQQ", "3x Inverse", "US", "ETF", AssetGroup.INVERSE, leverage=-3.0)
        assert asset.is_inverse

    def test_disabled_asset(self):
        asset = Asset("SPY", "S&P 500", "US", "ETF", AssetGroup.US_EQUITY, enabled=False)
        assert not asset.enabled


class TestDefaultLoading:
    def test_loads_defaults_no_file(self):
        """파일 없으면 기본 유니버스 로드"""
        um = UniverseManager()
        assert len(um.assets) > 0

    def test_default_symbols_present(self):
        um = UniverseManager()
        symbols = um.get_enabled_symbols()
        assert "SPY" in symbols
        assert "QQQ" in symbols
        assert "DIA" in symbols

    def test_default_has_inverse(self):
        um = UniverseManager()
        inverses = um.get_inverse_etfs()
        assert "SH" in inverses
        assert "SQQQ" in inverses

    def test_default_has_commodity(self):
        um = UniverseManager()
        commodities = um.get_symbols_by_group(AssetGroup.COMMODITY)
        assert "GLD" in commodities

    def test_default_has_bond(self):
        um = UniverseManager()
        bonds = um.get_symbols_by_group(AssetGroup.BOND)
        assert "TLT" in bonds

    def test_nonexistent_yaml_loads_defaults(self):
        um = UniverseManager(yaml_path="/nonexistent/path/universe.yaml")
        symbols = um.get_enabled_symbols()
        assert "SPY" in symbols


class TestYAMLLoading:
    def test_load_from_yaml(self):
        yaml_content = """
symbols:
  us_equity:
    - {symbol: AAPL, name: "Apple", group: us_equity}
    - {symbol: MSFT, name: "Microsoft", group: us_equity}
  commodity:
    - {symbol: GLD, name: "Gold ETF", group: commodity}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                symbols = um.get_enabled_symbols()
                assert "AAPL" in symbols
                assert "MSFT" in symbols
                assert "GLD" in symbols
                assert len(symbols) == 3
            finally:
                os.unlink(f.name)

    def test_yaml_group_mapping(self):
        yaml_content = """
symbols:
  us_equity:
    - {symbol: SPY, name: "S&P 500", group: us_equity}
  bond:
    - {symbol: TLT, name: "Treasury", group: bond}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                assert um.get_symbols_by_group(AssetGroup.US_EQUITY) == ["SPY"]
                assert um.get_symbols_by_group(AssetGroup.BOND) == ["TLT"]
            finally:
                os.unlink(f.name)

    def test_yaml_inverse_detection(self):
        yaml_content = """
symbols:
  inverse:
    - {symbol: SH, name: "S&P Inverse", group: inverse, underlying: SPY}
  us_equity:
    - {symbol: SPY, name: "S&P 500", group: us_equity}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                inverses = um.get_inverse_etfs()
                assert "SH" in inverses
                assert "SPY" not in inverses
            finally:
                os.unlink(f.name)

    def test_yaml_korean_symbols(self):
        yaml_content = """
symbols:
  kr_equity:
    - {symbol: "005930.KS", name: "삼성전자", group: kr_equity}
    - {symbol: "035420.KQ", name: "NAVER", group: kr_equity}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                kr_symbols = um.get_symbols_by_group(AssetGroup.KR_EQUITY)
                assert "005930.KS" in kr_symbols
                assert "035420.KQ" in kr_symbols
                # Country should be KR for .KS/.KQ symbols
                assert um.assets["005930.KS"].country == "KR"
                assert um.assets["035420.KQ"].country == "KR"
            finally:
                os.unlink(f.name)

    def test_yaml_empty_symbols_loads_defaults(self):
        yaml_content = """
other_key: value
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                # Should fall back to defaults since 'symbols' key is missing
                symbols = um.get_enabled_symbols()
                assert "SPY" in symbols
            finally:
                os.unlink(f.name)

    def test_yaml_empty_file_loads_defaults(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                symbols = um.get_enabled_symbols()
                assert "SPY" in symbols
            finally:
                os.unlink(f.name)

    def test_real_universe_yaml(self):
        """실제 config/universe.yaml 파일 로드"""
        yaml_path = "/Users/momo/dev/turtle_trading/config/universe.yaml"
        if os.path.exists(yaml_path):
            um = UniverseManager(yaml_path=yaml_path)
            symbols = um.get_enabled_symbols()
            assert "SPY" in symbols
            assert len(symbols) > 5


class TestCSVLoading:
    def test_load_from_csv(self):
        csv_content = "Ticker,Name,Country,Type\nAAPL,Apple,US,Stock\nMSFT,Microsoft,US,Stock\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            try:
                um = UniverseManager(csv_path=f.name)
                symbols = um.get_enabled_symbols()
                assert "AAPL" in symbols
                assert "MSFT" in symbols
            finally:
                os.unlink(f.name)

    def test_csv_alternative_columns(self):
        csv_content = "symbol,name,country,type\nTSLA,Tesla,US,Stock\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            try:
                um = UniverseManager(csv_path=f.name)
                symbols = um.get_enabled_symbols()
                assert "TSLA" in symbols
            finally:
                os.unlink(f.name)


class TestGetEnabledSymbols:
    def test_all_defaults_enabled(self):
        um = UniverseManager()
        symbols = um.get_enabled_symbols()
        assert len(symbols) == len(um.assets)

    def test_get_all_symbols_alias(self):
        um = UniverseManager()
        assert um.get_all_symbols() == um.get_enabled_symbols()


class TestGetSymbolsByGroup:
    def test_us_equity(self):
        um = UniverseManager()
        us = um.get_symbols_by_group(AssetGroup.US_EQUITY)
        assert "SPY" in us
        assert "QQQ" in us

    def test_empty_group(self):
        um = UniverseManager()
        asia = um.get_symbols_by_group(AssetGroup.ASIA_EQUITY)
        assert asia == []


class TestGetInverseETFs:
    def test_default_inverse_etfs(self):
        um = UniverseManager()
        inverses = um.get_inverse_etfs()
        assert "SH" in inverses
        assert "SQQQ" in inverses
        # Non-inverse should not be included
        assert "SPY" not in inverses


class TestGetGroupMapping:
    def test_mapping_keys(self):
        um = UniverseManager()
        mapping = um.get_group_mapping()
        assert "SPY" in mapping
        assert mapping["SPY"] == AssetGroup.US_EQUITY

    def test_mapping_inverse(self):
        um = UniverseManager()
        mapping = um.get_group_mapping()
        assert mapping["SH"] == AssetGroup.INVERSE

    def test_mapping_size(self):
        um = UniverseManager()
        mapping = um.get_group_mapping()
        assert len(mapping) == len(um.assets)


class TestGetDisplayName:
    def test_korean_stock_ks(self):
        """한국 종목(.KS)은 '이름 심볼' 형태"""
        yaml_content = """
symbols:
  kr_equity:
    - {symbol: "005930.KS", name: "삼성전자", group: kr_equity}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                assert um.get_display_name("005930.KS") == "삼성전자 005930.KS"
            finally:
                os.unlink(f.name)

    def test_korean_stock_kq(self):
        """한국 종목(.KQ)은 '이름 심볼' 형태"""
        yaml_content = """
symbols:
  kr_equity:
    - {symbol: "035420.KQ", name: "NAVER", group: kr_equity}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                assert um.get_display_name("035420.KQ") == "NAVER 035420.KQ"
            finally:
                os.unlink(f.name)

    def test_us_stock_returns_name(self):
        """미국 종목은 이름 반환 (SPY → S&P 500 ETF)"""
        um = UniverseManager()  # defaults
        assert um.get_display_name("SPY") == "S&P 500 ETF"

    def test_us_stock_name_equals_symbol(self):
        """이름이 심볼과 같으면 심볼 그대로"""
        yaml_content = """
symbols:
  us_equity:
    - {symbol: AAPL, name: "AAPL", group: us_equity}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                assert um.get_display_name("AAPL") == "AAPL"
            finally:
                os.unlink(f.name)

    def test_unknown_symbol(self):
        """유니버스에 없는 심볼은 그대로 반환"""
        um = UniverseManager()
        assert um.get_display_name("UNKNOWN") == "UNKNOWN"

    def test_unknown_korean_symbol(self):
        """유니버스에 없는 한국 심볼은 그대로 반환"""
        um = UniverseManager()
        assert um.get_display_name("999999.KS") == "999999.KS"


class TestShortRestricted:
    """short_restricted 필드 테스트"""

    def test_short_restricted_default_true(self):
        """Asset 기본값: short_restricted=True (공매도 불가, 안전 우선)"""
        asset = Asset(
            symbol="005930.KS",
            name="삼성전자",
            country="KR",
            asset_type="kr_equity",
            group=AssetGroup.KR_EQUITY,
        )
        assert asset.short_restricted is True

    def test_short_restricted_from_yaml(self):
        """YAML에서 short_restricted 파싱 — KR 종목은 True"""
        yaml_content = """
symbols:
  kr_equity:
    - {symbol: "005930.KS", name: "삼성전자", group: kr_equity, short_restricted: true}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                asset = um.assets["005930.KS"]
                assert asset.short_restricted is True
            finally:
                os.unlink(f.name)

    def test_us_equity_short_allowed(self):
        """YAML에서 short_restricted 파싱 — US 종목은 False"""
        yaml_content = """
symbols:
  us_equity:
    - {symbol: SPY, name: "S&P 500 ETF", group: us_equity, short_restricted: false}
    - {symbol: QQQ, name: "Nasdaq 100 ETF", group: us_equity, short_restricted: false}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                assert um.assets["SPY"].short_restricted is False
                assert um.assets["QQQ"].short_restricted is False
            finally:
                os.unlink(f.name)

    def test_default_us_equity_short_not_restricted(self):
        """기본 유니버스의 US equity는 short_restricted=False"""
        um = UniverseManager()
        assert um.assets["SPY"].short_restricted is False
        assert um.assets["QQQ"].short_restricted is False

    def test_yaml_missing_short_restricted_defaults_true(self):
        """YAML에 short_restricted 없으면 기본값 True (안전 우선)"""
        yaml_content = """
symbols:
  us_equity:
    - {symbol: AAPL, name: "Apple", group: us_equity}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                um = UniverseManager(yaml_path=f.name)
                assert um.assets["AAPL"].short_restricted is True
            finally:
                os.unlink(f.name)
