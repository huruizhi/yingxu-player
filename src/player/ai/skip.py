"""片尾自动跳过状态机。

依据 Store 中的片尾标记（单文件 > 同目录两级记忆），在播放进入片尾区间时
触发一次跳转回调。全局开关由 UI 控制（设置中可开/关）。
"""

from __future__ import annotations

from pathlib import Path

from player.core.store import Store


class CreditsSkipper:
    # 标记点之后该时长内仍视为片尾区间（容忍 seek 抖动与标记误差）
    GRACE = 90.0

    def __init__(self, store: Store):
        self.store = store
        self.enabled = False
        self.on_skip = None  # UI 注入：跳到下一集或结尾
        self._credits_start: float | None = None
        self._triggered = False
        self._token: str | None = None

    # ---- 生命周期 ----

    def on_file_opened(self, path: Path) -> None:
        self._token = str(Path(path).resolve())
        self._credits_start = self.store.get_credits_start(path)
        self._triggered = False

    def on_playback_stopped(self) -> None:
        self._credits_start = None
        self._triggered = False
        self._token = None

    # ---- 触发逻辑 ----

    def on_position(self, t: float) -> bool:
        """播放位置更新时调用；本次调用触发了自动跳过则返回 True。"""
        if not self.enabled or self._credits_start is None or self._triggered or self._token is None:
            return False
        if self._credits_start <= t <= self._credits_start + self.GRACE:
            self._triggered = True
            self._fire()
            return True
        return False

    def manual_skip(self) -> bool:
        """手动跳过（按钮触发），忽略开关与标记。"""
        if self.on_skip is None:
            return False
        self._triggered = True
        self._fire()
        return True

    def has_mark(self) -> bool:
        return self._credits_start is not None

    def _fire(self) -> None:
        try:
            if self.on_skip is not None:
                self.on_skip()
        except Exception:
            pass
