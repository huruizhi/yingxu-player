"""QOpenGLWidget 内嵌 libmpv 渲染上下文，把视频画面绘入 Qt 窗口。

mpv 的更新回调来自其内部线程，经 Qt 信号排队回 GUI 线程后再调度重绘；
OpenGL 调用只发生在 initializeGL/paintGL（GUI 线程且上下文现行）。
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from player.core.libmpv import patch_find_library


class MpvWidget(QOpenGLWidget):
    _frame_pending = Signal()

    def __init__(self, playback, parent=None):
        super().__init__(parent)
        self._playback = playback
        self._ctx = None
        self._getproc_fn = None  # 持有 CFUNCTYPE 引用，防止被 GC 后 mpv 调用崩溃
        self._frame_pending.connect(self._schedule_repaint)

    def initializeGL(self):
        patch_find_library()
        from mpv import MpvGlGetProcAddressFn, MpvRenderContext

        glctx = self.context()

        def get_proc(_ctx, name):
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            addr = glctx.getProcAddress(name)
            try:
                return int(addr) if addr is not None else 0
            except TypeError:
                return 0

        self._getproc_fn = MpvGlGetProcAddressFn(get_proc)
        self._ctx = MpvRenderContext(
            self._playback.mpv_instance,
            "opengl",
            opengl_init_params={"get_proc_address": self._getproc_fn},
        )
        self._ctx.update_cb = self._on_mpv_update

    # ---- mpv 回调（mpv 内部线程）----

    def _on_mpv_update(self) -> None:
        self._frame_pending.emit()

    @Slot()
    def _schedule_repaint(self) -> None:
        self.update()

    # ---- 绘制 ----

    def paintGL(self) -> None:
        if self._ctx is None:
            return
        fbo = int(self.defaultFramebufferObject())
        dpr = self.devicePixelRatioF()
        w = max(1, int(self.width() * dpr))
        h = max(1, int(self.height() * dpr))
        self._ctx.render(
            flip_y=True,
            opengl_fbo={"fbo": fbo, "w": w, "h": h, "internal_format": 0},
        )
        self._ctx.report_swap()

    # ---- 生命周期 ----

    def shutdown(self) -> None:
        """释放渲染上下文；必须在 playback.terminate() 之前调用。"""
        if self._ctx is not None:
            try:
                self._ctx.update_cb = None
                self._ctx.free()
            except Exception:
                pass
            self._ctx = None
