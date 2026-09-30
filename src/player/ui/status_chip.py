"""左上角状态徽标：AI 转写进度/就绪/出错等轻量状态提示。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from player.ui.theme import OVERLAY_QSS


class StatusChip(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("topStatus")
        self.setStyleSheet(OVERLAY_QSS)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setVisible(False)

    def set_status(self, text: str | None) -> None:
        """显示状态徽标；None 隐藏。"""
        if text:
            self.setText(text)
            self.adjustSize()
            self.setVisible(True)
        else:
            self.clear()
            self.setVisible(False)
