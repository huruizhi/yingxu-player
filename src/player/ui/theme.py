"""Cool charcoal surfaces, crisp controls, and a quiet playback canvas."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ---- 颜色常量（供自定义控件绘制使用）----
BG = QColor(20, 21, 24)
PANEL = QColor(31, 33, 38)
TEXT = QColor(237, 239, 244)
TEXT_DIM = QColor(157, 163, 175)
ACCENT = QColor(111, 163, 255)
OVERLAY_BG = "rgba(25, 27, 32, 0.97)"
OVERLAY_BG_SOLID = QColor(25, 27, 32, 247)
TRACK_BG = QColor(255, 255, 255, 34)  # 进度条轨道：低透明度让视频透出（UI v2 定稿值）
COVERED_TINT = QColor(111, 163, 255, 76)
LOOP_TINT = QColor(102, 204, 153, 88)
CHAPTER_TICK = QColor(255, 255, 255, 140)
PLAYED_COLOR = ACCENT

# ---- 应用级样式（菜单/提示）----
APP_QSS = """
QMenu {
    background-color: #202228; color: #eceef3;
    border: 1px solid #353841; border-radius: 10px; padding: 6px;
}
QMenu::item { padding: 7px 28px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background-color: #34435d; color: #ffffff; }
QMenu::separator { height: 1px; background: #383b43; margin: 5px 8px; }
QToolTip {
    background-color: #262930; color: #f1f2f5;
    border: 1px solid #41444d; border-radius: 6px; padding: 5px 8px;
}
"""

# ---- 悬浮控件样式（按 objectName 作用域）----
OVERLAY_QSS = """
QWidget#controlBar {
    background-color: rgba(25, 27, 32, 0.78);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 18px;
}
QWidget#topBar {
    background-color: rgba(25, 27, 32, 0.94);
    border: 1px solid #353841; border-radius: 12px;
}
QWidget#playlistDrawer {
    background-color: rgba(25, 27, 32, 0.90);
    border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 16px;
}
QLabel#playlistTitle { color: #f1f2f5; font-size: 15px; font-weight: 600; }
QLabel#playlistCount { color: #aeb5c2; font-size: 11px; }
QToolButton#playlistClose {
    background: transparent; border: 1px solid transparent; border-radius: 8px;
}
QToolButton#playlistClose:hover { background: rgba(255, 255, 255, 0.10); }
QToolButton#playlistClose:pressed { background: rgba(255, 255, 255, 0.16); }
QToolButton#playlistClose:focus { border-color: #829ac0; }
QListWidget#playlistPanel {
    background: transparent; border: none; outline: none;
}
QWidget#osdLabel {
    background-color: #24272e; border: 1px solid #3b3e47; border-radius: 12px;
}
QWidget#emptyState { background-color: #141519; }
QLabel#emptyMark { background-color: #20232a; border: 1px solid #363a44; border-radius: 48px; }
QLabel#welcomeTitle { color: #f1f2f5; font-size: 27px; font-weight: 600; }
QLabel#welcomeDescription { color: #a8adba; font-size: 14px; }
QLabel#welcomeHint { color: #828896; font-size: 12px; }
QPushButton#openPrimary, QPushButton#openSecondary {
    min-width: 112px; min-height: 40px; padding: 0 14px; border-radius: 9px;
    font-size: 13px; font-weight: 600;
}
QPushButton#openPrimary { background: #dce8ff; border: 1px solid #dce8ff; color: #1b263a; }
QPushButton#openPrimary:hover { background: #ffffff; }
QPushButton#openSecondary { background: #252830; border: 1px solid #41444d; color: #e3e6ed; }
QPushButton#openSecondary:hover { background: #30333c; }
QPushButton#recentDirectory {
    min-width: 260px; min-height: 30px; padding: 0 12px;
    background: #252830; border: 1px solid #41444d; border-radius: 8px;
    color: #e3e6ed; text-align: left;
}
QPushButton#recentDirectory:hover { background: #30333c; }
QPushButton:focus { border-color: #829ac0; }
QLabel#videoTitle { color: #f0f1f4; font-size: 14px; font-weight: 600; }
QLabel#topStatus {
    color: #c1d6ff; font-size: 11px;
    background: #263348; border: 1px solid #354968; border-radius: 8px; padding: 3px 9px;
}
QLabel#timeLabel { color: #c7cad2; font-size: 11px; font-variant-numeric: tabular-nums; }
QToolButton {
    background: transparent; border: 1px solid transparent; border-radius: 10px;
    color: #e8eaf0; padding: 0; font-size: 13px;
}
QToolButton:hover { background: #2b2e36; border-color: #3a3e48; }
QToolButton:pressed { background: #353944; }
QToolButton:focus { border-color: #829ac0; }
QToolButton:checked { background: #28364e; border-color: #3b5278; }
QToolButton:disabled { color: #626874; background: transparent; border-color: transparent; }
QToolButton::menu-indicator { image: none; width: 0px; height: 0px; }
QToolButton#playBig {
    background: #dce8ff; border: 1px solid #dce8ff; border-radius: 22px;
}
QToolButton#playBig:hover { background: #ffffff; border-color: #ffffff; }
QToolButton#playBig:pressed { background: #c5d9ff; }
QToolButton#speedButton { color: #d7dae2; font-weight: 600; }
QSlider { background: transparent; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: #41444d; }
QSlider::sub-page:horizontal { height: 4px; border-radius: 2px; background: #8ab3ff; }
QSlider::handle:horizontal {
    width: 10px; height: 10px; margin: -3px 0; border-radius: 5px;
    background: #eff3fb;
}
QListWidget {
    background: transparent; border: none; outline: none;
}
QListWidget::item { border-radius: 7px; padding: 7px 10px; color: #e3e5eb; }
QListWidget::item:selected { background: rgba(84, 132, 196, 0.52); color: #ffffff; }
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
