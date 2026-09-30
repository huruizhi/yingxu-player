"""自动隐藏状态机：控制悬浮层的显隐决策（纯逻辑，时钟可注入便于测试）。

规则：
- 任何鼠标活动 → 显示并重置计时
- 播放中且空闲超过 HIDE_AFTER 秒 → 隐藏（无论窗口/全屏）
- 暂停时保持显示；用户 Seek/切换文件/悬停控制区视为活动
"""

from __future__ import annotations

from collections.abc import Callable

HIDE_AFTER_SECONDS = 2.5


class AutoHideController:
    def __init__(self, clock: Callable[[], float] = None):  # type: ignore[assignment]
        import time

        self._clock = clock or time.monotonic
        self.shown = True
        self._last_activity = self._clock()

    def activity(self) -> None:
        """鼠标移动/悬停控制区等用户活动。返回是否发生显隐变化由 tick 统一处理。"""
        self._last_activity = self._clock()
        self.shown = True

    def tick(self, paused: bool, fullscreen: bool) -> bool:
        """周期调用；返回 shown 状态是否发生变化。"""
        if not self.shown:
            return False
        if not paused and self._clock() - self._last_activity > HIDE_AFTER_SECONDS:
            self.shown = False
            return True
        return False

    def force_show(self) -> bool:
        """立即显示（seek/换集/暂停等），返回是否变化。"""
        was = self.shown
        self.activity()
        return was != self.shown
