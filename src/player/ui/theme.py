"""深色主题 v2：Fusion 风格 + 暗色调色板 + 悬浮层 QSS。

设计语言：视频全幅铺满，控制元素为半透明深色圆角悬浮层；
统一 8/12/14px 圆角、无边框、悬停微亮。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ---- 颜色常量（供自定义控件绘制使用）----
BG = QColor(30, 30, 32)
PANEL = QColor(40, 40, 44)
TEXT = QColor(232, 232, 235)
TEXT_DIM = QColor(150, 150, 158)
ACCENT = QColor(77, 141, 246)
OVERLAY_BG = "rgba(22, 22, 26, 0.80)"  # 悬浮条背景
OVERLAY_BG_SOLID = QColor(22, 22, 26, 204)
TRACK_BG = QColor(255, 255, 255, 34)  # 进度条轨道
COVERED_TINT = QColor(77, 141, 246, 70)  # AI 已转写区间
PLAYED_COLOR = ACCENT

# ---- 应用级样式（菜单/提示）----
APP_QSS = """
QMenu {
    background-color: #232327;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    padding: 6px;
}
QMenu::item { padding: 6px 26px 6px 14px; border-radius: 6px; color: #e8e8eb; }
QMenu::item:selected { background-color: #4d8df6; color: white; }
QMenu::separator { height: 1px; background: rgba(255,255,255,0.08); margin: 5px 8px; }
QToolTip {
    background-color: #232327; color: #e8e8eb;
    border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 5px 8px;
}
"""

# ---- 悬浮控件样式（按 objectName 作用域）----
OVERLAY_QSS = """
QWidget#controlBar {
    background-color: rgba(22, 22, 26, 0.80);
    border-radius: 14px;
}
QWidget#topBar {
    background-color: rgba(22, 22, 26, 0.80);
    border-radius: 12px;
}
QWidget#playlistDrawer {
    background-color: rgba(20, 20, 24, 0.92);
    border-radius: 12px;
}
QWidget#osdLabel {
    background-color: rgba(22, 22, 26, 0.85);
    border-radius: 12px;
}
QLabel#topTitle { color: #e8e8eb; font-size: 13px; font-weight: 600; }
QLabel#topStatus {
    color: #9db9e8; font-size: 11px;
    background: rgba(77, 141, 246, 0.18); border-radius: 8px; padding: 2px 8px;
}
QLabel#timeLabel { color: #e8e8eb; font-size: 12px; font-variant-numeric: tabular-nums; }
QToolButton {
    background: transparent; border: none; border-radius: 8px;
    color: #e8e8eb; padding: 5px 7px; font-size: 14px;
}
QToolButton:hover { background: rgba(255, 255, 255, 0.12); }
QToolButton:pressed { background: rgba(255, 255, 255, 0.18); }
QToolButton:checked { color: #4d8df6; }
QToolButton:disabled { color: rgba(232, 232, 235, 0.35); background: transparent; }
QToolButton::menu-indicator { image: none; width: 0px; height: 0px; }
QToolButton#playBig {
    background: rgba(255, 255, 255, 0.16);
    border-radius: 19px; font-size: 17px; padding: 0px;
    min-width: 38px; min-height: 38px;
}
QToolButton#playBig:hover { background: rgba(255, 255, 255, 0.28); }
QToolButton#playBig:pressed { background: rgba(255, 255, 255, 0.36); }
QSlider { background: transparent; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: rgba(255,255,255,0.22); }
QSlider::sub-page:horizontal { height: 4px; border-radius: 2px; background: #4d8df6; }
QSlider::handle:horizontal {
    width: 11px; height: 11px; margin: -4px 0; border-radius: 5.5px;
    background: #ffffff;
}
QListWidget {
    background: transparent; border: none; outline: none;
}
QListWidget::item { border-radius: 8px; padding: 7px 9px; color: #e8e8eb; }
QListWidget::item:selected { background: rgba(77, 141, 246, 0.38); }
QListWidget::item:hover:!selected { background: rgba(255, 255, 255, 0.08); }
"""


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, BG)
    palette.setColor(QPalette.WindowText, TEXT)
    palette.setColor(QPalette.Base, QColor(24, 24, 26))
    palette.setColor(QPalette.AlternateBase, PANEL)
    palette.setColor(QPalette.ToolTipBase, PANEL)
    palette.setColor(QPalette.ToolTipText, TEXT)
    palette.setColor(QPalette.Text, TEXT)
    palette.setColor(QPalette.Button, PANEL)
    palette.setColor(QPalette.ButtonText, TEXT)
    palette.setColor(QPalette.BrightText, QColor(255, 90, 90))
    palette.setColor(QPalette.Highlight, ACCENT)
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 125))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 125))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(120, 120, 125))
    app.setPalette(palette)
    app.setStyleSheet(APP_QSS)
