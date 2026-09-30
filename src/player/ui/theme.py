"""深色主题：Fusion 风格 + 暗色调色板。"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_BG = QColor(30, 30, 32)
_PANEL = QColor(40, 40, 44)
_TEXT = QColor(232, 232, 235)
_DISABLED = QColor(120, 120, 125)
_HIGHLIGHT = QColor(72, 130, 230)


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, _BG)
    palette.setColor(QPalette.WindowText, _TEXT)
    palette.setColor(QPalette.Base, QColor(24, 24, 26))
    palette.setColor(QPalette.AlternateBase, _PANEL)
    palette.setColor(QPalette.ToolTipBase, _PANEL)
    palette.setColor(QPalette.ToolTipText, _TEXT)
    palette.setColor(QPalette.Text, _TEXT)
    palette.setColor(QPalette.Button, _PANEL)
    palette.setColor(QPalette.ButtonText, _TEXT)
    palette.setColor(QPalette.BrightText, QColor(255, 90, 90))
    palette.setColor(QPalette.Highlight, _HIGHLIGHT)
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.Disabled, QPalette.Text, _DISABLED)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, _DISABLED)
    palette.setColor(QPalette.Disabled, QPalette.WindowText, _DISABLED)
    app.setPalette(palette)
