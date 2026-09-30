"""定位 libmpv 动态库。

macOS 上 ctypes.util.find_library 不搜索 /opt/homebrew/lib（Apple Silicon
Homebrew 默认前缀），python-mpv 导入会失败。这里提供显式候选路径查找，
并在必要时修补 find_library，保证 `import mpv` 可用。
"""

from __future__ import annotations

import ctypes.util
from pathlib import Path

CANDIDATES = [
    "/opt/homebrew/lib/libmpv.dylib",  # Homebrew (Apple Silicon)
    "/usr/local/lib/libmpv.dylib",  # Homebrew (Intel) / 手动安装
    "/opt/homebrew/opt/mpv/lib/libmpv.dylib",
]


def find_libmpv() -> str | None:
    """返回 libmpv 绝对路径；找不到返回 None。"""
    try:
        found = ctypes.util.find_library("mpv")
    except Exception:
        found = None
    if found:
        return found
    return next((p for p in CANDIDATES if Path(p).exists()), None)


def patch_find_library() -> bool:
    """find_library 找不到 mpv 时，用候选路径补丁替换。返回是否已可用。"""
    if ctypes.util.find_library("mpv"):
        return True
    lib = next((p for p in CANDIDATES if Path(p).exists()), None)
    if lib is None:
        return False
    original = ctypes.util.find_library

    def patched(name: str, _original=original, _lib=lib):
        return _lib if name == "mpv" else _original(name)

    ctypes.util.find_library = patched
    return True
