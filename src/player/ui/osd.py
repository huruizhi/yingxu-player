"""中央 OSD 提示：音量/倍速变化时短暂显示后淡出。"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

_TEXT = """
QLabel#osdLabel {
    color: #ffffff; font-size: 16px; font-weight: 500;
    padding: 12px 22px;
}
"""


class OsdLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("osdLabel")
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet(_TEXT)
        self.setVisible(False)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(420)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._hide_timer = None

    def show_message(self, text: str) -> None:
        self.setText(text)
        parent = self.parentWidget()
        if parent is not None:
            self.setMaximumWidth(int(parent.width() * 0.72))
        self.adjustSize()
        self._center()
        self.setVisible(True)
        self._fade.stop()
        self._effect.setOpacity(0.94)
        if self._hide_timer is None:
            from PySide6.QtCore import QTimer

            self._hide_timer = QTimer(self)
            self._hide_timer.setSingleShot(True)
            self._hide_timer.timeout.connect(self._fade_out)
        self._hide_timer.start(900)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()
        self._fade.finished.connect(self._maybe_hide)

    def _maybe_hide(self) -> None:
        if self._effect.opacity() < 0.05:
            self.setVisible(False)
        try:
            self._fade.finished.disconnect(self._maybe_hide)
        except TypeError:
            pass

    def _center(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        y = int(parent.height() * 0.42)
        self.move(max(0, x), max(0, y))

    def reposition(self) -> None:
        if self.isVisible():
            self._center()
