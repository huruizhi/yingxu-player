"""主窗口：组装播放内核、播放列表、AI 字幕、片尾跳过与全部交互。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from player.ai.skip import CreditsSkipper
from player.ai.subtitles import SubtitleStore
from player.ai.transcriber import Transcriber
from player.ai.whisper_backend import WhisperBackend
from player.core.playback import Playback
from player.core.playlist import LoopMode, Playlist, scan_media_files
from player.core.settings import AI_MODELS, Settings, SubtitleSource
from player.core.store import Store
from player.ui.playlist_panel import PlaylistPanel
from player.ui.video_area import VideoArea

_TICK_MS = 250
_PROGRESS_SAVE_TICKS = 20  # ~5 秒落盘一次


def _fmt_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class SeekSlider(QSlider):
    """点击即跳转的进度条。"""

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            ratio = event.position().x() / max(1.0, float(self.width()))
            value = self.minimum() + round(ratio * (self.maximum() - self.minimum()))
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.sliderReleased.emit()
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    transcriber_status = Signal(str)  # 转写线程状态 → 状态栏（跨线程封送）

    def __init__(
        self,
        settings: Settings,
        store: Store,
        subtitle_cache_dir: Path,
        playback: Playback | None = None,
    ):
        super().__init__()
        self.settings = settings
        self.store = store
        self.playlist = Playlist()
        self.subtitles = SubtitleStore(subtitle_cache_dir)
        self.skipper = CreditsSkipper(store)
        self.skipper.on_skip = self._advance_to_next

        self.playback = playback if playback is not None else Playback(self)
        self._stt: WhisperBackend | None = None
        self._stt_model_size: str | None = None
        self._transcriber: Transcriber | None = None

        self._current_file: Path | None = None
        self._ai_active = False
        self._ai_override: bool | None = None  # 本次播放的手动开关覆盖
        self._subtitles_loaded_from_cache = False
        self._pending_resume: float | None = None
        self._scrubbing = False
        self._tick_count = 0

        self.setWindowTitle("Player")
        self.setAcceptDrops(True)
        self._build_ui()
        self._build_menus()
        self._build_shortcuts()
        self._connect_playback()
        self._restore_window()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(_TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        self.playback.set_volume(settings.volume)
        self.playback.set_speed(settings.speed)
        self._update_skip_ui()

    # ================= UI 构建 =================

    def _build_ui(self) -> None:
        self.video_area = VideoArea(self.playback)

        # ---- 控制栏 ----
        bar = QWidget()
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(8, 4, 8, 6)
        bar_l.setSpacing(6)

        def button(text: str, tip: str) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            return b

        self.prev_btn = button("⏮", "上一个 (Ctrl+[)")
        self.play_btn = button("▶", "播放/暂停 (空格)")
        self.next_btn = button("⏭", "下一个 (Ctrl+])")
        self.time_label = QLabel("00:00")
        self.seek_slider = SeekSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setFocusPolicy(Qt.NoFocus)
        self.duration_label = QLabel("--:--")

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 130)
        self.volume_slider.setValue(self.settings.volume)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.setFocusPolicy(Qt.NoFocus)
        self.volume_slider.setToolTip("音量 (↑/↓)")

        self.speed_btn = button("1.0x", "倍速")
        self.subtitle_btn = button("字", "AI 字幕开关")
        self.subtitle_btn.setCheckable(True)
        self.skip_btn = button("跳过片尾 ⏭", "跳到下一集 (Ctrl+S)")
        self.mark_btn = button("标记片尾", "把当前位置记为片尾起点 (Ctrl+M)")
        self.playlist_btn = button("☰ 列表", "播放列表 (Ctrl+L)")

        for w in (
            self.prev_btn,
            self.play_btn,
            self.next_btn,
            self.time_label,
            self.seek_slider,
            self.duration_label,
            self.volume_slider,
            self.speed_btn,
            self.subtitle_btn,
            self.skip_btn,
            self.mark_btn,
            self.playlist_btn,
        ):
            bar_l.addWidget(w)
        bar_l.setStretch(3, 0)
        bar_l.setStretch(4, 1)

        root = QWidget()
        root_l = QVBoxLayout(root)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.setSpacing(0)
        root_l.addWidget(self.video_area, 1)
        root_l.addWidget(bar)
        self.setCentralWidget(root)

        # ---- 播放列表面板 ----
        self.playlist_panel = PlaylistPanel()
        self.playlist_dock = QDockWidget("播放列表", self)
        self.playlist_dock.setWidget(self.playlist_panel)
        self.playlist_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.playlist_dock)
        self.playlist_dock.hide()

        self.statusBar().showMessage("拖入视频/音频文件开始播放")

    def _build_menus(self) -> None:
        menu = self.menuBar()

        # 文件
        m_file = menu.addMenu("文件")
        self.act_open = QAction("打开文件…", self)
        self.act_open.setShortcut(QKeySequence("Ctrl+O"))
        self.act_open_dir = QAction("打开目录…", self)
        self.act_open_dir.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.act_export = QAction("导出 AI 字幕 (.srt)…", self)
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        for a in (self.act_open, self.act_open_dir, self.act_export):
            m_file.addAction(a)
        m_file.addSeparator()
        m_file.addAction(act_quit)

        # 播放
        m_play = menu.addMenu("播放")
        self.act_prev = QAction("上一个", self)
        self.act_prev.setShortcut(QKeySequence("Ctrl+["))
        self.act_next = QAction("下一个", self)
        self.act_next.setShortcut(QKeySequence("Ctrl+]"))
        m_play.addAction(self.act_prev)
        m_play.addAction(self.act_next)
        m_play.addSeparator()
        self._loop_group = QActionGroup(self)
        self._loop_actions: dict[LoopMode, QAction] = {}
        for mode, label in (
            (LoopMode.SINGLE, "单曲循环"),
            (LoopMode.ALL, "列表循环"),
            (LoopMode.SHUFFLE, "随机播放"),
        ):
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda _c, m=mode: self._set_loop_mode(m))
            self._loop_group.addAction(act)
            self._loop_actions[mode] = act
            m_play.addAction(act)
        try:
            self.playlist.set_mode(LoopMode(self.settings.playlist_mode))
        except ValueError:
            self.playlist.set_mode(LoopMode.ALL)
        self._loop_actions[self.playlist.mode].setChecked(True)

        # 字幕
        m_sub = menu.addMenu("字幕")
        self._source_group = QActionGroup(self)
        self._source_actions: dict[SubtitleSource, QAction] = {}
        for src, label in (
            (SubtitleSource.AUTO, "AI 字幕：自动（无内置字幕时启用）"),
            (SubtitleSource.FORCE_AI, "AI 字幕：始终启用"),
            (SubtitleSource.OFF, "AI 字幕：关闭"),
        ):
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda _c, s=src: self._set_subtitle_source(s))
            self._source_group.addAction(act)
            self._source_actions[src] = act
            m_sub.addAction(act)
        self._source_actions[self.settings.subtitle_source].setChecked(True)
        self._audio_menu = m_sub.addMenu("音轨")
        self._sub_menu = m_sub.addMenu("内置字幕轨")
        m_sub.addAction(self.act_export)

        # 片尾
        m_skip = menu.addMenu("片尾")
        self.act_skip_toggle = QAction("自动跳过片尾", self, checkable=True)
        self.act_skip_toggle.setChecked(self.settings.skip_credits_enabled)
        self.act_skip_toggle.triggered.connect(self._toggle_skip_enabled)
        self.act_mark = QAction("标记片尾点（当前位置）", self)
        self.act_mark.setShortcut(QKeySequence("Ctrl+M"))
        self.act_clear_mark = QAction("清除本文件片尾标记", self)
        m_skip.addAction(self.act_skip_toggle)
        m_skip.addSeparator()
        m_skip.addAction(self.act_mark)
        m_skip.addAction(self.act_clear_mark)

        # 设置
        m_set = menu.addMenu("设置")
        self._model_menu = m_set.addMenu("AI 字幕模型")
        self._model_group = QActionGroup(self)
        self._model_actions: dict[str, QAction] = {}
        for size in AI_MODELS:
            act = QAction(
                f"{size}（{'快' if size in ('tiny', 'base') else '较慢/更准'}）", self, checkable=True
            )
            act.triggered.connect(lambda _c, s=size: self._set_ai_model(s))
            self._model_group.addAction(act)
            self._model_actions[size] = act
            self._model_menu.addAction(act)
        self._model_actions[self.settings.ai_model].setChecked(True)

        self._lang_menu = m_set.addMenu("字幕语言")
        self._lang_group = QActionGroup(self)
        self._lang_actions: dict[str, QAction] = {}
        for lang, label in (("auto", "自动检测"), ("zh", "中文"), ("en", "英文")):
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda _c, code=lang: self._set_ai_language(code))
            self._lang_group.addAction(act)
            self._lang_actions[lang] = act
            self._lang_menu.addAction(act)
        self._lang_actions[self.settings.ai_language].setChecked(True)

    def _build_shortcuts(self) -> None:
        def bind(seq: str, slot) -> None:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)

        bind("Space", self.playback.toggle_play)
        bind("Left", lambda: self.playback.seek_relative(-10))
        bind("Right", lambda: self.playback.seek_relative(10))
        bind("Up", lambda: self._change_volume(+5))
        bind("Down", lambda: self._change_volume(-5))
        bind("Ctrl+L", self._toggle_playlist)

        self.prev_btn.clicked.connect(lambda: self._play_sibling(-1))
        self.next_btn.clicked.connect(lambda: self._play_sibling(+1))
        self.act_prev.triggered.connect(lambda: self._play_sibling(-1))
        self.act_next.triggered.connect(lambda: self._play_sibling(+1))
        self.play_btn.clicked.connect(self.playback.toggle_play)
        self.subtitle_btn.clicked.connect(self._toggle_ai_manual)
        self.skip_btn.clicked.connect(self.skipper.manual_skip)
        self.mark_btn.clicked.connect(self._mark_credits)
        self.act_mark.triggered.connect(self._mark_credits)
        self.act_clear_mark.triggered.connect(self._clear_credits)
        self.playlist_btn.clicked.connect(self._toggle_playlist)
        self.act_open.triggered.connect(self._open_file_dialog)
        self.act_open_dir.triggered.connect(self._open_dir_dialog)
        self.act_export.triggered.connect(self._export_srt)
        self.playlist_panel.item_activated.connect(self.play_path)
        self.skipper.enabled = self.settings.skip_credits_enabled

        self.speed_menu = QMenu(self)
        for s in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            act = QAction(f"{s:g}x", self, checkable=True)
            act.setChecked(abs(self.settings.speed - s) < 1e-6)
            act.triggered.connect(lambda _c, v=s: self._set_speed(v))
            self.speed_menu.addAction(act)
        self.speed_btn.setMenu(self.speed_menu)
        self.speed_btn.setPopupMode(QToolButton.InstantPopup)

    def _connect_playback(self) -> None:
        self.playback.paused_changed.connect(self._on_paused_changed)
        self.playback.duration_changed.connect(self._on_duration_changed)
        self.playback.tracks_changed.connect(self._on_tracks_changed)
        self.playback.end_reached.connect(self._on_end_reached)
        self.playback.file_changed.connect(self._on_file_changed)

        self.seek_slider.sliderPressed.connect(lambda: setattr(self, "_scrubbing", True))
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        self.seek_slider.sliderMoved.connect(lambda v: self.time_label.setText(_fmt_time(v / 1000)))
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.transcriber_status.connect(lambda text: self.statusBar().showMessage(text, 4000))

    def _restore_window(self) -> None:
        geo = self.settings.window or {}
        if geo.get("w") and geo.get("h"):
            self.resize(int(geo["w"]), int(geo["h"]))
            if geo.get("x") is not None and geo.get("y") is not None:
                self.move(int(geo["x"]), int(geo["y"]))
            if geo.get("maximized"):
                self.showMaximized()
        else:
            self.resize(960, 600)

    # ================= 打开与播放 =================

    def open_path(self, path: Path) -> None:
        """打开文件或目录：文件自动带起同目录播放列表。"""
        path = Path(path).expanduser()
        if path.is_dir():
            files = scan_media_files(path)
            if not files:
                self.statusBar().showMessage("该目录没有可播放的媒体文件", 4000)
                return
            self.playlist.load_directory(path)
            self._refresh_playlist_panel()
            self.play_path(files[0])
            return
        if not path.is_file():
            self.statusBar().showMessage(f"文件不存在：{path}", 4000)
            return
        if not self.playlist.items or path.parent != self.playlist.items[0].parent:
            self.playlist.load_directory(path.parent, start_file=path)
            self._refresh_playlist_panel()
        else:
            self.playlist.jump_to_path(path)
            self._refresh_playlist_panel()
        self.play_path(path)

    def play_path(self, path: Path) -> None:
        path = Path(path)
        self._stop_transcriber()
        self._save_progress_now()
        self._current_file = path
        self._ai_override = None
        self._pending_resume = self.store.get_progress(path)
        self._subtitles_loaded_from_cache = False

        self.subtitles.clear_runtime()
        self.skipper.on_file_opened(path)
        self.playback.load(path)

        self.setWindowTitle(f"{path.name} — Player")
        if self.playlist.items:
            self.playlist.jump_to_path(path)  # 文件在列表中时同步当前项
        self.playlist_panel.highlight_current(self.playlist.current_item)
        self._update_skip_ui()
        if self._pending_resume:
            self.statusBar().showMessage(f"已恢复到上次进度 {_fmt_time(self._pending_resume)}", 4000)
        else:
            self.statusBar().showMessage(path.name, 4000)

    def _play_sibling(self, direction: int) -> None:
        nxt = self.playlist.next() if direction > 0 else self.playlist.previous()
        if nxt is not None:
            self.play_path(nxt)
        else:
            self.statusBar().showMessage("播放列表为空", 3000)

    def _advance_to_next(self) -> None:
        """片尾跳过/自然播完时的自动连播入口。"""
        nxt = self.playlist.next(auto=True)
        if nxt is not None:
            self.play_path(nxt)
        elif self._current_file is not None:
            self.statusBar().showMessage("播放结束", 3000)

    # ================= 播放回调 =================

    def _on_file_changed(self, path: str) -> None:
        if not self._current_file or Path(path) != self._current_file.resolve():
            self._current_file = Path(path)
        # 载入时轨道信息尚未就绪，先按"无内置字幕"预应用一次；
        # track-list 事件到达后 _on_tracks_changed 会再校正
        self._apply_subtitle_policy()

    def _on_paused_changed(self, paused: bool) -> None:
        self.play_btn.setText("▶" if paused else "⏸")

    def _on_duration_changed(self, duration: float) -> None:
        self.seek_slider.setRange(0, int(duration * 1000))
        self.duration_label.setText(_fmt_time(duration))
        if self._pending_resume and duration > 0:
            pos, self._pending_resume = self._pending_resume, None
            if pos < duration - 5:
                self.playback.seek_absolute(pos, exact=False)
        if self._ai_active and not self._transcriber and not self._subtitles_loaded_from_cache:
            self._start_ai_transcription()  # 拿到时长后再启动转写

    def _on_tracks_changed(self) -> None:
        self._rebuild_track_menus()
        self._apply_subtitle_policy()

    def _on_end_reached(self) -> None:
        self._advance_to_next()

    # ================= 字幕策略 =================

    def _apply_subtitle_policy(self) -> None:
        """按设置中的字幕源策略 + 当前文件轨道情况，决定 AI 字幕是否启用。"""
        mode = self.settings.subtitle_source
        has_embedded = bool(self.playback.sub_tracks())
        if mode is SubtitleSource.FORCE_AI:
            self.playback.select_sub_track(None)  # 隐藏内置字幕，避免重叠
        elif mode is SubtitleSource.AUTO:
            self.playback.reset_sub_track_auto()
        wanted = mode is SubtitleSource.FORCE_AI or (mode is SubtitleSource.AUTO and not has_embedded)
        if self._ai_override is not None:
            wanted = self._ai_override
        self._set_ai_active(wanted)

    def _set_ai_active(self, active: bool) -> None:
        self._ai_active = active
        self.subtitle_btn.setChecked(active)
        self.subtitle_btn.setToolTip("AI 字幕：开启中（点击关闭）" if active else "AI 字幕：关闭（点击开启）")
        if active:
            self._start_ai_transcription()
        else:
            self._stop_transcriber()
            self.subtitles.clear_runtime()
            self.video_area.set_subtitle_text(None)

    def _toggle_ai_manual(self) -> None:
        self._ai_override = not self._ai_active
        self._set_ai_active(self._ai_override)
        self.statusBar().showMessage("AI 字幕：开启" if self._ai_override else "AI 字幕：关闭", 3000)

    def _start_ai_transcription(self) -> None:
        if self._current_file is None:
            return
        duration = self.playback.duration() or 0.0
        if self.subtitles.try_load_cache(self._current_file, duration):
            self._subtitles_loaded_from_cache = True
            self.statusBar().showMessage("已加载缓存的 AI 字幕", 4000)
            return
        if self._transcriber is not None:
            return
        if duration <= 0:
            return  # 等 duration_changed 再启动
        if self._stt is None or self._stt_model_size != self.settings.ai_model:
            self._stt = WhisperBackend(model_size=self.settings.ai_model, language=self.settings.ai_language)
            self._stt_model_size = self.settings.ai_model
        decoder = self._make_decoder(self._current_file)
        if decoder is None:
            self.statusBar().showMessage("该文件没有音频轨，无法生成 AI 字幕", 4000)
            return
        self._transcriber = Transcriber(
            self._stt,
            decoder,
            self.subtitles,
            self._current_file,
            duration,
            on_status=self.transcriber_status.emit,
        )
        self._transcriber.start(self.playback.position() or 0.0)

    @staticmethod
    def _make_decoder(path: Path):
        from player.ai.audio_source import AudioDecodeError, AudioDecoder

        try:
            return AudioDecoder(path)
        except AudioDecodeError as exc:
            print(f"[ai] {exc}")
            return None

    def _stop_transcriber(self) -> None:
        if self._transcriber is not None:
            self._transcriber.stop()
            self._transcriber = None

    def _set_subtitle_source(self, source: SubtitleSource) -> None:
        self.settings.subtitle_source = source
        self._ai_override = None
        self._apply_subtitle_policy()

    def _set_ai_model(self, size: str) -> None:
        self.settings.ai_model = size
        if self._transcriber is not None:  # 换模型即重启转写
            self._stop_transcriber()
            self.subtitles.clear_runtime()
            self._stt = None
            self._start_ai_transcription()

    def _set_ai_language(self, lang: str) -> None:
        self.settings.ai_language = lang
        if self._stt is not None:
            self._stt.language = lang

    def _export_srt(self) -> None:
        if self._current_file is None or not self.subtitles.all_segments():
            self.statusBar().showMessage("当前文件还没有可导出的 AI 字幕", 4000)
            return
        dest = self.subtitles.export_srt(self._current_file)
        self.statusBar().showMessage(f"AI 字幕已导出：{dest}", 6000)

    # ================= 轨道菜单 =================

    def _rebuild_track_menus(self) -> None:
        self._audio_menu.clear()
        self._sub_menu.clear()
        audio_tracks = self.playback.audio_tracks()
        sub_tracks = self.playback.sub_tracks()

        if audio_tracks:
            group = QActionGroup(self._audio_menu)
            for t in audio_tracks:
                act = QAction(self._track_label(t, "音轨"), self._audio_menu, checkable=True)
                act.setChecked(t.selected)
                act.triggered.connect(lambda _c, tid=t.id: self.playback.select_audio_track(tid))
                group.addAction(act)
                self._audio_menu.addAction(act)
        else:
            empty = QAction("（无音轨）", self._audio_menu)
            empty.setEnabled(False)
            self._audio_menu.addAction(empty)

        if sub_tracks:
            act_off = QAction("关闭", self._sub_menu, checkable=True)
            act_off.triggered.connect(lambda: self.playback.select_sub_track(None))
            self._sub_menu.addAction(act_off)
            group = QActionGroup(self._sub_menu)
            for t in sub_tracks:
                act = QAction(self._track_label(t, "字幕"), self._sub_menu, checkable=True)
                act.setChecked(t.selected)
                act.triggered.connect(lambda _c, tid=t.id: self.playback.select_sub_track(tid))
                group.addAction(act)
                self._sub_menu.addAction(act)
        else:
            empty = QAction("（无内置字幕轨）", self._sub_menu)
            empty.setEnabled(False)
            self._sub_menu.addAction(empty)

    @staticmethod
    def _track_label(track, kind: str) -> str:
        parts = [f"{kind} {track.id}"]
        if track.title:
            parts.append(track.title)
        if track.lang:
            parts.append(f"[{track.lang}]")
        return " ".join(parts)

    # ================= 片尾 =================

    def _mark_credits(self) -> None:
        if self._current_file is None:
            return
        pos = self.playback.position()
        if pos is None:
            return
        self.store.mark_credits(self._current_file, pos)
        self.skipper.on_file_opened(self._current_file)
        self._update_skip_ui()
        self.statusBar().showMessage(f"已标记片尾起点 {_fmt_time(pos)}（对同目录文件同样生效）", 6000)

    def _clear_credits(self) -> None:
        if self._current_file is None:
            return
        if self.store.clear_credits(self._current_file):
            self.skipper.on_file_opened(self._current_file)
            self._update_skip_ui()
            self.statusBar().showMessage("已清除片尾标记", 3000)

    def _toggle_skip_enabled(self, checked: bool) -> None:
        self.settings.skip_credits_enabled = checked
        self.skipper.enabled = checked
        self._update_skip_ui()
        self.statusBar().showMessage("自动跳过片尾：开" if checked else "自动跳过片尾：关", 3000)

    def _update_skip_ui(self) -> None:
        has_mark = self._current_file is not None and self.skipper.has_mark()
        self.skip_btn.setEnabled(True)
        self.skip_btn.setToolTip(
            "跳过片尾 (Ctrl+S)" + ("" if has_mark else "（本目录未标记片尾，将直接跳到下一集）")
        )

    # ================= 控件联动 =================

    def _on_tick(self) -> None:
        pos = self.playback.position()
        duration = self.playback.duration()
        if pos is not None and not self._scrubbing:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(int(pos * 1000))
            self.seek_slider.blockSignals(False)
        if pos is not None:
            self.time_label.setText(_fmt_time(pos))

        if self._current_file is None or pos is None:
            return

        self._tick_count += 1
        if self._transcriber is not None:
            self._transcriber.notify_position(pos)
        seg = self.subtitles.current(pos)
        self.video_area.set_subtitle_text(seg.text if seg else None)
        self.skipper.on_position(pos)
        if self._tick_count % _PROGRESS_SAVE_TICKS == 0 and duration:
            self.store.set_progress(self._current_file, pos, duration)
            self.store.save()

    def _on_seek_released(self) -> None:
        self._scrubbing = False
        self.playback.seek_absolute(self.seek_slider.value() / 1000, exact=False)

    def _on_volume_changed(self, value: int) -> None:
        self.settings.volume = value
        self.playback.set_volume(value)

    def _change_volume(self, delta: int) -> None:
        self.volume_slider.setValue(self.volume_slider.value() + delta)

    def _set_speed(self, speed: float) -> None:
        self.settings.speed = speed
        self.playback.set_speed(speed)
        self.speed_btn.setText(f"{speed:g}x")
        for act in self.speed_menu.actions():
            act.setChecked(abs(float(act.text().rstrip("x")) - speed) < 1e-6)

    def _set_loop_mode(self, mode: LoopMode) -> None:
        self.playlist.set_mode(mode)
        self.settings.playlist_mode = mode.value

    def _toggle_playlist(self) -> None:
        self.playlist_dock.setVisible(not self.playlist_dock.isVisible())

    def _refresh_playlist_panel(self) -> None:
        self.playlist_panel.populate(self.playlist.items, self.playlist.current_item)

    # ================= 对话框与拖拽 =================

    def _open_file_dialog(self) -> None:
        exts = " ".join(
            f"*{e}"
            for e in sorted(
                {
                    ".mkv",
                    ".mp4",
                    ".mov",
                    ".avi",
                    ".webm",
                    ".ts",
                    ".m4v",
                    ".flv",
                    ".wmv",
                    ".mp3",
                    ".flac",
                    ".m4a",
                    ".wav",
                    ".aac",
                    ".ogg",
                    ".opus",
                }
            )
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "打开媒体文件", str(Path.home()), f"媒体文件 ({exts});;所有文件 (*)"
        )
        if path:
            self.open_path(Path(path))

    def _open_dir_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "打开目录", str(Path.home()))
        if path:
            self.open_path(Path(path))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        from player.core.playlist import MEDIA_EXTENSIONS

        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        media = [p for p in paths if p.suffix.lower() in MEDIA_EXTENSIONS]
        dirs = [p for p in paths if p.is_dir()]
        if media:
            self.open_path(media[0])
        elif dirs:
            self.open_path(dirs[0])
        else:
            self.statusBar().showMessage("没有可播放的媒体文件", 3000)

    # ================= 关闭与清理 =================

    def _save_progress_now(self) -> None:
        if self._current_file is None:
            return
        pos = self.playback.position()
        dur = self.playback.duration()
        if pos is not None and dur:
            self.store.set_progress(self._current_file, pos, dur)
        self.store.save()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._tick_timer.stop()
        self.settings.volume = self.volume_slider.value()
        geo = self.geometry()
        self.settings.window = {
            "x": geo.x(),
            "y": geo.y(),
            "w": geo.width(),
            "h": geo.height(),
            "maximized": self.isMaximized(),
        }
        self.settings.playlist_mode = self.playlist.mode.value
        self.settings.save()
        self._save_progress_now()
        self._stop_transcriber()
        self.video_area.mpv_widget.shutdown()
        self.playback.terminate()
        super().closeEvent(event)
