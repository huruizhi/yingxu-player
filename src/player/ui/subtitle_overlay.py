"""AI 字幕叠层：视频底部中央的半透明圆角文本条。

仅显示 AI 生成的字幕；MKV 内置字幕由 mpv 自行渲染，二者互不干扰。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

_STYLE = """
QLabel {
    background-color: rgba(0, 0, 0, 175);
    border-radius: 8px;
    color: #ffffff;
    padding: 8px 18px;
    font-size: 21px;
    font-weight: 500;
}
"""


class SubtitleOverlay(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # 不挡视频区交互
        self.setStyleSheet(_STYLE)
        self.setVisible(False)
        self._shown: str | None = None

    def show_text(self, text: str | None) -> None:
        """更新字幕文本；None/空串隐藏。文本变化才重排，避免每帧闪烁。"""
        if text == self._shown:
            return
        self._shown = text
        if text:
            self.setText(text)
            self.setVisible(True)
            self._reflow()
        else:
            self.clear()
            self.setVisible(False)

    def _reflow(self) -> None:
        self.adjustSize()
        self._place()

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        w = min(self.width(), parent.width())
        x = (parent.width() - w) // 2
        y = parent.height() - self.height() - 36
        self.setGeometry(max(0, x), max(0, y), w, self.height())

    def reposition(self) -> None:
        """容器尺寸变化时由 VideoArea 调用。"""
        parent = self.parentWidget()
        if parent is not None:
            self.setMaximumWidth(int(parent.width() * 0.8))
        if self.isVisible():
            self._reflow()
