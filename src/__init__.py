"""터틀 트레이딩 시스템."""

from importlib.metadata import PackageNotFoundError, version


def _get_version() -> str:
    """패키지 버전을 동적으로 조회한다.

    1차: importlib.metadata (pip install 환경)
    2차: pyproject.toml 직접 파싱 (로컬 개발 환경)
    3차: "unknown" fallback
    """
    try:
        return version("turtle-trading")
    except PackageNotFoundError:
        pass
    try:
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        if pyproject.exists():
            with open(pyproject, "rb") as f:
                return str(tomllib.load(f)["project"]["version"])
    except (KeyError, FileNotFoundError, Exception):
        pass
    return "unknown"


__version__ = _get_version()
