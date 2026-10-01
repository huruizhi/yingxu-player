"""Keep the displayed app version aligned with the release metadata."""

import tomllib
from pathlib import Path

from player import __version__


def test_app_version_matches_package_version():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == metadata["project"]["version"]
