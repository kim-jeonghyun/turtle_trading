"""
src/types.py 단위 테스트
- Enum 직렬화/역직렬화
- 문자열 비교 호환
- 모든 Enum 값 존재 확인
"""

import pytest
import json
from src.types import Direction, SignalType, AssetGroup, OrderStatus


class TestDirection:
    def test_values(self):
        assert Direction.LONG.value == "LONG"
        assert Direction.SHORT.value == "SHORT"

    def test_string_comparison(self):
        """direction: str 필드와의 호환"""
        assert Direction.LONG.value == "LONG"
        assert Direction.SHORT.value == "SHORT"

    def test_enum_identity(self):
        assert Direction.LONG == Direction.LONG
        assert Direction.LONG != Direction.SHORT

    def test_from_value(self):
        assert Direction("LONG") == Direction.LONG
        assert Direction("SHORT") == Direction.SHORT

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            Direction("INVALID")

    def test_iteration(self):
        values = [d.value for d in Direction]
        assert len(values) == 2
        assert "LONG" in values
        assert "SHORT" in values


class TestSignalType:
    def test_all_values(self):
        assert SignalType.ENTRY_LONG.value == "entry_long"
        assert SignalType.ENTRY_SHORT.value == "entry_short"
        assert SignalType.EXIT_LONG.value == "exit_long"
        assert SignalType.EXIT_SHORT.value == "exit_short"
        assert SignalType.PYRAMID_LONG.value == "pyramid_long"
        assert SignalType.PYRAMID_SHORT.value == "pyramid_short"
        assert SignalType.STOP_LOSS.value == "stop_loss"

    def test_json_serialization(self):
        """JSON 직렬화 호환"""
        data = {"type": SignalType.ENTRY_LONG.value}
        serialized = json.dumps(data)
        loaded = json.loads(serialized)
        assert loaded["type"] == "entry_long"

    def test_all_signal_types_json_roundtrip(self):
        """모든 SignalType을 JSON으로 왕복"""
        for st in SignalType:
            serialized = json.dumps({"signal": st.value})
            loaded = json.loads(serialized)
            assert SignalType(loaded["signal"]) == st

    def test_count(self):
        assert len(list(SignalType)) == 7

    def test_from_value(self):
        assert SignalType("entry_long") == SignalType.ENTRY_LONG
        assert SignalType("stop_loss") == SignalType.STOP_LOSS


class TestAssetGroup:
    def test_all_groups_exist(self):
        groups = [g.value for g in AssetGroup]
        assert "us_equity" in groups
        assert "kr_equity" in groups
        assert "crypto" in groups
        assert "commodity" in groups
        assert "bond" in groups
        assert "inverse" in groups

    def test_additional_groups(self):
        groups = [g.value for g in AssetGroup]
        assert "asia_equity" in groups
        assert "currency" in groups

    def test_count(self):
        assert len(list(AssetGroup)) == 8

    def test_from_value(self):
        assert AssetGroup("us_equity") == AssetGroup.US_EQUITY
        assert AssetGroup("crypto") == AssetGroup.CRYPTO


class TestOrderStatus:
    def test_all_statuses(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.FAILED.value == "failed"
        assert OrderStatus.DRY_RUN.value == "dry_run"

    def test_additional_statuses(self):
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.UNKNOWN.value == "unknown"

    def test_count(self):
        assert len(list(OrderStatus)) == 8

    def test_from_value(self):
        assert OrderStatus("pending") == OrderStatus.PENDING
        assert OrderStatus("filled") == OrderStatus.FILLED

    def test_json_roundtrip(self):
        for status in OrderStatus:
            serialized = json.dumps({"status": status.value})
            loaded = json.loads(serialized)
            assert OrderStatus(loaded["status"]) == status
