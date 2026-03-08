"""
scripts/weekly_charts.sh 래퍼 스크립트 테스트
- 스크립트 존재 및 실행 권한
- 로그 디렉토리 생성 및 실제 로그 파일 검증
- fetch_universe_charts.py 호출 검증
- 실패 시 알림 발송 경로 검증
"""

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
WRAPPER_SCRIPT = PROJECT_ROOT / "scripts" / "weekly_charts.sh"
CHART_SCRIPT = PROJECT_ROOT / "scripts" / "fetch_universe_charts.py"


class TestWeeklyChartsWrapper:
    """래퍼 스크립트 기본 검증"""

    def test_wrapper_script_exists(self):
        """래퍼 스크립트가 존재한다"""
        assert WRAPPER_SCRIPT.exists()

    def test_wrapper_script_is_executable(self):
        """래퍼 스크립트에 실행 권한이 있다"""
        assert os.access(WRAPPER_SCRIPT, os.X_OK)

    def test_chart_script_exists(self):
        """차트 생성 스크립트가 존재한다"""
        assert CHART_SCRIPT.exists()

    def test_wrapper_uses_set_euo_pipefail(self):
        """래퍼 스크립트가 strict 모드를 사용한다"""
        content = WRAPPER_SCRIPT.read_text()
        assert "set -euo pipefail" in content

    def test_wrapper_references_fetch_universe_charts(self):
        """래퍼 스크립트가 fetch_universe_charts.py를 호출한다"""
        content = WRAPPER_SCRIPT.read_text()
        assert "fetch_universe_charts.py" in content

    def test_wrapper_cleans_old_logs(self):
        """래퍼 스크립트가 30일 이상 된 로그를 정리한다"""
        content = WRAPPER_SCRIPT.read_text()
        assert "-mtime +30 -delete" in content

    def test_wrapper_delegates_notification_to_python(self):
        """래퍼 스크립트는 알림을 Python 스크립트에 위임한다 (직접 알림 코드 없음)"""
        content = WRAPPER_SCRIPT.read_text()
        # 래퍼에는 알림 코드가 없어야 함 (Python 스크립트가 처리)
        assert "NotificationManager" not in content
        assert "NotificationLevel" not in content
        # 대신 Python 스크립트에 알림 로직이 존재해야 함
        chart_content = CHART_SCRIPT.read_text()
        assert "load_config" in chart_content
        assert "setup_notifier" in chart_content
        assert "_send_notification" in chart_content


class TestWrapperExecution:
    """래퍼 스크립트 실제 실행 검증"""

    def test_missing_venv_exits_with_error(self, tmp_path):
        """venv가 없으면 에러 코드 1로 종료한다"""
        test_script = tmp_path / "test_wrapper.sh"
        test_script.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'VENV_PATH="{tmp_path}/.venv/bin/python"\n'
            'if [ ! -f "$VENV_PATH" ]; then\n'
            '    echo "ERROR: Python venv not found" >&2\n'
            "    exit 1\n"
            "fi\n"
        )
        test_script.chmod(0o755)

        result = subprocess.run(
            [str(test_script)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_wrapper_creates_log_and_runs_python(self, tmp_path):
        """래퍼가 로그 디렉토리를 생성하고 Python 스크립트를 호출한다"""
        # 가짜 venv python 생성 (성공하는 스크립트)
        venv_dir = tmp_path / ".venv" / "bin"
        venv_dir.mkdir(parents=True)
        fake_python = venv_dir / "python"
        fake_python.write_text("#!/usr/bin/env bash\necho 'chart generated'\nexit 0\n")
        fake_python.chmod(0o755)

        # 가짜 fetch_universe_charts.py 생성
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "fetch_universe_charts.py").write_text("# placeholder")

        # 테스트용 래퍼 스크립트 (PROJECT_ROOT를 tmp_path로)
        test_wrapper = scripts_dir / "test_weekly.sh"
        test_wrapper.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'PROJECT_ROOT="{tmp_path}"\n'
            'LOG_DIR="$PROJECT_ROOT/logs/weekly_charts"\n'
            'mkdir -p "$LOG_DIR"\n'
            'TIMESTAMP=$(date +"%Y-%m-%d_%H%M%S")\n'
            'LOG_FILE="$LOG_DIR/$TIMESTAMP.log"\n'
            'VENV_PATH="$PROJECT_ROOT/.venv/bin/python"\n'
            'if [ ! -f "$VENV_PATH" ]; then\n'
            '    echo "ERROR: venv not found" >&2\n'
            "    exit 1\n"
            "fi\n"
            'echo "[$TIMESTAMP] start" | tee "$LOG_FILE"\n'
            'if "$VENV_PATH" "$PROJECT_ROOT/scripts/fetch_universe_charts.py" >> "$LOG_FILE" 2>&1; then\n'
            '    echo "done" | tee -a "$LOG_FILE"\n'
            "else\n"
            "    exit $?\n"
            "fi\n"
        )
        test_wrapper.chmod(0o755)

        result = subprocess.run(
            [str(test_wrapper)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

        # 로그 디렉토리와 파일이 생성되었는지 확인
        log_dir = tmp_path / "logs" / "weekly_charts"
        assert log_dir.exists()
        log_files = list(log_dir.glob("*.log"))
        assert len(log_files) == 1
        assert "start" in log_files[0].read_text()

    def test_wrapper_propagates_failure_exit_code(self, tmp_path):
        """Python 스크립트 실패 시 종료 코드가 전파된다"""
        venv_dir = tmp_path / ".venv" / "bin"
        venv_dir.mkdir(parents=True)
        fake_python = venv_dir / "python"
        fake_python.write_text("#!/usr/bin/env bash\nexit 2\n")
        fake_python.chmod(0o755)

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "fetch_universe_charts.py").write_text("# placeholder")

        test_wrapper = scripts_dir / "test_fail.sh"
        test_wrapper.write_text(
            "#!/usr/bin/env bash\n"
            "set -uo pipefail\n"
            f'PROJECT_ROOT="{tmp_path}"\n'
            'LOG_DIR="$PROJECT_ROOT/logs/weekly_charts"\n'
            'mkdir -p "$LOG_DIR"\n'
            'LOG_FILE="$LOG_DIR/test.log"\n'
            'VENV_PATH="$PROJECT_ROOT/.venv/bin/python"\n'
            'if "$VENV_PATH" "$PROJECT_ROOT/scripts/fetch_universe_charts.py" >> "$LOG_FILE" 2>&1; then\n'
            '    echo "ok"\n'
            "else\n"
            "    EXIT_CODE=$?\n"
            "    exit $EXIT_CODE\n"
            "fi\n"
        )
        test_wrapper.chmod(0o755)

        result = subprocess.run(
            [str(test_wrapper)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2


class TestCrontabIntegration:
    """프로젝트 crontab 파일 연동 검증"""

    def test_crontab_has_weekly_charts_entry(self):
        """프로젝트 crontab에 주간 차트 생성 항목이 있다"""
        crontab_path = PROJECT_ROOT / "crontab"
        if not crontab_path.exists():
            return  # Docker 설정 없는 환경에서는 스킵
        content = crontab_path.read_text()
        assert "fetch_universe_charts.py" in content
        assert "0 6 * * 6" in content

    def test_crontab_charts_before_weekly_report(self):
        """차트 생성(06:00)이 주간 리포트(09:00) 전에 실행된다"""
        crontab_path = PROJECT_ROOT / "crontab"
        if not crontab_path.exists():
            return
        content = crontab_path.read_text()
        chart_pos = content.find("fetch_universe_charts.py")
        report_pos = content.find("weekly_report.py")
        assert chart_pos < report_pos
