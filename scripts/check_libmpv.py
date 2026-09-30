"""检查运行环境是否提供 libmpv 动态库（播放内核依赖）。"""

import ctypes.util
import sys
from pathlib import Path

CANDIDATES = [
    "/opt/homebrew/lib/libmpv.dylib",
    "/usr/local/lib/libmpv.dylib",
    "/opt/homebrew/opt/mpv/lib/libmpv.dylib",
]


def find_libmpv() -> str | None:
    found = ctypes.util.find_library("mpv")
    if found:
        return found
    for path in CANDIDATES:
        if Path(path).exists():
            return path
    return None


def main() -> int:
    lib = find_libmpv()
    if lib:
        print(f"libmpv OK: {lib}")
        return 0
    print("未找到 libmpv：请执行 `brew install mpv` 后重试 make setup")
    return 1


if __name__ == "__main__":
    sys.exit(main())
