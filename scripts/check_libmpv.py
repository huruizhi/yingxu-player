"""检查运行环境是否提供 libmpv 动态库（播放内核依赖）。"""

import sys

from player.core.libmpv import find_libmpv


def main() -> int:
    lib = find_libmpv()
    if lib:
        print(f"libmpv OK: {lib}")
        return 0
    print("未找到 libmpv：请执行 `brew install mpv` 后重试 make setup")
    return 1


if __name__ == "__main__":
    sys.exit(main())
