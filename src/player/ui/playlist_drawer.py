"""右侧滑出的播放列表抽屉（半透明），窗口/全屏模式统一。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from player.ui.playlist_panel import PlaylistPanel
from player.ui.theme import OVERLAY_QSS

_WIDTH = 280
_MARGIN = 12


class PlaylistDrawer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("playlistDrawer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(OVERLAY_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(6)
        header = QLabel("播放列表")
        header.setObjectName("topTitle")
        self.panel = PlaylistPanel()
        layout.addWidget(header)
        layout.addWidget(self.panel, 1)
        self.setVisible(False)

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    # ---- 数据代理 ----

    def populate(self, paths: list[Path], current: Path | None) -> None:
        self.panel.populate(paths, current)

    def highlight_current(self, path: Path | None) -> None:
        self.panel.highlight_current(path)

    # ---- 显隐 ----

    def _target_rect(self, parent: QWidget) -> QRect:
        return QRect(
            parent.width() - _WIDTH - _MARGIN,
            _MARGIN,
            _WIDTH,
            parent.height() - 2 * _MARGIN,
        )

    def toggle(self) -> None:
        if self.isVisible():
            self.slide_out()
        else:
            self.slide_in()

    def slide_in(self) -> None:
        parent = self.parentWidget()
        if parent is None or self.isVisible():
            return
        target = self._target_rect(parent)
        self.setGeometry(parent.width(), _MARGIN, _WIDTH, target.height())  # 屏外起点
        self.setVisible(True)
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(target)
        self._anim.start()

    def slide_out(self) -> None:
        parent = self.parentWidget()
        if parent is None or not self.isVisible():
            return
        self._anim.stop()
        self._anim.finished.connect(self._on_slide_out_done)
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(parent.width(), self.y(), self.width(), self.height()))
        self._anim.start()

    def _on_slide_out_done(self) -> None:
        self.setVisible(False)
        try:
            self._anim.finished.disconnect(self._on_slide_out_done)
        except TypeError:
            pass

    def relayout(self) -> None:
        """容器尺寸变化时保持右侧停靠（不做动画）。"""
        parent = self.parentWidget()
        if parent is not None and self.isVisible():
            self._anim.stop()
            self.setGeometry(self._target_rect(parent))
