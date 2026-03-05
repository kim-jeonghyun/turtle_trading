"""버전 메타데이터 정합성 테스트."""

import re

import src


class TestVersionMetadata:
    """__version__ 검증 테스트."""

    def test_version_is_not_unknown(self):
        """버전이 'unknown'이 아닌 실제 값이어야 한다."""
        assert src.__version__ != "unknown"

    def test_version_format_semver(self):
        """시맨틱 버전 형식(X.Y.Z)을 따라야 한다."""
        pattern = r"^\d+\.\d+\.\d+$"
        assert re.match(pattern, src.__version__), f"Version '{src.__version__}' does not match semver format X.Y.Z"

    def test_version_matches_pyproject(self):
        """src.__version__이 pyproject.toml의 version과 일치해야 한다."""
        import tomllib
        from pathlib import Path

        pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            pyproject_version = tomllib.load(f)["project"]["version"]

        assert src.__version__ == pyproject_version, (
            f"src.__version__={src.__version__} != pyproject.toml={pyproject_version}"
        )
