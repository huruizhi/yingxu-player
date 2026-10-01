"""Unified transport panel, with the timeline above the controls."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QWidget,
)

from player.core.airplay import AirPlayButton
from player.ui.icons import icon
from player.ui.theme import OVERLAY_QSS


def _button(name: str, tip: str, checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setIcon(icon(name))
    button.setIconSize(QSize(20, 20))
    button.setToolTip(tip)
    button.setAccessibleName(tip.split(" (")[0])
    button.setCheckable(checkable)
    button.setFixedSize(36, 36)
    button.setFocusPolicy(Qt.TabFocus)
    button.setCursor(Qt.PointingHandCursor)
    return button


class ControlBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlBar")
        self.setAttribute(Qt.WA_StyledBackground, True)  # 普通 QWidget 画 QSS 背景必需
        self.setStyleSheet(OVERLAY_QSS)

        self.setFixedHeight(112)

        left = QWidget(self)
        left_l = QHBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(6)
        self.subtitle_btn = _button("subtitles", "AI 字幕开关", checkable=True)
        self.speed_btn = QToolButton()
        self.speed_btn.setObjectName("speedButton")
        self.speed_btn.setText("1x")
        self.speed_btn.setFixedSize(46, 36)
        self.speed_btn.setToolTip("播放速度")
        self.speed_btn.setAccessibleName("播放速度")
        self.speed_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn = _button("skip", "跳过片尾 (Ctrl+S)")
        for widget in (self.subtitle_btn, self.speed_btn, self.skip_btn):
            left_l.addWidget(widget)

        center = QWidget(self)
        center_l = QHBoxLayout(center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.setSpacing(16)
        self.prev_btn = _button("previous", "上一个 (Ctrl+[)")
        self.play_btn = _button("play", "播放/暂停 (空格)")
        self.play_btn.setObjectName("playBig")
        self.play_btn.setFixedSize(44, 44)
        self.play_btn.setIconSize(QSize(24, 24))
        self.next_btn = _button("next", "下一个 (Ctrl+])")
        for widget in (self.prev_btn, self.play_btn, self.next_btn):
            center_l.addWidget(widget, 0, Qt.AlignVCenter)

        right = QWidget(self)
        right_l = QHBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(6)
        self.volume_icon = QLabel()
        self.volume_icon.setPixmap(icon("volume").pixmap(18, 18))
        self.volume_icon.setFixedSize(22, 22)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 130)
        self.volume_slider.setFixedWidth(68)
        self.volume_slider.setToolTip("音量 (↑/↓)")
        self.volume_slider.setAccessibleName("音量")
        self.fullscreen_btn = _button("fullscreen", "全屏 (F)")
        self.airplay_btn = AirPlayButton()
        self.playlist_btn = _button("playlist", "播放列表 (Ctrl+L)", checkable=True)
        for widget in (
            self.volume_icon,
            self.volume_slider,
            self.airplay_btn,
            self.playlist_btn,
            self.fullscreen_btn,
        ):
            right_l.addWidget(widget)

        grid = QGridLayout(self)
        grid.setContentsMargins(18, 48, 18, 14)
        grid.setHorizontalSpacing(12)
        grid.addWidget(left, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(center, 0, 1, Qt.AlignCenter)
        grid.addWidget(right, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        self._grid = grid

    def set_paused(self, paused: bool) -> None:
        self.play_btn.setIcon(icon("play" if paused else "pause", "#14171c"))
        self.play_btn.setAccessibleName("播放" if paused else "暂停")

    def set_compact(self, compact: bool) -> None:
        self.volume_slider.setVisible(not compact)
        self.volume_icon.setVisible(not compact)
        self.skip_btn.setVisible(not compact)
        narrow = self.width() < 460
        self.subtitle_btn.setVisible(not narrow)
        self.speed_btn.setVisible(not narrow)
        self._grid.setHorizontalSpacing(6 if narrow else 12)
