"""视频区容器：mpv 画面全幅铺满，悬浮控制层宿主。

自身作为所有鼠标事件的汇聚点（mpv 画面控件对鼠标透明），负责：
- 悬浮层几何布局（顶栏/控制条/时间轴/列表抽屉/OSD）
- 控制层显隐应用（字幕叠层自动避让）
- 单击播放暂停、双击全屏（250ms 消歧）
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QWidget

from player.core.playback import Playback
from player.ui.control_bar import ControlBar
from player.ui.empty_state import EmptyState
from player.ui.mpv_widget import MpvWidget
from player.ui.osd import OsdLabel
from player.ui.playlist_drawer import PlaylistDrawer
from player.ui.status_chip import StatusChip
from player.ui.subtitle_overlay import SubtitleOverlay
from player.ui.timeline_slider import TimelineSlider

_SINGLE_CLICK_MS = 240
_TIMELINE_H = 28


class VideoArea(QWidget):
    mouse_activity = Signal()
    single_clicked = Signal()
    double_clicked = Signal()
    scrub_started = Signal()
    scrub_moved = Signal(float)
    scrub_finished = Signal(float)

    def __init__(self, playback: Playback, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self.mpv_widget = MpvWidget(playback, self)
        self.mpv_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.subtitle = SubtitleOverlay(self)
        self.status_chip = StatusChip(self)
        self.media_title = QLabel(self)
        self.media_title.setObjectName("videoTitle")
        self.media_title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.media_title.setVisible(False)
        self.control_bar = ControlBar(self)
        # 进度条直接浮在视频上（UI v2 设计）：半透明轨道能透出画面，
        # 不放进控制条胶囊——背后是深色面板会让透视效果失效
        self.timeline = TimelineSlider(self)
        self.drawer = PlaylistDrawer(self)
        self.osd = OsdLabel(self)
        self.empty_state = EmptyState(self)
        self.empty_state.raise_()

        self._controls_shown = True
        self._fullscreen = False
        self._last_mouse_pos = None  # 过滤原地重复的 MouseMove（隐藏控制层时的重投递）

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(_SINGLE_CLICK_MS)
        self._click_timer.timeout.connect(self.single_clicked.emit)

        # 子控件鼠标事件也算用户活动。
        for widget in (self.control_bar, self.timeline, self.drawer):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

        self.timeline.scrub_started.connect(self.scrub_started.emit)
        self.timeline.scrub_moved.connect(self.scrub_moved.emit)
        self.timeline.scrub_finished.connect(self.scrub_finished.emit)

    def cursor_over_controls(self) -> bool:
        """光标悬停在任一控制悬浮层上：此时保持显示（IINA 同款行为）。"""
        return bool(self.control_bar.underMouse() or self.timeline.underMouse() or self.drawer.underMouse())

    def set_empty_state(self, visible: bool) -> None:
        self.empty_state.setVisible(visible)
        self.control_bar.setVisible(not visible and self._controls_shown)
        self.status_chip.setVisible(not visible and self._controls_shown and bool(self.status_chip.text()))
        self.media_title.setVisible(not visible and bool(self.media_title.text()))
        if visible:
            self.timeline.setVisible(False)
            self.subtitle.show_text(None)
        else:
            self.timeline.setVisible(self._controls_shown)
            self._relayout()
        self._place_subtitle()
        self.empty_state.raise_()

    def set_media_title(self, title: str) -> None:
        self.media_title.setText(title)
        self.media_title.adjustSize()
        self.media_title.setVisible(bool(title) and not self.empty_state.isVisible())

    # ---- 显隐 ----

    @property
    def controls_shown(self) -> bool:
        return self._controls_shown

    def set_controls_shown(self, shown: bool) -> None:
        if shown == self._controls_shown:
            return
        self._controls_shown = shown
        media_visible = not self.empty_state.isVisible()
        self.status_chip.setVisible(shown and media_visible and bool(self.status_chip.text()))
        self.media_title.setVisible(media_visible and bool(self.media_title.text()))
        self.control_bar.setVisible(shown and media_visible)
        self.timeline.setVisible(shown and media_visible)
        self._place_subtitle()

    def set_fullscreen(self, on: bool) -> None:
        self._fullscreen = on
        self._relayout()

    # ---- 几何 ----

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.mpv_widget.setGeometry(self.rect())
        self._relayout()
        self.drawer.relayout()
        self.osd.reposition()
        self.empty_state.setGeometry(self.rect())
        self.empty_state.raise_()

    def _relayout(self) -> None:
        w, h = self.width(), self.height()
        margin = 24 if self._fullscreen else 20
        cw = min(900, max(340, w - 2 * margin))
        ch = self.control_bar.height()
        self.control_bar.setGeometry((w - cw) // 2, h - _TIMELINE_H - ch - margin, cw, ch)
        self.control_bar.set_compact(w < 690)
        self.timeline.setGeometry(0, h - _TIMELINE_H, w, _TIMELINE_H)
        self.media_title.move(margin, margin)
        self.status_chip.move(margin, margin + 30)
        self._place_subtitle()

    # ---- 字幕 ----

    def set_subtitle_text(self, text: str | None) -> None:
        self.subtitle.show_text(text)

    # ---- 字幕避让 ----

    def _place_subtitle(self) -> None:
        if self._controls_shown:
            bottom = self.control_bar.height() + (24 if self._fullscreen else 20) + 16
        else:
            bottom = 42
        self.subtitle.bottom_margin = bottom
        self.subtitle.reposition()

    # ---- OSD ----

    def show_osd(self, text: str) -> None:
        self.osd.show_message(text)

    # ---- 列表抽屉 ----

    def toggle_playlist(self) -> None:
        self.drawer.toggle()

    def hide_playlist(self) -> None:
        if self.drawer.isVisible():
            self.drawer.slide_out()

    # ---- 鼠标 ----

    def _real_mouse_move(self, event) -> bool:
        """过滤同位置的重复 MouseMove：控制层隐藏时 macOS 会向下方控件
        重投递鼠标事件，不能算作用户活动，否则显隐振荡。"""
        try:
            pos = event.globalPosition()
        except AttributeError:
            return False
        if self._last_mouse_pos is not None and (pos - self._last_mouse_pos).manhattanLength() < 3:
            return False
        self._last_mouse_pos = pos
        return True

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        etype = event.type()
        if etype == event.Type.MouseMove and self._real_mouse_move(event):
            self.mouse_activity.emit()
        elif etype == event.Type.Enter and self._real_mouse_move(event):
            self.mouse_activity.emit()
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._real_mouse_move(event):
            self.mouse_activity.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.mouse_activity.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and not self._click_timer.isActive():
            self._click_timer.start()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._click_timer.stop()  # 取消待发的单击事件
            self.double_clicked.emit()
