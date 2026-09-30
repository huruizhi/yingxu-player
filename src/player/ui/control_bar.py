"""底部悬浮胶囊控制条：左（AI 字幕）/ 中（大圆播放键组）/ 右（工具）。

三区网格布局，左右两列等比拉伸使中间播放键组始终视觉居中。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSlider, QToolButton, QWidget

from player.ui.theme import OVERLAY_QSS


def _button(text: str, tip: str, checkable: bool = False) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    return b


class ControlBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlBar")
        self.setAttribute(Qt.WA_StyledBackground, True)  # 普通 QWidget 画 QSS 背景必需
        self.setStyleSheet(OVERLAY_QSS)

        # ---- 左区：AI 字幕 ----
        left = QWidget(self)
        left_l = QHBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(2)
        self.subtitle_btn = _button("字", "AI 字幕开关", checkable=True)
        left_l.addWidget(self.subtitle_btn)

        # ---- 中区：主导航（大圆播放键） ----
        center = QWidget(self)
        center_l = QHBoxLayout(center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.setSpacing(10)
        self.prev_btn = _button("⏮", "上一个 (Ctrl+[)")
        self.play_btn = _button("⏸", "播放/暂停 (空格)")
        self.play_btn.setObjectName("playBig")
        self.next_btn = _button("⏭", "下一个 (Ctrl+])")
        center_l.addWidget(self.prev_btn, 0, Qt.AlignVCenter)
        center_l.addWidget(self.play_btn, 0, Qt.AlignVCenter)
        center_l.addWidget(self.next_btn, 0, Qt.AlignVCenter)

        # ---- 右区：工具 ----
        right = QWidget(self)
        right_l = QHBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(2)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 130)
        self.volume_slider.setFixedWidth(76)
        self.volume_slider.setFocusPolicy(Qt.NoFocus)
        self.volume_slider.setToolTip("音量 (↑/↓)")
        self.speed_btn = _button("1x", "倍速")
        self.skip_btn = _button("跳片尾", "跳过片尾 (Ctrl+S)")
        self.fullscreen_btn = _button("⛶", "全屏 (F)")
        self.playlist_btn = _button("☰", "播放列表 (Ctrl+L)")
        for w in (self.volume_slider, self.speed_btn, self.skip_btn, self.fullscreen_btn, self.playlist_btn):
            right_l.addWidget(w)

        # ---- 三区网格：左右等比拉伸 → 中间始终居中 ----
        grid = QGridLayout(self)
        grid.setContentsMargins(16, 5, 14, 5)
        grid.setHorizontalSpacing(8)
        grid.addWidget(left, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(center, 0, 1, Qt.AlignCenter)
        grid.addWidget(right, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)

        for w in (
            self.prev_btn,
            self.play_btn,
            self.next_btn,
            self.speed_btn,
            self.subtitle_btn,
            self.skip_btn,
            self.fullscreen_btn,
            self.playlist_btn,
            self.volume_slider,
        ):
            w.setFocusPolicy(Qt.NoFocus)
