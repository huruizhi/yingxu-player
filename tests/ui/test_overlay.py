"""自动隐藏状态机与全屏交互测试。"""

from player.ui.overlay_visibility import AutoHideController


class TestAutoHideController:
    def test_hides_after_idle_when_playing(self):
        t = [0.0]
        c = AutoHideController(clock=lambda: t[0])
        assert c.shown is True
        t[0] += 3.0  # 超过 HIDE_AFTER_SECONDS
        assert c.tick(paused=False, fullscreen=False) is True
        assert c.shown is False

    def test_paused_keeps_controls_visible(self):
        t = [0.0]
        c = AutoHideController(clock=lambda: t[0])
        t[0] += 10.0
        assert c.tick(paused=True, fullscreen=True) is False
        assert c.shown is True

    def test_activity_resets_idle_clock(self):
        t = [0.0]
        c = AutoHideController(clock=lambda: t[0])
        t[0] += 1.5
        c.activity()
        t[0] += 1.5  # 距上次活动仅 1.5s
        assert c.tick(paused=False, fullscreen=False) is False
        assert c.shown is True

    def test_stays_hidden_until_activity(self):
        t = [0.0]
        c = AutoHideController(clock=lambda: t[0])
        t[0] += 3.0
        c.tick(paused=False, fullscreen=False)
        t[0] += 3.0
        assert c.tick(paused=False, fullscreen=False) is False
        c.activity()
        assert c.shown is True

    def test_force_show(self):
        t = [0.0]
        c = AutoHideController(clock=lambda: t[0])
        assert c.force_show() is False  # 本来就显示
        t[0] += 3.0
        c.tick(paused=False, fullscreen=False)
        assert c.shown is False
        assert c.force_show() is True
        assert c.shown is True
