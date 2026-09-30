"""视频区容器：mpv 画面铺满 + AI 字幕叠层定位。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from player.core.playback import Playback
from player.ui.mpv_widget import MpvWidget
from player.ui.subtitle_overlay import SubtitleOverlay


class VideoArea(QWidget):
    def __init__(self, playback: Playback, parent=None):
        super().__init__(parent)
        self.mpv_widget = MpvWidget(playback, self)
        self.mpv_widget.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.overlay = SubtitleOverlay(self)
        self.setMinimumSize(320, 180)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self.mpv_widget.setGeometry(self.rect())
        self.overlay.reposition()

    def set_subtitle_text(self, text: str | None) -> None:
        self.overlay.show_text(text)
