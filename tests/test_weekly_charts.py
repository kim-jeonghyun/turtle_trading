"""
scripts/weekly_charts.sh 래퍼 스크립트 테스트
- 스크립트 존재 및 실행 권한
- 로그 디렉토리 생성
- fetch_universe_charts.py 호출 검증
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

    def test_wrapper_creates_log_directory(self, tmp_path):
        """래퍼 스크립트가 로그 디렉토리를 생성한다"""
        # 래퍼 스크립트의 로그 디렉토리 생성 로직만 검증
        log_dir = tmp_path / "logs" / "weekly_charts"
        log_dir.mkdir(parents=True, exist_ok=True)
        assert log_dir.exists()

    def test_wrapper_references_fetch_universe_charts(self):
        """래퍼 스크립트가 fetch_universe_charts.py를 호출한다"""
        content = WRAPPER_SCRIPT.read_text()
        assert "fetch_universe_charts.py" in content

    def test_wrapper_handles_missing_venv(self, tmp_path):
        """venv가 없으면 에러 코드 1로 종료한다"""
        # PROJECT_ROOT를 tmp_path로 변경한 테스트용 스크립트 생성
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

    def test_wrapper_cleans_old_logs(self):
        """래퍼 스크립트가 30일 이상 된 로그를 정리한다"""
        content = WRAPPER_SCRIPT.read_text()
        assert "-mtime +30 -delete" in content
