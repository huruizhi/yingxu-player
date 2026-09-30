"""右侧滑出的播放列表抽屉（半透明），窗口/全屏模式统一。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from player.ui.icons import icon
from player.ui.playlist_panel import PlaylistPanel
from player.ui.theme import OVERLAY_QSS

_WIDTH = 320
_MARGIN = 16
_BOTTOM_GAP = 12
_ROW_HEIGHT = 30
_AUTO_HIDE_MS = 4000


class PlaylistDrawer(QWidget):
    visibility_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("playlistDrawer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(OVERLAY_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(2, 0, 0, 0)
        header_row.setSpacing(8)
        header = QLabel("播放列表")
        header.setObjectName("playlistTitle")
        self.count_label = QLabel("0 项")
        self.count_label.setObjectName("playlistCount")
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("playlistClose")
        self.close_button.setIcon(icon("close"))
        self.close_button.setToolTip("收起播放列表")
        self.close_button.setAccessibleName("收起播放列表")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(self.slide_out)
        header_row.addWidget(header)
        header_row.addWidget(self.count_label)
        header_row.addStretch(1)
        header_row.addWidget(self.close_button)

        self.panel = PlaylistPanel()
        layout.addLayout(header_row)
        layout.addWidget(self.panel)
        self.setVisible(False)

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.setInterval(_AUTO_HIDE_MS)
        self._auto_hide.timeout.connect(self._on_auto_hide_timeout)
        for widget in (self, self.panel, self.panel.viewport(), self.close_button, header, self.count_label):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

    # ---- 数据代理 ----

    def populate(self, paths: list[Path], current: Path | None) -> None:
        self.panel.populate(paths, current)
        self.count_label.setText(f"{len(paths)} 项")
        self._update_height()

    def highlight_current(self, path: Path | None) -> None:
        self.panel.highlight_current(path)

    # ---- 显隐 ----

    def _target_rect(self, parent: QWidget) -> QRect:
        width = min(_WIDTH, max(180, parent.width() - 2 * _MARGIN))
        control_bar = getattr(parent, "control_bar", None)
        bottom = control_bar.y() - _BOTTOM_GAP if control_bar is not None else parent.height() - _MARGIN
        max_height = max(1, bottom - _MARGIN)
        desired_height = self._content_height()
        height = min(desired_height, max_height)
        return QRect(
            parent.width() - width - _MARGIN,
            _MARGIN,
            width,
            height,
        )

    def _content_height(self) -> int:
        header_height = max(28, self.close_button.height())
        rows = max(1, self.panel.count())
        margins = self.layout().contentsMargins()
        return margins.top() + header_height + self.layout().spacing() + rows * _ROW_HEIGHT + margins.bottom()

    def _update_height(self) -> None:
        parent = self.parentWidget()
        if parent is not None and self.isVisible():
            self.setGeometry(self._target_rect(parent))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Enter, QEvent.MouseMove, QEvent.MouseButtonPress) and self.isVisible():
            self._auto_hide.start()
        return super().eventFilter(obj, event)

    def _on_auto_hide_timeout(self) -> None:
        if self.isVisible() and self.underMouse():
            self._auto_hide.start()
        else:
            self.slide_out()

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
        self.setGeometry(parent.width(), _MARGIN, target.width(), target.height())  # 屏外起点
        self.setVisible(True)
        self.visibility_changed.emit(True)
        self._auto_hide.start()
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(target)
        self._anim.start()

    def slide_out(self) -> None:
        parent = self.parentWidget()
        if parent is None or not self.isVisible():
            return
        self._auto_hide.stop()
        self._anim.stop()
        self._anim.finished.connect(self._on_slide_out_done)
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(parent.width(), self.y(), self.width(), self.height()))
        self._anim.start()

    def _on_slide_out_done(self) -> None:
        was_visible = self.isVisible()
        self.setVisible(False)
        if was_visible:
            self.visibility_changed.emit(False)
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
