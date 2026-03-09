# Weekly Charts Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Issue #170 후속 — 테스트 커버리지 강화, 운영 가시성 개선, 보안 방어 보강

**Architecture:** 기존 `fetch_universe_charts.py`의 `_send_notification()` 함수에 대한 단위 테스트 추가, `main()` 알림 경로 테스트 보강, 전체 실패 시 ERROR 승격 + 성공 알림 추가, 테스트 안티패턴 수정, 경로 순회 방어 보강

**Tech Stack:** Python 3.12, pytest, unittest.mock, mplfinance, yfinance

**Issue:** #174 (생성 예정)

**Review Rubric Reference:**
- Code Review Agent: 7.3/10 → 목표 9.0/10
- Test Engineer Agent: NEEDS_IMPROVEMENT → 목표 SUFFICIENT
- Security Review Agent: 0 Critical, 0 High, 2 Medium → 목표 0 Medium

---

## Task 1: `_send_notification()` 단위 테스트

**Files:**
- Modify: `tests/test_chart_generator.py` (기존 `TestScriptEntryPoint` 클래스에 추가)
- Reference: `scripts/fetch_universe_charts.py:33-44`
- Reference: `src/script_helpers.py:56-81` (`load_config`)
- Reference: `src/script_helpers.py:83-111` (`setup_notifier`)

**Step 1: Write 3 failing tests for `_send_notification`**

```python
# tests/test_chart_generator.py — TestScriptEntryPoint 클래스 끝에 추가

class TestSendNotification:
    """_send_notification() 단위 테스트"""

    @patch("scripts.fetch_universe_charts.setup_notifier")
    @patch("scripts.fetch_universe_charts.load_config")
    def test_sends_message_when_channels_configured(self, mock_config, mock_setup):
        """채널이 설정되면 send_message가 호출된다"""
        from scripts.fetch_universe_charts import _send_notification

        mock_config.return_value = {"discord_webhook": "https://discord.com/api/webhooks/test"}
        mock_notifier = MagicMock()
        mock_notifier.channels = [MagicMock()]
        mock_notifier.send_message = AsyncMock()
        mock_setup.return_value = mock_notifier

        _send_notification("테스트 제목", "테스트 본문", NotificationLevel.ERROR)

        mock_config.assert_called_once()
        mock_setup.assert_called_once()
        mock_notifier.send_message.assert_called_once()
        msg = mock_notifier.send_message.call_args[0][0]
        assert msg.title == "테스트 제목"
        assert msg.level == NotificationLevel.ERROR

    @patch("scripts.fetch_universe_charts.setup_notifier")
    @patch("scripts.fetch_universe_charts.load_config")
    def test_skips_when_no_channels(self, mock_config, mock_setup):
        """채널 미설정 시 send_message를 호출하지 않는다"""
        from scripts.fetch_universe_charts import _send_notification

        mock_config.return_value = {}
        mock_notifier = MagicMock()
        mock_notifier.channels = []  # 빈 채널
        mock_setup.return_value = mock_notifier

        _send_notification("제목", "본문", NotificationLevel.WARNING)

        mock_notifier.send_message.assert_not_called()

    @patch("scripts.fetch_universe_charts.load_config")
    def test_catches_exception_without_propagating(self, mock_config):
        """load_config 예외 시 경고 로그만 남기고 전파하지 않는다"""
        from scripts.fetch_universe_charts import _send_notification

        mock_config.side_effect = RuntimeError("config load failed")

        # 예외가 전파되지 않아야 함
        _send_notification("제목", "본문", NotificationLevel.ERROR)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chart_generator.py::TestSendNotification -v`
Expected: FAIL (import errors — need to add imports)

**Step 3: Add required imports to test file**

```python
# tests/test_chart_generator.py 상단 imports에 추가
from unittest.mock import AsyncMock, MagicMock, patch
from src.notifier import NotificationLevel
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chart_generator.py::TestSendNotification -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add tests/test_chart_generator.py
git commit -m "[#174] test: _send_notification 단위 테스트 3건 추가"
```

---

## Task 2: `main()` 알림 경로 테스트

**Files:**
- Modify: `tests/test_chart_generator.py` (기존 `TestScriptEntryPoint` 보강)
- Reference: `scripts/fetch_universe_charts.py:64-75` (Universe 로드 실패 → 알림)
- Reference: `scripts/fetch_universe_charts.py:88-94` (부분 실패 → 알림)

**Step 1: Write 2 failing tests for main() notification paths**

```python
# tests/test_chart_generator.py — TestScriptEntryPoint 클래스에 추가

    @patch("scripts.fetch_universe_charts._send_notification")
    def test_main_sends_error_on_universe_load_failure(self, mock_notify, tmp_path, monkeypatch):
        """Universe 로드 실패 시 ERROR 알림이 발송된다"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.fetch_universe_charts import main

        monkeypatch.setattr("sys.argv", ["fetch_universe_charts"])
        monkeypatch.setattr("scripts.fetch_universe_charts.PROJECT_ROOT", tmp_path)

        # config 디렉토리는 있지만 universe.yaml이 잘못된 내용
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "universe.yaml").write_text("invalid: yaml: content: [}")

        with pytest.raises(SystemExit):
            main()

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][2] == NotificationLevel.ERROR
        assert "실패" in call_args[0][0]

    @patch("scripts.fetch_universe_charts._send_notification")
    @patch("src.local_chart_renderer.yf.download")
    def test_main_sends_warning_on_partial_failure(self, mock_download, mock_notify, tmp_path, monkeypatch):
        """일부 종목 실패 시 WARNING 알림이 발송된다"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.fetch_universe_charts import main

        # 빈 DataFrame 반환 → 모든 종목 실패
        mock_download.return_value = pd.DataFrame()

        monkeypatch.setattr("sys.argv", ["fetch_universe_charts", "--limit", "2"])
        monkeypatch.setattr("scripts.fetch_universe_charts.PROJECT_ROOT", tmp_path)

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        yaml_content = {
            "symbols": {
                "us_equity": [
                    {"symbol": "SPY", "name": "S&P 500 ETF", "group": "us_equity", "short_restricted": False},
                    {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "group": "us_equity", "short_restricted": False},
                ],
            }
        }
        (config_dir / "universe.yaml").write_text(yaml.dump(yaml_content))

        main()

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[0][2] == NotificationLevel.WARNING
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chart_generator.py::TestScriptEntryPoint::test_main_sends_error_on_universe_load_failure tests/test_chart_generator.py::TestScriptEntryPoint::test_main_sends_warning_on_partial_failure -v`
Expected: FAIL

**Step 3: Verify tests pass (implementation already exists)**

이 테스트들은 기존 코드의 알림 경로를 검증하므로 추가 구현 없이 통과해야 합니다. 만약 실패한다면 `_send_notification` 호출 경로를 디버깅합니다.

Run: `uv run pytest tests/test_chart_generator.py::TestScriptEntryPoint -v`
Expected: 4 PASS (기존 2 + 신규 2)

**Step 4: Commit**

```bash
git add tests/test_chart_generator.py
git commit -m "[#174] test: main() 알림 경로 테스트 2건 추가 (Universe 실패, 부분 실패)"
```

---

## Task 3: 전체 실패 ERROR 승격 + 성공 알림

**Files:**
- Modify: `scripts/fetch_universe_charts.py:82-95`
- Modify: `tests/test_chart_generator.py` (검증 테스트 추가)

**Step 1: Write failing tests for new behavior**

```python
# tests/test_chart_generator.py — TestScriptEntryPoint 클래스에 추가

    @patch("scripts.fetch_universe_charts._send_notification")
    @patch("src.local_chart_renderer.yf.download")
    def test_main_sends_error_on_all_failures(self, mock_download, mock_notify, tmp_path, monkeypatch):
        """전체 종목 실패 시 ERROR 알림 (WARNING이 아닌)"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.fetch_universe_charts import main

        mock_download.return_value = pd.DataFrame()  # 모든 종목 빈 데이터

        monkeypatch.setattr("sys.argv", ["fetch_universe_charts", "--limit", "2"])
        monkeypatch.setattr("scripts.fetch_universe_charts.PROJECT_ROOT", tmp_path)

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        yaml_content = {
            "symbols": {
                "us_equity": [
                    {"symbol": "SPY", "name": "S&P 500", "group": "us_equity", "short_restricted": False},
                    {"symbol": "QQQ", "name": "Nasdaq 100", "group": "us_equity", "short_restricted": False},
                ],
            }
        }
        (config_dir / "universe.yaml").write_text(yaml.dump(yaml_content))

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][2] == NotificationLevel.ERROR

    @patch("scripts.fetch_universe_charts._send_notification")
    @patch("src.local_chart_renderer.yf.download")
    def test_main_sends_info_on_full_success(self, mock_download, mock_notify, tmp_path, monkeypatch):
        """전체 성공 시 INFO 알림 발송"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.fetch_universe_charts import main

        mock_download.return_value = _make_ohlcv()

        monkeypatch.setattr("sys.argv", ["fetch_universe_charts", "--limit", "1"])
        monkeypatch.setattr("scripts.fetch_universe_charts.PROJECT_ROOT", tmp_path)

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        yaml_content = {
            "symbols": {
                "us_equity": [
                    {"symbol": "SPY", "name": "S&P 500", "group": "us_equity", "short_restricted": False},
                ],
            }
        }
        (config_dir / "universe.yaml").write_text(yaml.dump(yaml_content))

        main()

        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][2] == NotificationLevel.INFO
        assert "성공" in mock_notify.call_args[0][0] or "완료" in mock_notify.call_args[0][0]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chart_generator.py::TestScriptEntryPoint::test_main_sends_error_on_all_failures tests/test_chart_generator.py::TestScriptEntryPoint::test_main_sends_info_on_full_success -v`
Expected: FAIL (현재 코드는 전체 실패에도 WARNING, 성공 시 알림 없음)

**Step 3: Implement the fix in `fetch_universe_charts.py`**

`scripts/fetch_universe_charts.py:82-95` 결과 리포팅 섹션을 다음으로 교체:

```python
    # 4. 결과 리포팅
    successes = [s for s, ok in results.items() if ok]
    failures = [s for s, ok in results.items() if not ok]

    logger.info("=" * 40)
    logger.info(f"배치 완료: 성공 {len(successes)} / 실패 {len(failures)}")

    if len(failures) == len(results):
        # 전체 실패 → ERROR + 비정상 종료
        logger.error(f"전체 종목 실패: {', '.join(failures)}")
        _send_notification(
            "주간 차트 생성 전체 실패",
            f"전체 {len(failures)}개 종목 차트 생성 실패",
            NotificationLevel.ERROR,
        )
        logger.info("=" * 40)
        sys.exit(1)
    elif failures:
        # 부분 실패 → WARNING
        logger.warning(f"실패 종목: {', '.join(failures)}")
        _send_notification(
            "주간 차트 생성 부분 실패",
            f"성공 {len(successes)} / 실패 {len(failures)}\n실패 종목: {', '.join(failures)}",
            NotificationLevel.WARNING,
        )
    else:
        # 전체 성공 → INFO
        _send_notification(
            "주간 차트 생성 완료",
            f"전체 {len(successes)}개 종목 차트 생성 성공",
            NotificationLevel.INFO,
        )

    logger.info("=" * 40)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chart_generator.py::TestScriptEntryPoint -v`
Expected: 6 PASS

**Step 5: Commit**

```bash
git add scripts/fetch_universe_charts.py tests/test_chart_generator.py
git commit -m "[#174] feat: 전체 실패 ERROR 승격 + 성공 INFO 알림 추가"
```

---

## Task 4: 테스트 안티패턴 수정

**Files:**
- Modify: `tests/test_weekly_charts.py:48-58` (동어반복 테스트 개선)
- Modify: `tests/test_weekly_charts.py:185-186, 194-195` (`pytest.skip` 적용)

**Step 1: Fix `pytest.skip` usage**

`tests/test_weekly_charts.py`에서 `return` → `pytest.skip()` 교체:

```python
    def test_crontab_has_weekly_charts_entry(self):
        """프로젝트 crontab에 주간 차트 생성 항목이 있다"""
        crontab_path = PROJECT_ROOT / "crontab"
        if not crontab_path.exists():
            pytest.skip("crontab not found")
        content = crontab_path.read_text()
        assert "fetch_universe_charts.py" in content
        assert "0 6 * * 6" in content

    def test_crontab_charts_before_weekly_report(self):
        """차트 생성(06:00)이 주간 리포트(09:00) 전에 실행된다"""
        crontab_path = PROJECT_ROOT / "crontab"
        if not crontab_path.exists():
            pytest.skip("crontab not found")
        content = crontab_path.read_text()
        chart_pos = content.find("fetch_universe_charts.py")
        report_pos = content.find("weekly_report.py")
        assert chart_pos < report_pos
```

**Step 2: Replace tautological notification delegation test**

기존 `test_wrapper_delegates_notification_to_python`을 실제 행위를 검증하는 테스트로 교체:

```python
    def test_wrapper_does_not_contain_notification_logic(self):
        """래퍼 스크립트는 알림 로직을 포함하지 않는다 (Python에 위임)"""
        content = WRAPPER_SCRIPT.read_text()
        # 래퍼에 Python 알림 관련 키워드가 없어야 함
        assert "send_notification" not in content.lower()
        assert "notif" not in content.lower()
```

**Step 3: Add `import pytest` to test file (if not present)**

`tests/test_weekly_charts.py` 상단에 `import pytest` 추가 (필요시).

**Step 4: Run tests**

Run: `uv run pytest tests/test_weekly_charts.py -v`
Expected: 12 PASS

**Step 5: Commit**

```bash
git add tests/test_weekly_charts.py
git commit -m "[#174] fix: 테스트 안티패턴 수정 — pytest.skip 적용, 동어반복 제거"
```

---

## Task 5: 경로 순회 방어 + 예외 메시지 정리

**Files:**
- Modify: `src/local_chart_renderer.py:168-169` (경로 순회 방어)
- Modify: `scripts/fetch_universe_charts.py:70-74` (예외 메시지 정리)
- Modify: `tests/test_local_chart_renderer.py` (방어 테스트 추가)

**Step 1: Write failing test for path traversal defense**

```python
# tests/test_local_chart_renderer.py — TestBatchChartRenderer 클래스에 추가

    @patch("src.local_chart_renderer.yf.download")
    def test_path_traversal_in_asset_name_is_blocked(self, mock_download, tmp_path):
        """asset.name에 .. 시퀀스가 있으면 안전하게 제거된다"""
        import yaml

        yaml_content = {
            "symbols": {
                "us_equity": [
                    {
                        "symbol": "EVIL",
                        "name": "../../etc/cron.d/malicious",
                        "group": "us_equity",
                        "short_restricted": False,
                    },
                ],
            }
        }
        yaml_path = tmp_path / "universe.yaml"
        yaml_path.write_text(yaml.dump(yaml_content))
        um = UniverseManager(yaml_path=str(yaml_path))

        mock_download.return_value = self._make_mock_df()
        renderer = BatchChartRenderer(um)
        output_dir = tmp_path / "charts"
        output_dir.mkdir()
        results = renderer.render_all(output_dir=str(output_dir))

        assert results["EVIL"] is True
        # 생성된 파일이 output_dir 내부에만 존재
        for png in Path(str(output_dir)).rglob("*.png"):
            resolved = png.resolve()
            assert str(resolved).startswith(str(output_dir.resolve()))
        # .. 이 파일명에 포함되지 않음
        for png in output_dir.glob("*.png"):
            assert ".." not in png.name
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_local_chart_renderer.py::TestBatchChartRenderer::test_path_traversal_in_asset_name_is_blocked -v`
Expected: FAIL (현재 코드는 `..` 미제거)

**Step 3: Fix path sanitization in `local_chart_renderer.py`**

`src/local_chart_renderer.py:168-169` 교체:

```python
                safe_name = re.sub(r'[\\/*?:"<>|\x00]', "", asset.name).replace("..", "").replace(" ", "_")
                output_path = str(Path(output_dir) / f"{safe_name}_{symbol}.png")
```

**Step 4: Fix notification error message sanitization**

`scripts/fetch_universe_charts.py:70-74` 교체:

```python
        _send_notification(
            "주간 차트 생성 실패",
            "Universe 설정 파일 로드 중 오류가 발생했습니다. 서버 로그를 확인하세요.",
            NotificationLevel.ERROR,
        )
```

**Step 5: Run all tests**

Run: `uv run pytest tests/test_local_chart_renderer.py tests/test_chart_generator.py tests/test_weekly_charts.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/local_chart_renderer.py scripts/fetch_universe_charts.py tests/test_local_chart_renderer.py
git commit -m "[#174] fix: 경로 순회 방어 보강 + 알림 예외 메시지 내부 경로 제거"
```

---

## Task 6: render_chart 경계값 테스트

**Files:**
- Modify: `tests/test_local_chart_renderer.py` (경계값 테스트 추가)

**Step 1: Write boundary tests**

```python
# tests/test_local_chart_renderer.py — TestRenderChart 클래스에 추가

    def test_exactly_4_rows_returns_false(self, tmp_path):
        """정확히 4행 데이터는 False 반환 (최소 5행 필요)"""
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=4, freq="B")
        close = 100 + np.cumsum(np.random.randn(4))
        df = pd.DataFrame(
            {
                "Open": close - 1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.random.randint(1_000_000, 10_000_000, 4),
            },
            index=dates,
        )
        df = calculate_indicators(df)
        output = str(tmp_path / "boundary.png")
        assert render_chart(df, "BOUND", "Boundary", output) is False

    def test_exactly_5_rows_renders_successfully(self, tmp_path):
        """정확히 5행 데이터는 렌더링 성공"""
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=5, freq="B")
        close = 100 + np.cumsum(np.random.randn(5))
        df = pd.DataFrame(
            {
                "Open": close - 1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.random.randint(1_000_000, 10_000_000, 5),
            },
            index=dates,
        )
        df = calculate_indicators(df)
        output = str(tmp_path / "five.png")
        assert render_chart(df, "FIVE", "Five Rows", output) is True
        assert os.path.exists(output)
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_local_chart_renderer.py::TestRenderChart -v`
Expected: 5 PASS (기존 3 + 신규 2)

**Step 3: Commit**

```bash
git add tests/test_local_chart_renderer.py
git commit -m "[#174] test: render_chart 경계값 테스트 추가 (4행 실패, 5행 성공)"
```

---

## Task 7: 최종 검증 및 PR 생성

**Step 1: Full test suite run**

Run: `uv run pytest -x -q`
Expected: 1120+ tests PASS

**Step 2: Ruff check**

Run: `uv run ruff check scripts/fetch_universe_charts.py src/local_chart_renderer.py tests/test_chart_generator.py tests/test_local_chart_renderer.py tests/test_weekly_charts.py`
Expected: All checks passed

**Step 3: Push and create PR**

```bash
git push -u origin fix/issue-174-weekly-charts-hardening
gh pr create --title "[#174] 주간 차트 테스트 커버리지 + 운영 가시성 + 보안 강화" \
  --body "Fixes #174

## Summary
- _send_notification() 단위 테스트 3건
- main() 알림 경로 테스트 2건
- 전체 실패 ERROR 승격 + 성공 INFO 알림
- pytest.skip 적용 + 동어반복 테스트 수정
- 경로 순회 방어 (.. 제거) + 예외 메시지 내부 경로 제거
- render_chart 경계값 테스트 2건

## Test plan
- [ ] 전체 테스트 통과
- [ ] ruff lint clean
- [ ] CI (lint + test) pass"
```

**Step 4: Wait for CI**

Run: `gh pr checks <PR_NUMBER> --watch`
Expected: All checks pass

**Step 5: Merge**

```bash
gh pr merge <PR_NUMBER> --squash --delete-branch
```
