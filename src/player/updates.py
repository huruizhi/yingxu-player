"""GitHub release lookup and semantic version comparison."""

from __future__ import annotations

import re

GITHUB_REPOSITORY = "huruizhi/yingxu-player"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"


def version_tuple(value: str) -> tuple[int, int, int] | None:
    """Parse a three-part release version, optionally prefixed with ``v``."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def is_newer_version(latest: str, current: str) -> bool:
    """Return whether latest is a valid version newer than current."""
    latest_version = version_tuple(latest)
    current_version = version_tuple(current)
    return latest_version is not None and current_version is not None and latest_version > current_version
