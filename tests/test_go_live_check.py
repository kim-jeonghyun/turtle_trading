"""tests/test_go_live_check.py — Go-Live 자동 검증 체크리스트 테스트."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path so scripts/ and src/ are importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import go_live_check  # noqa: E402

# ---------------------------------------------------------------------------
# 체크 1: health_check 전체 통과
# ---------------------------------------------------------------------------


def test_health_check_passes():
    """health_check 함수들이 모두 통과하면 True."""
    mock_hc = MagicMock()
    mock_hc.check_python_version.return_value = (True, "ok")
    mock_hc.check_data_directory.return_value = (True, "ok")
    mock_hc.check_python_packages.return_value = (True, "ok")
    mock_hc.check_position_files.return_value = (True, "ok")
    mock_hc.check_disk_space.return_value = (True, "ok")
    mock_hc.check_kill_switch.return_value = (True, "ok")
    mock_hc.check_position_sync_module.return_value = (True, "ok")
    mock_hc.check_vi_cb_detector.return_value = (True, "ok")

    with patch.dict(sys.modules, {"health_check": mock_hc}):
        ok, msg = go_live_check.check_health_check_passes()

    assert ok is True
    assert "통과" in msg


def test_health_check_fails_when_one_fails():
    """health_check 함수 중 하나라도 실패하면 False."""
    mock_hc = MagicMock()
    mock_hc.check_python_version.return_value = (True, "ok")
    mock_hc.check_data_directory.return_value = (False, "missing")
    mock_hc.check_python_packages.return_value = (True, "ok")
    mock_hc.check_position_files.return_value = (True, "ok")
    mock_hc.check_disk_space.return_value = (True, "ok")
    mock_hc.check_kill_switch.return_value = (True, "ok")
    mock_hc.check_position_sync_module.return_value = (True, "ok")
    mock_hc.check_vi_cb_detector.return_value = (True, "ok")

    with patch.dict(sys.modules, {"health_check": mock_hc}):
        ok, msg = go_live_check.check_health_check_passes()

    assert ok is False
    assert "실패" in msg


# ---------------------------------------------------------------------------
# 체크 2: KIS 토큰 발급
# ---------------------------------------------------------------------------


def test_kis_token_check():
    """KIS 환경변수 + 모듈 정상 시 True."""
    mock_kis = MagicMock()
    env_vars = {"KIS_APP_KEY": "test", "KIS_APP_SECRET": "test", "KIS_ACCOUNT_NO": "test"}
    with patch.dict(sys.modules, {"src.kis_api": mock_kis}):
        with patch.dict(os.environ, env_vars):
            ok, msg = go_live_check.check_kis_token()
    assert ok is True
    assert "정상" in msg


def test_kis_token_check_missing_env_vars():
    """KIS 환경변수 미설정 시 False."""
    mock_kis = MagicMock()
    with patch.dict(sys.modules, {"src.kis_api": mock_kis}):
        with patch.dict(os.environ, {}, clear=True):
            ok, msg = go_live_check.check_kis_token()
    assert ok is False
    assert "미설정" in msg


def test_kis_token_check_fails_on_import_error():
    """KISAPIClient import 실패 시 False."""
    with patch.dict(sys.modules, {"src.kis_api": None}):
        ok, msg = go_live_check.check_kis_token()
    assert ok is False


# ---------------------------------------------------------------------------
# 체크 3: KIS 잔고 조회
# ---------------------------------------------------------------------------


def test_kis_balance_check():
    """get_balance + get_daily_fills 메서드 존재 시 True."""
    mock_client = MagicMock()
    mock_client.get_balance = MagicMock()
    mock_client.get_daily_fills = MagicMock()
    mock_module = MagicMock()
    mock_module.KISAPIClient = mock_client

    with patch.dict(sys.modules, {"src.kis_api": mock_module}):
        ok, msg = go_live_check.check_kis_balance()
    assert ok is True
    assert "get_balance" in msg or "메서드" in msg


def test_kis_balance_check_missing_method():
    """get_balance 메서드 없으면 False."""
    mock_client = MagicMock(spec=[])  # no attributes
    mock_module = MagicMock()
    mock_module.KISAPIClient = mock_client

    with patch.dict(sys.modules, {"src.kis_api": mock_module}):
        ok, msg = go_live_check.check_kis_balance()
    assert ok is False
    assert "없음" in msg


# ---------------------------------------------------------------------------
# 체크 4: 포지션 동기화
# ---------------------------------------------------------------------------


def test_position_sync_check():
    """PositionSyncVerifier.verify() + 생성자 시그니처 검증 시 True."""
    # 실제 모듈이 importable하므로 직접 호출
    ok, msg = go_live_check.check_position_sync()
    assert ok is True
    assert "verify" in msg or "확인" in msg


def test_position_sync_check_missing_verify():
    """PositionSyncVerifier.verify 없으면 False."""
    mock_verifier = MagicMock(spec=[])
    mock_module = MagicMock()
    mock_module.PositionSyncVerifier = mock_verifier

    with patch.dict(sys.modules, {"src.position_sync": mock_module}):
        ok, msg = go_live_check.check_position_sync()
    assert ok is False
    assert "메서드 없음" in msg


# ---------------------------------------------------------------------------
# 체크 5: 데이터 무결성
# ---------------------------------------------------------------------------


def test_data_integrity_check(tmp_path):
    """validate_data.py 존재 시 True."""
    fake_script = tmp_path / "validate_data.py"
    fake_script.write_text("# validate")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "validate_data.py").write_text("# validate")
        ok, msg = go_live_check.check_data_integrity()

    assert ok is True
    assert "존재" in msg


def test_data_integrity_check_missing(tmp_path):
    """validate_data.py 없으면 False."""
    (tmp_path / "scripts").mkdir()
    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_data_integrity()
    assert ok is False
    assert "없음" in msg


# ---------------------------------------------------------------------------
# 체크 6: 최근 OHLCV 데이터
# ---------------------------------------------------------------------------


def test_recent_ohlcv_exists(tmp_path):
    """최신 parquet 파일이 2일 이내면 True."""
    ohlcv_dir = tmp_path / "data" / "ohlcv"
    ohlcv_dir.mkdir(parents=True)
    parquet = ohlcv_dir / "000080_ohlcv.parquet"
    parquet.write_bytes(b"fake")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_recent_ohlcv()

    assert ok is True
    assert "OHLCV" in msg or "parquet" in msg.lower() or "시간 전" in msg


def test_recent_ohlcv_stale(tmp_path):
    """parquet 파일이 3일 이상 오래됐으면 False."""
    import os
    import time

    ohlcv_dir = tmp_path / "data" / "ohlcv"
    ohlcv_dir.mkdir(parents=True)
    parquet = ohlcv_dir / "000080_ohlcv.parquet"
    parquet.write_bytes(b"fake")

    # Set mtime to 3 days ago
    old_time = time.time() - (3 * 86400 + 60)
    os.utime(parquet, (old_time, old_time))

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_recent_ohlcv()

    assert ok is False
    assert "일 전" in msg


def test_recent_ohlcv_no_dir(tmp_path):
    """ohlcv 디렉토리 없으면 False."""
    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_recent_ohlcv()
    assert ok is False
    assert "디렉토리 없음" in msg


def test_recent_ohlcv_empty_dir(tmp_path):
    """ohlcv 디렉토리는 있지만 parquet 없으면 False."""
    ohlcv_dir = tmp_path / "data" / "ohlcv"
    ohlcv_dir.mkdir(parents=True)
    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_recent_ohlcv()
    assert ok is False
    assert "없음" in msg


# ---------------------------------------------------------------------------
# 체크 7: 킬 스위치
# ---------------------------------------------------------------------------


def test_kill_switch_enabled():
    """킬 스위치 활성화 상태면 True."""
    mock_ks = MagicMock()
    mock_ks.is_trading_enabled = True
    mock_module = MagicMock()
    mock_module.KillSwitch.return_value = mock_ks

    with patch.dict(sys.modules, {"src.kill_switch": mock_module}):
        ok, msg = go_live_check.check_kill_switch()

    assert ok is True
    assert "활성화" in msg


def test_kill_switch_disabled():
    """킬 스위치 비활성화 상태면 False."""
    mock_ks = MagicMock()
    mock_ks.is_trading_enabled = False
    mock_module = MagicMock()
    mock_module.KillSwitch.return_value = mock_ks

    with patch.dict(sys.modules, {"src.kill_switch": mock_module}):
        ok, msg = go_live_check.check_kill_switch()

    assert ok is False
    assert "비활성화" in msg


# ---------------------------------------------------------------------------
# 체크 8: 백테스트 최소 성과
# ---------------------------------------------------------------------------


def _write_backtest_csv(path: Path, rows: list[dict]) -> None:
    """헬퍼: 백테스트 CSV 파일 작성."""
    import csv

    fieldnames = rows[0].keys() if rows else ["symbol", "pnl"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_backtest_performance_pass(tmp_path):
    """PF > 1.0인 최신 백테스트 결과면 True."""
    bt_dir = tmp_path / "data" / "backtest_results"
    bt_dir.mkdir(parents=True)
    trades = [
        {"symbol": "SPY", "pnl": "500"},
        {"symbol": "QQQ", "pnl": "300"},
        {"symbol": "IWM", "pnl": "-200"},
    ]
    _write_backtest_csv(bt_dir / "result_2026.csv", trades)

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_backtest_performance()

    assert ok is True
    assert "PF" in msg
    assert "3건" in msg


def test_backtest_performance_fail_pf(tmp_path):
    """PF < 1.0이면 False."""
    bt_dir = tmp_path / "data" / "backtest_results"
    bt_dir.mkdir(parents=True)
    trades = [
        {"symbol": "SPY", "pnl": "100"},
        {"symbol": "QQQ", "pnl": "-500"},
    ]
    _write_backtest_csv(bt_dir / "result_2026.csv", trades)

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_backtest_performance()

    assert ok is False
    assert "PF" in msg


def test_backtest_performance_stale(tmp_path):
    """백테스트 결과가 30일 초과 오래됐으면 False."""
    import os
    import time

    bt_dir = tmp_path / "data" / "backtest_results"
    bt_dir.mkdir(parents=True)
    trades = [{"symbol": "SPY", "pnl": "500"}]
    result_file = bt_dir / "result_old.csv"
    _write_backtest_csv(result_file, trades)

    old_time = time.time() - (31 * 86400)
    os.utime(result_file, (old_time, old_time))

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_backtest_performance()

    assert ok is False
    assert "일 전" in msg


def test_backtest_performance_no_dir(tmp_path):
    """data/backtest_results/ 없으면 False."""
    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_backtest_performance()
    assert ok is False
    assert "디렉토리 없음" in msg


def test_backtest_performance_no_files(tmp_path):
    """data/backtest_results/ 있지만 파일 없으면 False."""
    (tmp_path / "data" / "backtest_results").mkdir(parents=True)
    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_backtest_performance()
    assert ok is False
    assert "없음" in msg


def test_backtest_performance_empty_csv(tmp_path):
    """CSV 헤더만 있고 데이터 없으면 False."""
    bt_dir = tmp_path / "data" / "backtest_results"
    bt_dir.mkdir(parents=True)
    (bt_dir / "empty.csv").write_text("symbol,pnl\n")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_backtest_performance()

    assert ok is False
    assert "데이터 없음" in msg


def test_backtest_performance_missing_pnl_column(tmp_path):
    """pnl 컬럼 없으면 False."""
    bt_dir = tmp_path / "data" / "backtest_results"
    bt_dir.mkdir(parents=True)
    (bt_dir / "bad.csv").write_text("symbol,direction\nSPY,LONG\n")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_backtest_performance()

    assert ok is False
    assert "pnl" in msg


# ---------------------------------------------------------------------------
# 체크 9: 알림 채널
# ---------------------------------------------------------------------------


def test_notification_check():
    """NotificationManager import 성공 시 True."""
    mock_module = MagicMock()
    with patch.dict(sys.modules, {"src.notifier": mock_module}):
        ok, msg = go_live_check.check_notification()
    assert ok is True
    assert "정상" in msg


def test_notification_check_fails():
    """NotificationManager import 실패 시 False."""
    with patch.dict(sys.modules, {"src.notifier": None}):
        ok, msg = go_live_check.check_notification()
    assert ok is False


# ---------------------------------------------------------------------------
# 체크 10: dry_run 주문
# ---------------------------------------------------------------------------


def test_dry_run_order_check():
    """AutoTrader 런타임 통합 검증 통과."""
    ok, msg = go_live_check.check_dry_run_order()
    assert ok is True
    assert "통합" in msg or "검증" in msg


# ---------------------------------------------------------------------------
# 체크 11: 안전 가드 모듈
# ---------------------------------------------------------------------------


def test_trading_guard_module(tmp_path):
    """TradingGuard 인스턴스 생성 + 기능 검증 통과."""
    ok, msg = go_live_check.check_trading_guard_module()
    assert ok is True
    assert "검증" in msg or "통과" in msg


def test_trading_guard_module_missing():
    """src/trading_guard.py 없으면 False."""
    with patch.dict(sys.modules, {"src.trading_guard": None}):
        ok, msg = go_live_check.check_trading_guard_module()
    assert ok is False


def test_trading_guard_module_exception():
    """TradingGuard 생성 실패 시 False."""
    mock_module = MagicMock()
    mock_module.TradingGuard.side_effect = RuntimeError("test")
    mock_module.TradingLimits = MagicMock()
    with patch.dict(sys.modules, {"src.trading_guard": mock_module, "src.kill_switch": MagicMock()}):
        ok, msg = go_live_check.check_trading_guard_module()
    assert ok is False


# ---------------------------------------------------------------------------
# 체크 13: CostAnalyzer 모듈
# ---------------------------------------------------------------------------


def test_cost_analyzer_module():
    """CostAnalyzer 인스턴스 생성 + 기능 검증 통과."""
    ok, msg = go_live_check.check_cost_analyzer_module()
    assert ok is True
    assert "검증" in msg or "통과" in msg


def test_cost_analyzer_module_missing():
    """src/cost_analyzer.py 없으면 False."""
    with patch.dict(sys.modules, {"src.cost_analyzer": None}):
        ok, msg = go_live_check.check_cost_analyzer_module()
    assert ok is False


def test_cost_analyzer_module_exception():
    """CostAnalyzer 생성 실패 시 False."""
    mock_module = MagicMock()
    mock_module.CostAnalyzer.side_effect = RuntimeError("test")
    with patch.dict(sys.modules, {"src.cost_analyzer": mock_module}):
        ok, msg = go_live_check.check_cost_analyzer_module()
    assert ok is False


# ---------------------------------------------------------------------------
# 체크 12: 상관그룹 일관성
# ---------------------------------------------------------------------------


def test_correlation_consistency(tmp_path):
    """universe.yaml과 correlation_groups.yaml 일관성 있으면 True."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    universe_yaml = config_dir / "universe.yaml"
    universe_yaml.write_text(
        "symbols:\n  us_equity:\n    - {symbol: SPY, name: S&P 500 ETF}\n    - {symbol: QQQ, name: Nasdaq 100 ETF}\n"
    )

    corr_yaml = config_dir / "correlation_groups.yaml"
    corr_yaml.write_text("groups:\n  us_equity:\n    - SPY\n    - QQQ\n")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_correlation_groups_consistency()

    assert ok is True


def test_correlation_consistency_all_unmapped(tmp_path):
    """모든 universe 심볼이 correlation_groups에 없으면 False."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    (config_dir / "universe.yaml").write_text("symbols:\n  us_equity:\n    - {symbol: SPY}\n    - {symbol: QQQ}\n")
    (config_dir / "correlation_groups.yaml").write_text("groups:\n  other:\n    - XYZ\n")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_correlation_groups_consistency()

    assert ok is False
    assert "미매핑" in msg


def test_correlation_consistency_partial_unmapped(tmp_path):
    """일부 미매핑 심볼은 허용 (True)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    (config_dir / "universe.yaml").write_text(
        "symbols:\n  us_equity:\n    - {symbol: SPY}\n    - {symbol: NEW_SYMBOL}\n"
    )
    (config_dir / "correlation_groups.yaml").write_text("groups:\n  us_equity:\n    - SPY\n")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_correlation_groups_consistency()

    assert ok is True
    assert "허용" in msg


def test_correlation_consistency_missing_universe(tmp_path):
    """universe.yaml 없으면 False."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "correlation_groups.yaml").write_text("groups: {}")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_correlation_groups_consistency()

    assert ok is False
    assert "universe.yaml" in msg


def test_correlation_consistency_missing_corr(tmp_path):
    """correlation_groups.yaml 없으면 False."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "universe.yaml").write_text("symbols: {}")

    with patch.object(go_live_check, "PROJECT_ROOT", tmp_path):
        ok, msg = go_live_check.check_correlation_groups_consistency()

    assert ok is False
    assert "correlation_groups.yaml" in msg


# ---------------------------------------------------------------------------
# 전체 통합: exit code 검증
# ---------------------------------------------------------------------------


def test_all_checks_pass_exit_0(monkeypatch):
    """모든 체크가 통과하면 exit code 0."""
    monkeypatch.setattr(sys, "argv", ["go_live_check.py"])
    patched = [(name, lambda: (True, "mock pass")) for name, _ in go_live_check.ALL_CHECKS]

    with patch.object(go_live_check, "ALL_CHECKS", patched):
        with pytest.raises(SystemExit) as exc_info:
            go_live_check.main()
    assert exc_info.value.code == 0


def test_any_check_fail_exit_1(monkeypatch):
    """하나라도 실패하면 exit code 1."""
    monkeypatch.setattr(sys, "argv", ["go_live_check.py"])
    checks_copy = list(go_live_check.ALL_CHECKS)
    first_name, _ = checks_copy[0]
    patched = [(first_name, lambda: (False, "forced fail"))]
    for name, _ in checks_copy[1:]:
        patched.append((name, lambda: (True, "mock pass")))

    with patch.object(go_live_check, "ALL_CHECKS", patched):
        with pytest.raises(SystemExit) as exc_info:
            go_live_check.main()
    assert exc_info.value.code == 1
