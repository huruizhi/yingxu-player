"""时间轴细进度条：贴底细线，悬停变粗，拖拽 seek，AI 已转写区间淡色高亮。

另叠加章节刻度（细白线）与 AB 循环区间（淡绿色）。
当前时间与总时长内嵌于线条两端（Aurora 式布局）。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget

from player.ui.theme import CHAPTER_TICK, COVERED_TINT, LOOP_TINT, PLAYED_COLOR, TRACK_BG

_BAR_THIN = 4
_BAR_THICK = 10
_TIME_STYLE = "color: rgba(232, 232, 235, 0.9); font-size: 11px; background: transparent;"


def _fmt(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class TimelineSlider(QWidget):
    """全宽贴底时间轴；视觉条自底部生长，命中区更高便于点击。"""

    scrub_started = Signal()
    scrub_moved = Signal(float)  # 预览位置（秒）
    scrub_finished = Signal(float)  # 落点（秒）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._position = 0.0
        self._duration = 0.0
        self._covered: list[tuple[float, float]] = []
        self._chapters: list[float] = []
        self._loop_range: tuple[float, float] | None = None
        self._hovered = False
        self._scrubbing = False
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(22)

        self.left_label = QLabel("00:00", self)
        self.left_label.setStyleSheet(_TIME_STYLE)
        self.left_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.right_label = QLabel("--:--", self)
        self.right_label.setStyleSheet(_TIME_STYLE)
        self.right_label.setAttribute(Qt.WA_TransparentForMouseEvents)

    # ---- 数据 ----

    def set_position(self, position: float, duration: float) -> None:
        self._position = max(0.0, position)
        self._duration = max(0.0, duration)
        self.left_label.setText(_fmt(self._position))
        self.right_label.setText(_fmt(self._duration))
        self._place_labels()
        self.update()

    def set_covered(self, ranges: list[tuple[float, float]]) -> None:
        self._covered = list(ranges)
        self.update()

    def set_chapters(self, times: list[float]) -> None:
        self._chapters = [float(t) for t in times]
        self.update()

    def set_loop_range(self, start: float | None, end: float | None) -> None:
        self._loop_range = (start, end) if start is not None and end is not None else None
        self.update()

    # ---- 几何 ----

    def _place_labels(self) -> None:
        self.left_label.adjustSize()
        self.right_label.adjustSize()
        self.left_label.move(12, 1)
        self.right_label.move(self.width() - self.right_label.width() - 12, 1)

    def _bar_rect(self) -> QRectF:
        h = _BAR_THICK if (self._hovered or self._scrubbing) else _BAR_THIN
        return QRectF(0, self.height() - h, self.width(), h)

    def _time_at(self, x: float) -> float:
        if self._duration <= 0 or self.width() <= 0:
            return 0.0
        return max(0.0, min(1.0, x / self.width())) * self._duration

    # ---- 绘制 ----

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bar = self._bar_rect()
        radius = bar.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(TRACK_BG)
        painter.drawRoundedRect(bar, radius, radius)
        if self._duration <= 0:
            return
        w = self.width()
        painter.setBrush(COVERED_TINT)
        for lo, hi in self._covered:
            x0, x1 = lo / self._duration * w, min(hi, self._duration) / self._duration * w
            if x1 > x0:
                painter.drawRoundedRect(QRectF(x0, bar.top(), x1 - x0, bar.height()), radius, radius)
        if self._loop_range is not None:
            a, b = self._loop_range
            x0, x1 = a / self._duration * w, min(b, self._duration) / self._duration * w
            if x1 > x0:
                painter.setBrush(LOOP_TINT)
                painter.drawRoundedRect(QRectF(x0, bar.top(), x1 - x0, bar.height()), radius, radius)
        played_w = min(self._position / self._duration, 1.0) * w
        if played_w > 0:
            painter.setBrush(PLAYED_COLOR)
            painter.drawRoundedRect(QRectF(0, bar.top(), played_w, bar.height()), radius, radius)
        if self._chapters:
            painter.setPen(QPen(CHAPTER_TICK, 1.4))
            for time in self._chapters:
                if 0 < time < self._duration:
                    x = time / self._duration * w
                    painter.drawLine(QPointF(x, bar.top() + 1), QPointF(x, bar.bottom() - 1))
            painter.setPen(Qt.NoPen)
        if self._hovered or self._scrubbing:
            painter.setBrush(Qt.white)
            painter.drawEllipse(QRectF(played_w - 5, bar.center().y() - 5, 10, 10))

    # ---- 交互 ----

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_labels()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._scrubbing = True
            self.scrub_started.emit()
            self.scrub_moved.emit(self._time_at(event.position().x()))
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._scrubbing:
            self.scrub_moved.emit(self._time_at(event.position().x()))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._scrubbing:
            self._scrubbing = False
            self.scrub_finished.emit(self._time_at(event.position().x()))
            self.update()
