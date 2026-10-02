"""主窗口：组装播放内核、播放列表、AI 字幕、片尾跳过与全部交互。

UI v3：视频全幅铺满，字幕、进度与播放控制收在统一的底部悬浮面板；
播放中鼠标静止自动隐藏；全屏共用同一套逻辑。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMenu, QMessageBox, QToolButton

from player import __version__
from player.ai.skip import CreditsSkipper
from player.ai.subtitles import SubtitleStore
from player.ai.transcriber import Transcriber
from player.ai.whisper_backend import WhisperBackend
from player.core.airplay import AirPlaySession, can_airplay
from player.core.display_sleep import DisplaySleepInhibitor
from player.core.playback import ASPECT_PRESETS, ROTATE_STEPS, Playback
from player.core.playlist import VIDEO_EXTENSIONS, LoopMode, Playlist, scan_media_files
from player.core.settings import AI_MODELS, Settings, SubtitleSource
from player.core.store import Store
from player.ui.icons import icon
from player.ui.overlay_visibility import AutoHideController
from player.ui.video_area import VideoArea
from player.updates import LATEST_RELEASE_API, is_newer_version

_TICK_MS = 250
_PROGRESS_SAVE_TICKS = 20  # ~5 秒落盘一次
_SYNC_STEP = 0.1  # 音画同步/字幕偏移步长（秒）
_ZOOM_STEP = 0.1  # log2 尺度，约 ±7% 面积
_PIP_HEIGHT = 270
_PIP_MARGIN = 24


def _fmt_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class MainWindow(QMainWindow):
    transcriber_status = Signal(str)  # 转写线程状态 → 顶栏徽标（跨线程封送）

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
        self._airplay: AirPlaySession | None = None
        self._airplay_active = False
        self._airplay_was_playing = False
        self._display_sleep_inhibitor = DisplaySleepInhibitor()
        self._stt: WhisperBackend | None = None
        self._stt_model_size: str | None = None
        self._transcriber: Transcriber | None = None
        self._transcriber_generation = 0

        self._current_file: Path | None = None
        self._ai_active = False
        self._ai_override: bool | None = None  # 本次播放的手动开关覆盖
        self._subtitles_loaded_from_cache = False
        self._pending_resume: float | None = None
        self._tick_count = 0
        self._auto_hide = AutoHideController()
        self._update_manager = QNetworkAccessManager(self)
        self._update_reply: QNetworkReply | None = None
        self._update_manual = False
        self._update_notice: QMessageBox | None = None

        # 会话内观看调整（换文件时重置，不落盘）
        self._aspect_override: str | None = None  # None=跟随视频
        self._video_rotate = 0
        self._ab_a: float | None = None
        self._ab_b: float | None = None
        self._pip_active = False
        self._pip_restore: dict | None = None

        self.setWindowTitle("映序")
        self.setAcceptDrops(True)
        self._build_ui()
        try:
            self._airplay = AirPlaySession(self.video_area.control_bar.airplay_btn)
            self._airplay.picker_opened.connect(self._on_airplay_picker_opened)
            self._airplay.picker_closed.connect(self._on_airplay_picker_closed)
        except (ImportError, RuntimeError, AttributeError) as exc:
            self.video_area.control_bar.airplay_btn.hide()
            print(f"[airplay] unavailable: {exc}")
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
        self.setCentralWidget(self.video_area)

        # 悬浮控件别名（保持既有逻辑可读）
        bar = self.video_area.control_bar
        self.prev_btn = bar.prev_btn
        self.play_btn = bar.play_btn
        self.next_btn = bar.next_btn
        self.volume_slider = bar.volume_slider
        self.speed_btn = bar.speed_btn
        self.subtitle_btn = bar.subtitle_btn
        self.skip_btn = bar.skip_btn
        self.playlist_btn = bar.playlist_btn
        self.timeline = self.video_area.timeline
        self.playlist_panel = self.video_area.drawer.panel
        self.volume_slider.setValue(self.settings.volume)
        self.video_area.empty_state.open_file.connect(self._open_file_dialog)
        self.video_area.empty_state.open_directory.connect(self._open_dir_dialog)
        self.video_area.empty_state.open_recent_directory.connect(lambda path: self.open_path(Path(path)))
        self._refresh_recent_directories()
        self.video_area.set_empty_state(True)
        self.video_area.control_bar.set_paused(self.playback.is_paused())

    def _build_menus(self) -> None:
        menu = self.menuBar()

        # 文件
        m_file = menu.addMenu("文件")
        self.act_open = QAction("打开文件…", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open_dir = QAction("打开目录…", self)
        self.act_open_dir.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self._recent_dirs_menu = QMenu("最近打开的目录", self)
        self._recent_dirs_menu.aboutToShow.connect(self._refresh_recent_directories)
        self.act_export = QAction("导出 AI 字幕 (.srt)…", self)
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        self.act_screenshot = QAction("截图", self)
        self.act_screenshot.setShortcut(QKeySequence("S"))
        self.act_screenshot.triggered.connect(self._take_screenshot)
        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        for a in (self.act_open, self.act_open_dir, self.act_export, self.act_screenshot):
            m_file.addAction(a)
        m_file.addMenu(self._recent_dirs_menu)
        self._refresh_recent_directories()
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
        m_play.addSeparator()

        # 章节
        self._chapter_menu = m_play.addMenu("章节")
        self._chapter_menu.aboutToShow.connect(self._rebuild_chapter_menu)
        self.act_prev_chapter = QAction("上一章", self)
        self.act_prev_chapter.setShortcut(QKeySequence("Alt+Left"))
        self.act_prev_chapter.triggered.connect(lambda: self._jump_chapter(-1))
        self.act_next_chapter = QAction("下一章", self)
        self.act_next_chapter.setShortcut(QKeySequence("Alt+Right"))
        self.act_next_chapter.triggered.connect(lambda: self._jump_chapter(+1))
        self._chapter_menu.addAction(self.act_prev_chapter)
        self._chapter_menu.addAction(self.act_next_chapter)
        self._chapter_menu.addSeparator()

        # AB 循环：同一动作在 设A → 设B → 清除 间循环
        self.act_ab_loop = QAction("标记 AB 循环起点 (L)", self)
        self.act_ab_loop.setShortcut(QKeySequence("L"))
        self.act_ab_loop.triggered.connect(self._cycle_ab_loop)
        m_play.addAction(self.act_ab_loop)

        # 画面：比例/缩放/旋转
        self._picture_menu = m_play.addMenu("画面")
        self._aspect_menu = self._picture_menu.addMenu("比例")
        self._aspect_group = QActionGroup(self._aspect_menu)
        self._aspect_actions: dict[str | None, QAction] = {}
        for value, label in ((None, "跟随视频"), *((v, v) for v in ASPECT_PRESETS)):
            act = QAction(label, self, checkable=True)
            act.setChecked(value is None)
            act.triggered.connect(lambda _c, v=value: self._set_aspect_override(v))
            self._aspect_group.addAction(act)
            self._aspect_actions[value] = act
            self._aspect_menu.addAction(act)
        self.act_zoom_in = QAction("放大", self)
        self.act_zoom_in.setShortcut(QKeySequence("+"))
        self.act_zoom_in.triggered.connect(lambda: self._adjust_zoom(+_ZOOM_STEP))
        self.act_zoom_out = QAction("缩小", self)
        self.act_zoom_out.setShortcut(QKeySequence("-"))
        self.act_zoom_out.triggered.connect(lambda: self._adjust_zoom(-_ZOOM_STEP))
        self.act_zoom_reset = QAction("重置缩放", self)
        self.act_zoom_reset.triggered.connect(self._reset_zoom)
        self._picture_menu.addAction(self.act_zoom_in)
        self._picture_menu.addAction(self.act_zoom_out)
        self._picture_menu.addAction(self.act_zoom_reset)
        self._rotate_menu = self._picture_menu.addMenu("旋转")
        self._rotate_group = QActionGroup(self._rotate_menu)
        self._rotate_actions: dict[int, QAction] = {}
        for degrees in ROTATE_STEPS:
            act = QAction(f"{degrees}°" if degrees else "0°（正常）", self, checkable=True)
            act.setChecked(degrees == 0)
            act.triggered.connect(lambda _c, d=degrees: self._set_video_rotate(d))
            self._rotate_group.addAction(act)
            self._rotate_actions[degrees] = act
            self._rotate_menu.addAction(act)
        self.act_picture_reset = QAction("重置画面调整", self)
        self.act_picture_reset.triggered.connect(self._reset_picture)
        self._picture_menu.addSeparator()
        self._picture_menu.addAction(self.act_picture_reset)

        # 同步：音频/字幕偏移
        self._sync_menu = m_play.addMenu("同步")
        for label, slot in (
            ("音频提前 0.1 秒", lambda: self._adjust_audio_delay(-_SYNC_STEP)),
            ("音频延后 0.1 秒", lambda: self._adjust_audio_delay(+_SYNC_STEP)),
            ("重置音频偏移", lambda: self._adjust_audio_delay(0)),
        ):
            act = QAction(label, self)
            act.triggered.connect(slot)
            self._sync_menu.addAction(act)
        self.act_audio_early, self.act_audio_late = self._sync_menu.actions()[:2]
        self.act_audio_early.setShortcut(QKeySequence("["))
        self.act_audio_late.setShortcut(QKeySequence("]"))
        self._sync_menu.addSeparator()
        for label, slot in (
            ("字幕提前 0.1 秒", lambda: self._adjust_sub_delay(-_SYNC_STEP)),
            ("字幕延后 0.1 秒", lambda: self._adjust_sub_delay(+_SYNC_STEP)),
            ("重置字幕偏移", lambda: self._adjust_sub_delay(0)),
        ):
            act = QAction(label, self)
            act.triggered.connect(slot)
            self._sync_menu.addAction(act)
        # actions() 序列：音频×3、分隔线、字幕×3 → 下标 4/5 是字幕提前/延后
        self.act_sub_early, self.act_sub_late = self._sync_menu.actions()[4:6]
        self.act_sub_early.setShortcut(QKeySequence("Z"))
        self.act_sub_late.setShortcut(QKeySequence("X"))

        m_play.addSeparator()
        self.act_topmost = QAction("窗口置顶", self, checkable=True)
        self.act_topmost.setShortcut(QKeySequence("Ctrl+T"))
        # triggered 而非 toggled：避免程序性 setChecked（画中画切换）反向触发窗口操作
        self.act_topmost.triggered.connect(lambda: self._set_topmost(self.act_topmost.isChecked()))
        m_play.addAction(self.act_topmost)
        self.act_pip = QAction("画中画", self)
        self.act_pip.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.act_pip.triggered.connect(self._toggle_pip)
        m_play.addAction(self.act_pip)
        m_play.addSeparator()
        self.act_fullscreen = QAction("进入全屏", self)
        self.act_fullscreen.setShortcut(QKeySequence("F"))
        self.act_fullscreen.triggered.connect(self.toggle_fullscreen)
        m_play.addAction(self.act_fullscreen)

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

        m_help = menu.addMenu("帮助")
        act_updates = QAction("检查更新…", self)
        act_updates.triggered.connect(lambda: self.check_for_updates(manual=True))
        m_help.addAction(act_updates)

    def check_for_updates(self, manual: bool = False) -> None:
        """Check GitHub Releases without blocking video playback."""
        if self._update_reply is not None:
            self._update_manual = self._update_manual or manual
            return
        self._update_settings = QSettings()
        last_checked = self._update_settings.value("updates/last_checked", 0, type=int)
        now = int(time.time())
        if not manual and now - last_checked < 24 * 60 * 60:
            return
        request = QNetworkRequest(QUrl(LATEST_RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", b"Yingxu-Player")
        request.setTransferTimeout(5000)
        self._update_manual = manual
        self._update_started_at = now
        self._update_reply = self._update_manager.get(request)
        self._update_reply.finished.connect(self._on_update_check_finished)

    def _on_update_check_finished(self) -> None:
        reply = self._update_reply
        if reply is None:
            return
        self._update_reply = None
        manual = self._update_manual
        self._update_manual = False
        if reply.error() != QNetworkReply.NoError:
            message = reply.errorString()
            reply.deleteLater()
            if manual:
                QMessageBox.warning(self, "检查更新失败", f"暂时无法连接 GitHub：\n{message}")
            return

        try:
            release = json.loads(bytes(reply.readAll()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            release = {}
        self._update_settings.setValue("updates/last_checked", self._update_started_at)
        reply.deleteLater()

        latest = str(release.get("tag_name", ""))
        release_url = str(release.get("html_url", ""))
        if is_newer_version(latest, __version__) and release_url.startswith("https://github.com/"):
            self._show_update_notice(latest, release_url)
        elif manual:
            QMessageBox.information(self, "检查更新", f"当前已是最新版本（{__version__}）。")

    def _show_update_notice(self, version: str, release_url: str) -> None:
        if self._update_notice is not None and self._update_notice.isVisible():
            return
        notice = QMessageBox(self)
        notice.setIcon(QMessageBox.Information)
        notice.setWindowTitle("发现新版本")
        notice.setText(f"映序 {version} 已发布")
        notice.setInformativeText(f"当前版本：{__version__}\n查看更新说明并下载最新版本。")
        download_button = notice.addButton("前往下载", QMessageBox.AcceptRole)
        notice.addButton("稍后", QMessageBox.RejectRole)
        notice.setWindowModality(Qt.NonModal)
        notice.setAttribute(Qt.WA_DeleteOnClose, True)
        notice.destroyed.connect(lambda: setattr(self, "_update_notice", None))
        notice.buttonClicked.connect(
            lambda button: QDesktopServices.openUrl(QUrl(release_url)) if button == download_button else None
        )
        self._update_notice = notice
        notice.open()

    def _build_shortcuts(self) -> None:
        def bind(seq: str, slot) -> None:
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)

        bind("Space", self._toggle_playback)
        bind("Left", lambda: self._seek_and_feedback(-10))
        bind("Right", lambda: self._seek_and_feedback(+10))
        bind("Up", lambda: self._change_volume(+5))
        bind("Down", lambda: self._change_volume(-5))
        bind("Ctrl+L", self._toggle_playlist)
        bind("Ctrl+S", self.skipper.manual_skip)
        bind("A", self._cycle_aspect_override)
        bind("R", self._cycle_rotate)
        bind("Escape", self._exit_fullscreen_if_needed)

        self.prev_btn.clicked.connect(lambda: self._play_sibling(-1))
        self.next_btn.clicked.connect(lambda: self._play_sibling(+1))
        self.act_prev.triggered.connect(lambda: self._play_sibling(-1))
        self.act_next.triggered.connect(lambda: self._play_sibling(+1))
        self.play_btn.clicked.connect(self._toggle_playback)
        self.subtitle_btn.clicked.connect(self._toggle_ai_manual)
        self.skip_btn.clicked.connect(self.skipper.manual_skip)
        self.act_mark.triggered.connect(self._mark_credits)
        self.act_clear_mark.triggered.connect(self._clear_credits)
        self.playlist_btn.clicked.connect(self._toggle_playlist)
        self.video_area.control_bar.pip_btn.clicked.connect(self._toggle_pip)
        self.video_area.drawer.visibility_changed.connect(self.playlist_btn.setChecked)
        self.video_area.control_bar.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        self.act_open.triggered.connect(self._open_file_dialog)
        self.act_open_dir.triggered.connect(self._open_dir_dialog)
        self.act_export.triggered.connect(self._export_srt)
        self.playlist_panel.item_activated.connect(self.play_path)
        self.skipper.enabled = self.settings.skip_credits_enabled

        # 视频区交互：单击暂停/播放，双击全屏
        self.video_area.single_clicked.connect(self._toggle_playback)
        self.video_area.double_clicked.connect(self.toggle_fullscreen)
        self.video_area.mouse_activity.connect(self._on_mouse_activity)
        self.video_area.scrub_started.connect(self._auto_hide.force_show)
        self.video_area.scrub_finished.connect(self._on_scrub_finished)

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
        self.playback.chapters_changed.connect(self._on_chapters_changed)
        self.playback.end_reached.connect(self._on_end_reached)
        self.playback.file_changed.connect(self._on_file_changed)

        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.transcriber_status.connect(self._on_transcriber_status)

    def _restore_window(self) -> None:
        geo = self.settings.window or {}
        if geo.get("w") and geo.get("h"):
            self.resize(int(geo["w"]), int(geo["h"]))
            if geo.get("x") is not None and geo.get("y") is not None:
                self.move(int(geo["x"]), int(geo["y"]))
            if geo.get("maximized"):
                self.showMaximized()
        else:
            self.resize(1120, 700)

    # ================= 显隐与全屏 =================

    def _on_mouse_activity(self) -> None:
        self._auto_hide.activity()
        self._apply_controls_visibility()

    def _apply_controls_visibility(self) -> None:
        shown = self._auto_hide.shown
        self.video_area.set_controls_shown(shown)
        if self.isFullScreen() and not shown:
            self.video_area.setCursor(Qt.BlankCursor)
        else:
            self.video_area.unsetCursor()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            if self._pip_active:
                self._exit_pip()
            self.showFullScreen()
        fullscreen = self.isFullScreen()
        self.video_area.set_fullscreen(fullscreen)
        self.act_fullscreen.setText("退出全屏" if fullscreen else "进入全屏")
        self.video_area.control_bar.fullscreen_btn.setIcon(
            icon("exit_fullscreen" if fullscreen else "fullscreen")
        )
        self.video_area.control_bar.fullscreen_btn.setToolTip("退出全屏 (F)" if fullscreen else "全屏 (F)")
        self._auto_hide.force_show()
        self._apply_controls_visibility()

    def _exit_fullscreen_if_needed(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()
        elif self._pip_active:
            self._exit_pip()

    # ================= 打开与播放 =================

    def open_path(self, path: Path) -> None:
        """打开文件或目录：文件自动带起同目录播放列表。"""
        path = Path(path).expanduser()
        if path.is_dir():
            files = scan_media_files(path)
            if not files:
                self.video_area.show_osd("该目录没有可播放的媒体文件")
                return
            self.playlist.load_directory(path)
            self._refresh_playlist_panel()
            self._remember_directory(path)
            self.play_path(files[0])
            return
        if not path.is_file():
            self.video_area.show_osd(f"文件不存在：{path}")
            return
        if not self.playlist.items or path.parent != self.playlist.items[0].parent:
            self.playlist.load_directory(path.parent, start_file=path)
            self._refresh_playlist_panel()
        else:
            self.playlist.jump_to_path(path)
            self._refresh_playlist_panel()
        self._remember_directory(path.parent)
        self.play_path(path)

    def _available_recent_directories(self) -> list[str]:
        return [path for path in self.settings.recent_directories if Path(path).is_dir()]

    def _refresh_recent_directories(self) -> None:
        directories = self._available_recent_directories()
        self.video_area.empty_state.set_recent_directories(directories)
        if not hasattr(self, "_recent_dirs_menu"):
            return
        self._recent_dirs_menu.clear()
        for directory in directories:
            path = Path(directory)
            action = self._recent_dirs_menu.addAction(f"{path.name or directory}  ·  {path.parent}")
            action.setToolTip(directory)
            action.triggered.connect(lambda _checked=False, value=directory: self.open_path(Path(value)))
        self._recent_dirs_menu.setEnabled(bool(directories))

    def _remember_directory(self, directory: Path) -> None:
        self.settings.remember_directory(directory)
        self.settings.save()
        self._refresh_recent_directories()

    def play_path(self, path: Path) -> None:
        path = Path(path)
        self._stop_transcriber()
        self._save_progress_now()
        self._current_file = path
        self._ai_override = None
        self._reset_per_file_adjustments()
        self._pending_resume = self.store.get_progress(path)
        self._subtitles_loaded_from_cache = False
        self.video_area.set_empty_state(False)
        self.video_area.set_media_title(path.name)
        self.video_area.control_bar.airplay_btn.hide()

        self.subtitles.clear_runtime()
        self.video_area.timeline.set_covered([])
        self.skipper.on_file_opened(path)
        airplay_state = "unsupported"
        if self._airplay is not None:
            airplay_state = self._airplay.load(path, self._pending_resume or 0.0)
        if self._airplay_active and airplay_state != "ready":
            self._airplay_active = False
            self.video_area.status_chip.set_status(None)
            self._airplay.set_paused(True)
            self.video_area.show_osd("正在准备新视频，电视投屏已断开；准备好后可重新连接")
        self.playback.load(path)
        if self._airplay_active:
            self.playback.pause()
            self._airplay.set_volume(self.settings.volume)
            self._airplay.set_speed(self.settings.speed)
            self._airplay.set_paused(False)

        self.setWindowTitle(f"{path.name} — 映序")
        self.video_area.status_chip.set_status(None)
        if self.playlist.items:
            self.playlist.jump_to_path(path)  # 文件在列表中时同步当前项
        self.playlist_panel.highlight_current(self.playlist.current_item)
        self._update_skip_ui()
        self._auto_hide.force_show()
        self._apply_controls_visibility()
        if self._pending_resume:
            self.video_area.show_osd(f"已恢复到上次进度 {_fmt_time(self._pending_resume)}")

    def handle_secondary_launch(self, path: str | None) -> None:
        """Show this window and handle a file-open request from another launch."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        if path:
            self.open_path(Path(path))

    def _play_sibling(self, direction: int) -> None:
        nxt = self.playlist.next() if direction > 0 else self.playlist.previous()
        if nxt is not None:
            self.play_path(nxt)
        else:
            self.video_area.show_osd("播放列表为空")

    def _advance_to_next(self) -> None:
        """片尾跳过/自然播完时的自动连播入口。"""
        nxt = self.playlist.next(auto=True)
        if nxt is not None:
            self.play_path(nxt)
        elif self._current_file is not None:
            self._display_sleep_inhibitor.close()
            self.video_area.show_osd("播放结束")

    # ================= 播放回调 =================

    def _on_file_changed(self, path: str) -> None:
        if not self._current_file or Path(path) != self._current_file.resolve():
            self._current_file = Path(path)
        self._sync_display_sleep_inhibitor()
        self.video_area.control_bar.set_paused(self.playback.is_paused())
        # 载入时轨道信息尚未就绪，先按"无内置字幕"预应用一次；
        # track-list 事件到达后 _on_tracks_changed 会再校正
        self._apply_subtitle_policy()

    def _toggle_playback(self) -> None:
        if self._airplay_active and self._airplay is not None:
            should_play = self._airplay.player.rate() == 0
            self._airplay_was_playing = should_play
            self._airplay.set_paused(not should_play)
            self.video_area.control_bar.set_paused(not should_play)
            self._sync_display_sleep_inhibitor()
            return
        self.playback.toggle_play()

    def _current_position(self) -> float | None:
        if self._airplay_active and self._airplay is not None:
            return self._airplay.position()
        return self.playback.position()

    def _current_duration(self) -> float | None:
        if self._airplay_active and self._airplay is not None:
            return self._airplay.duration() or self.playback.duration()
        return self.playback.duration()

    def _sync_airplay_route(self) -> None:
        if self._airplay is None:
            return
        active = self._airplay.is_active()
        if active == self._airplay_active:
            return
        if active:
            position = self.playback.position() or 0.0
            self._airplay_was_playing = not self.playback.is_paused()
            self._airplay.seek(position)
            self._airplay.set_volume(self.settings.volume)
            self._airplay.set_speed(self.settings.speed)
            self._airplay_active = True
            self.playback.pause()
            self._airplay.set_paused(not self._airplay_was_playing)
            self.video_area.status_chip.set_status("AirPlay 已连接")
            if self._ai_active or self.playback.sub_tracks():
                self.video_area.show_osd("已投屏。AI 字幕与播放器内字幕不会传到电视。")
            else:
                self.video_area.show_osd("已连接 AirPlay")
        else:
            position = self._airplay.position()
            if position is not None:
                self.playback.seek_absolute(position, exact=False)
            was_playing = self._airplay_was_playing
            self._airplay_active = False
            self._airplay.set_paused(True)
            if was_playing:
                self.playback.play()
            self.video_area.status_chip.set_status(None)
            self.video_area.show_osd("已断开 AirPlay，继续在本机播放")
        self._sync_display_sleep_inhibitor()

    def _on_airplay_picker_opened(self) -> None:
        if self._airplay is None or not self._airplay.is_ready() or self._airplay_active:
            return
        self._airplay_was_playing = not self.playback.is_paused()
        self._airplay.seek(self.playback.position() or 0.0)
        self._airplay.set_speed(self.settings.speed)
        # AVPlayer does not establish an external video route until playback starts.
        # Keep it muted until the route is confirmed, so local playback remains audible.
        self._airplay.set_volume(0)
        self._airplay.set_paused(False)

    def _on_airplay_picker_closed(self) -> None:
        if self._airplay is None or self._airplay_active:
            return
        QTimer.singleShot(300, self._stop_unrouted_airplay_probe)

    def _stop_unrouted_airplay_probe(self) -> None:
        if self._airplay is None or self._airplay_active or self._airplay.is_active():
            return
        self._airplay.set_paused(True)
        self._airplay.set_volume(self.settings.volume)

    def _on_paused_changed(self, paused: bool) -> None:
        if self._airplay_active and self._airplay is not None:
            self.video_area.control_bar.set_paused(self._airplay.player.rate() == 0)
        else:
            self.video_area.control_bar.set_paused(paused)
        self._auto_hide.force_show()  # 暂停时控制层保持可见
        self._apply_controls_visibility()
        self._sync_display_sleep_inhibitor()

    def _sync_display_sleep_inhibitor(self) -> None:
        playing_video = (
            self._current_file is not None
            and self._current_file.suffix.lower() in VIDEO_EXTENSIONS
            and (
                (self._airplay_active and self._airplay is not None and self._airplay.player.rate() != 0)
                or (not self._airplay_active and not self.playback.is_paused())
            )
        )
        self._display_sleep_inhibitor.set_playing_video(playing_video)

    def _on_duration_changed(self, duration: float) -> None:
        self.timeline.set_position(self.playback.position() or 0.0, duration)
        if self._pending_resume and duration > 0:
            pos, self._pending_resume = self._pending_resume, None
            if pos < duration - 5:
                self.playback.seek_absolute(pos, exact=False)
                if self._airplay is not None:
                    self._airplay.seek(pos)
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
        wanted = mode is SubtitleSource.FORCE_AI or (mode is SubtitleSource.AUTO and not has_embedded)
        if self._ai_override is not None:
            wanted = self._ai_override
        if wanted:
            self.playback.select_sub_track(None)  # AI 接管时隐藏内置字幕，避免重叠
        else:
            self.playback.reset_sub_track_auto()
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
            self.video_area.timeline.set_covered([])
            self.video_area.set_subtitle_text(None)
            self.video_area.status_chip.set_status(None)

    def _toggle_ai_manual(self) -> None:
        self._ai_override = not self._ai_active
        self._apply_subtitle_policy()
        self.video_area.show_osd("AI 字幕：开启" if self._ai_override else "AI 字幕：关闭")

    def _start_ai_transcription(self) -> None:
        if self._current_file is None:
            return
        duration = self.playback.duration() or 0.0
        cache_profile = self._subtitle_cache_profile()
        if self.subtitles.try_load_cache(self._current_file, duration, cache_profile):
            self._subtitles_loaded_from_cache = True
            self.video_area.status_chip.set_status("AI 字幕：缓存")
            self.video_area.timeline.set_covered(self.subtitles.covered.ranges())
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
            self.video_area.status_chip.set_status("无音频轨")
            return
        generation = self._transcriber_generation
        self._transcriber = Transcriber(
            self._stt,
            decoder,
            self.subtitles,
            self._current_file,
            duration,
            on_status=lambda text: self._emit_transcriber_status(generation, text),
            cache_profile=cache_profile,
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

    def _stop_transcriber(self, wait_timeout: float = 0.0) -> None:
        self._transcriber_generation += 1
        if self._transcriber is not None:
            self._transcriber.stop(timeout=wait_timeout)
            self._transcriber = None

    def _emit_transcriber_status(self, generation: int, text: str) -> None:
        if generation == self._transcriber_generation:
            self.transcriber_status.emit(text)

    def _on_transcriber_status(self, text: str) -> None:
        if "转写中" in text or "追赶" in text or "下载" in text or "加载" in text:
            self.video_area.status_chip.set_status(text)
        elif text == "字幕已就绪":
            self.video_area.status_chip.set_status("AI 字幕：就绪")
        elif "失败" in text or "出错" in text:
            self.video_area.status_chip.set_status("AI 字幕：出错")
            self.video_area.show_osd(text)

    def _set_subtitle_source(self, source: SubtitleSource) -> None:
        self.settings.subtitle_source = source
        self._ai_override = None
        self._apply_subtitle_policy()

    def _set_ai_model(self, size: str) -> None:
        self.settings.ai_model = size
        self._restart_ai_for_profile_change()

    def _set_ai_language(self, lang: str) -> None:
        self.settings.ai_language = lang
        self._restart_ai_for_profile_change()

    def _subtitle_cache_profile(self) -> str:
        return f"{self.settings.ai_model}:{self.settings.ai_language}"

    def _restart_ai_for_profile_change(self) -> None:
        if not self._ai_active:
            return
        self._stop_transcriber()
        self.subtitles.clear_runtime()
        self._subtitles_loaded_from_cache = False
        self._stt = None
        self._stt_model_size = None
        self._start_ai_transcription()

    def _export_srt(self) -> None:
        if self._current_file is None or not self.subtitles.all_segments():
            self.video_area.show_osd("当前文件还没有可导出的 AI 字幕")
            return
        dest = self.subtitles.export_srt(self._current_file)
        self.video_area.show_osd(f"AI 字幕已导出：{dest.name}")

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

    # ================= 观看调整：换文件重置 =================

    def _reset_per_file_adjustments(self) -> None:
        """与 Playback.load() 的属性重置保持一致的 UI 状态。"""
        self._aspect_override = None
        self._video_rotate = 0
        self._ab_a = None
        self._ab_b = None
        self._apply_ab_loop()
        self._sync_picture_menus()
        self.timeline.set_chapters([])

    def _sync_picture_menus(self) -> None:
        for value, act in self._aspect_actions.items():
            act.setChecked(value == self._aspect_override)
        for degrees, act in self._rotate_actions.items():
            act.setChecked(degrees == self._video_rotate)

    # ================= 截图 =================

    def _screenshot_directory(self) -> Path:
        return Path.home() / "Pictures" / "映序"

    def _take_screenshot(self) -> None:
        if self._current_file is None:
            self.video_area.show_osd("先打开视频才能截图")
            return
        if not self.playback.tracks("video"):
            self.video_area.show_osd("音频文件没有画面，无法截图")
            return
        directory = self._screenshot_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.video_area.show_osd(f"无法创建截图目录：{exc}")
            return
        stem = self._current_file.stem
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = directory / f"{stem} {stamp}.png"
        counter = 2
        while path.exists():
            path = directory / f"{stem} {stamp}-{counter}.png"
            counter += 1
        if self.playback.screenshot_to_file(path):
            self.video_area.show_osd(f"已保存截图：{path.name}")
        else:
            self.video_area.show_osd("截图失败")

    # ================= 音画同步 =================

    def _adjust_sub_delay(self, delta: float) -> None:
        value = 0.0 if delta == 0 else round(self.playback.sub_delay() + delta, 3)
        self.playback.set_sub_delay(value)
        self.video_area.show_osd("字幕偏移已重置" if value == 0 else f"字幕偏移 {value:+.1f}s")

    def _adjust_audio_delay(self, delta: float) -> None:
        value = 0.0 if delta == 0 else round(self.playback.audio_delay() + delta, 3)
        self.playback.set_audio_delay(value)
        self.video_area.show_osd("音频偏移已重置" if value == 0 else f"音频偏移 {value:+.1f}s")

    # ================= 画面调整 =================

    def _set_aspect_override(self, value: str | None) -> None:
        self._aspect_override = value
        self.playback.set_aspect_override(value)
        self._sync_picture_menus()
        self.video_area.show_osd("画面比例：跟随视频" if value is None else f"画面比例 {value}")

    def _cycle_aspect_override(self) -> None:
        order: list[str | None] = [None, *ASPECT_PRESETS]
        try:
            index = order.index(self._aspect_override)
        except ValueError:
            index = 0
        self._set_aspect_override(order[(index + 1) % len(order)])

    def _set_video_rotate(self, degrees: int) -> None:
        self._video_rotate = degrees
        self.playback.set_video_rotate(degrees)
        self._sync_picture_menus()
        self.video_area.show_osd("画面旋转已重置" if degrees == 0 else f"画面旋转 {degrees}°")

    def _cycle_rotate(self) -> None:
        index = ROTATE_STEPS.index(self._video_rotate) if self._video_rotate in ROTATE_STEPS else 0
        self._set_video_rotate(ROTATE_STEPS[(index + 1) % len(ROTATE_STEPS)])

    def _adjust_zoom(self, delta: float) -> None:
        zoom = self.playback.adjust_video_zoom(delta)
        self.video_area.show_osd(f"画面缩放 {round(2**zoom * 100)}%")

    def _reset_zoom(self) -> None:
        self.playback.reset_video_zoom()
        self.video_area.show_osd("画面缩放 100%")

    def _reset_picture(self) -> None:
        self._aspect_override = None
        self._video_rotate = 0
        self.playback.set_aspect_override(None)
        self.playback.reset_video_zoom()
        self.playback.set_video_rotate(0)
        self._sync_picture_menus()
        self.video_area.show_osd("画面调整已重置")

    # ================= AB 循环 =================

    def _cycle_ab_loop(self) -> None:
        if self._ab_a is None:
            position = self._current_position()
            if position is None:
                self.video_area.show_osd("先打开视频再使用 AB 循环")
                return
            self._ab_a = position
            self._apply_ab_loop()
            self.video_area.show_osd(f"已标记 A 点 {_fmt_time(position)}")
            return
        if self._ab_b is None:
            position = self._current_position()
            if position is None:
                return
            if position <= self._ab_a:
                self.video_area.show_osd("B 点需要晚于 A 点")
                return
            self._ab_b = position
            self._apply_ab_loop()
            self.video_area.show_osd(f"AB 循环 {_fmt_time(self._ab_a)} – {_fmt_time(self._ab_b)}")
            return
        self._ab_a = None
        self._ab_b = None
        self._apply_ab_loop()
        self.video_area.show_osd("已清除 AB 循环")

    def _apply_ab_loop(self) -> None:
        self.playback.set_ab_loop(self._ab_a, self._ab_b)
        self.timeline.set_loop_range(self._ab_a, self._ab_b)
        if self._ab_a is None:
            self.act_ab_loop.setText("标记 AB 循环起点 (L)")
        elif self._ab_b is None:
            self.act_ab_loop.setText("标记 AB 循环终点 (L)")
        else:
            self.act_ab_loop.setText("清除 AB 循环 (L)")

    # ================= 章节 =================

    def _on_chapters_changed(self) -> None:
        self.timeline.set_chapters([chapter.time for chapter in self.playback.chapters()])

    def _rebuild_chapter_menu(self) -> None:
        # 前 3 项（上一章/下一章/分隔线）固定，仅重建其后的章节列表
        while len(self._chapter_menu.actions()) > 3:
            self._chapter_menu.removeAction(self._chapter_menu.actions()[3])
        chapters = self.playback.chapters()
        if not chapters:
            empty = QAction("（无章节信息）", self._chapter_menu)
            empty.setEnabled(False)
            self._chapter_menu.addAction(empty)
            return
        current = self.playback.current_chapter()
        for chapter in chapters:
            title = chapter.title or f"章节 {chapter.index + 1}"
            act = QAction(
                f"{chapter.index + 1}. {title}  {_fmt_time(chapter.time)}", self._chapter_menu, checkable=True
            )
            act.setChecked(chapter.index == current)
            act.triggered.connect(lambda _c, i=chapter.index: self._select_chapter(i))
            self._chapter_menu.addAction(act)

    def _select_chapter(self, index: int) -> None:
        chapters = self.playback.chapters()
        if not 0 <= index < len(chapters):
            return
        self.playback.select_chapter(index)
        title = chapters[index].title or f"章节 {index + 1}"
        self.video_area.show_osd(f"章节 {index + 1}/{len(chapters)}：{title}")

    def _jump_chapter(self, delta: int) -> None:
        chapters = self.playback.chapters()
        current = self.playback.current_chapter()
        if not chapters or current is None:
            self.video_area.show_osd("该文件没有章节信息")
            return
        target = min(len(chapters) - 1, max(0, current + delta))
        self._select_chapter(target)

    # ================= 窗口置顶与画中画 =================

    def _set_topmost(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()
        self.video_area.show_osd("窗口置顶：开" if on else "窗口置顶：关")

    def _toggle_pip(self) -> None:
        if self._pip_active:
            self._exit_pip()
        else:
            self._enter_pip()

    def _pip_target_size(self) -> tuple[int, int]:
        size = self.playback.video_size()
        ratio = size[0] / size[1] if size and size[1] else 16 / 9
        height = _PIP_HEIGHT
        return max(320, int(height * ratio)), height

    def _enter_pip(self) -> None:
        if self._current_file is None:
            self.video_area.show_osd("先打开视频再使用画中画")
            return
        was_maximized = self.isMaximized()
        self._pip_restore = {
            "geometry": self.geometry(),
            "maximized": was_maximized,
            "topmost": self.act_topmost.isChecked(),
        }
        if self.isFullScreen():
            self.showNormal()
        width, height = self._pip_target_size()
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        width = min(width, available.width() - 2 * _PIP_MARGIN)
        height = min(height, available.height() - 2 * _PIP_MARGIN)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.act_topmost.setChecked(True)
        self.video_area.hide_playlist()
        if was_maximized:
            self.showNormal()
        self.resize(width, height)
        self.move(available.right() - width - _PIP_MARGIN, available.bottom() - height - _PIP_MARGIN)
        self.show()
        self._pip_active = True
        self.act_pip.setText("退出画中画")
        self.video_area.control_bar.set_pip_active(True)
        self._auto_hide.force_show()
        self._apply_controls_visibility()
        self.video_area.show_osd("已进入画中画（Esc 或再次点击退出）")

    def _exit_pip(self) -> None:
        restore = self._pip_restore or {}
        self._pip_restore = None
        self._pip_active = False
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(restore.get("topmost")))
        self.act_topmost.setChecked(bool(restore.get("topmost")))
        self.act_pip.setText("画中画")
        self.video_area.control_bar.set_pip_active(False)
        geometry = restore.get("geometry")
        if restore.get("maximized"):
            self.showMaximized()
        elif geometry is not None:
            self.setGeometry(geometry)
        else:
            self.resize(1120, 700)
        self.show()
        self._auto_hide.force_show()
        self._apply_controls_visibility()
        self.video_area.show_osd("已退出画中画")

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
        self.video_area.show_osd(f"已标记片尾起点 {_fmt_time(pos)}（对同目录文件同样生效）")

    def _clear_credits(self) -> None:
        if self._current_file is None:
            return
        if self.store.clear_credits(self._current_file):
            self.skipper.on_file_opened(self._current_file)
            self._update_skip_ui()
            self.video_area.show_osd("已清除片尾标记")

    def _toggle_skip_enabled(self, checked: bool) -> None:
        self.settings.skip_credits_enabled = checked
        self.skipper.enabled = checked
        self._update_skip_ui()
        self.video_area.show_osd("自动跳过片尾：开" if checked else "自动跳过片尾：关")

    def _update_skip_ui(self) -> None:
        has_mark = self._current_file is not None and self.skipper.has_mark()
        self.skip_btn.setEnabled(True)
        self.skip_btn.setToolTip(
            "跳过片尾 (Ctrl+S)" + ("" if has_mark else "（本目录未标记片尾，将直接跳到下一集）")
        )

    # ================= 控件联动 =================

    def _on_tick(self) -> None:
        self._sync_airplay_availability()
        self._sync_airplay_route()
        pos = self._current_position()
        duration = self._current_duration()
        if pos is not None:
            self.timeline.set_position(pos, duration or 0.0)
            if self._airplay is not None and not self._airplay_active:
                airplay_pos = self._airplay.position()
                if airplay_pos is None or abs(airplay_pos - pos) > 1.5:
                    self._airplay.seek(pos)
            if self._transcriber is not None:
                self._transcriber.notify_position(pos)
                self.video_area.timeline.set_covered(self.subtitles.covered.ranges())

        # 自动隐藏判定：悬停控制层视为活动，保持显示
        if self.video_area.cursor_over_controls():
            self._auto_hide.activity()
        elif self._auto_hide.tick(
            paused=(self._airplay.player.rate() == 0 if self._airplay_active else self.playback.is_paused()),
            fullscreen=self.isFullScreen(),
        ):
            self._apply_controls_visibility()

        if self._current_file is None or pos is None:
            return

        self._tick_count += 1
        seg = self.subtitles.current(pos)
        self.video_area.set_subtitle_text(seg.text if seg else None)
        self.skipper.on_position(pos)
        if self._tick_count % _PROGRESS_SAVE_TICKS == 0 and duration:
            self.store.set_progress(self._current_file, pos, duration)
            self.store.save()

    def _sync_airplay_availability(self) -> None:
        if self._airplay is None or self._current_file is None:
            return
        button = self.video_area.control_bar.airplay_btn
        if self._airplay.source_path != self._current_file or not can_airplay(self._current_file):
            button.hide()
            return
        if self._airplay.item_failed() or self._airplay.load_error:
            button.hide()
            return
        ready = self._airplay.is_ready()
        # isVisible() also becomes false when the auto-hidden control bar is hidden.
        # Track the button's own visibility so background readiness stays silent.
        if button.isHidden() == ready:
            button.setVisible(ready)

    def _on_scrub_finished(self, seconds: float) -> None:
        self.playback.seek_absolute(seconds, exact=False)
        if self._airplay is not None:
            self._airplay.seek(seconds)
        self._auto_hide.force_show()
        self._apply_controls_visibility()

    def _seek_and_feedback(self, delta: float) -> None:
        self.playback.seek_relative(delta)
        if self._airplay_active and self._airplay is not None:
            self._airplay.seek((self._airplay.position() or 0.0) + delta)
        self._auto_hide.force_show()
        self._apply_controls_visibility()

    def _on_volume_changed(self, value: int) -> None:
        self.settings.volume = value
        self.playback.set_volume(value)
        if self._airplay is not None:
            self._airplay.set_volume(value)
        self.video_area.show_osd(f"音量 {min(value, 100)}%{'+' if value > 100 else ''}")

    def _change_volume(self, delta: int) -> None:
        self.volume_slider.setValue(self.volume_slider.value() + delta)

    def _set_speed(self, speed: float) -> None:
        self.settings.speed = speed
        self.playback.set_speed(speed)
        if self._airplay is not None:
            self._airplay.set_speed(speed)
        self.speed_btn.setText(f"{speed:g}x")
        self.video_area.show_osd(f"倍速 {speed:g}x")
        for act in self.speed_menu.actions():
            act.setChecked(abs(float(act.text().rstrip("x")) - speed) < 1e-6)

    def _set_loop_mode(self, mode: LoopMode) -> None:
        self.playlist.set_mode(mode)
        self.settings.playlist_mode = mode.value

    def _toggle_playlist(self) -> None:
        self.video_area.toggle_playlist()

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
            self, "打开媒体文件", self._dialog_start_directory(), f"媒体文件 ({exts});;所有文件 (*)"
        )
        if path:
            self.open_path(Path(path))

    def _open_dir_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "打开目录", self._dialog_start_directory())
        if path:
            self.open_path(Path(path))

    def _dialog_start_directory(self) -> str:
        directories = self._available_recent_directories()
        return directories[0] if directories else str(Path.home())

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
            self.video_area.show_osd("没有可播放的媒体文件")

    # ================= 关闭与清理 =================

    def _save_progress_now(self) -> None:
        if self._current_file is None:
            return
        pos = self._current_position()
        dur = self._current_duration()
        if pos is not None and dur:
            self.store.set_progress(self._current_file, pos, dur)
        self.store.save()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._tick_timer.stop()
        self.settings.volume = self.volume_slider.value()
        if self.isFullScreen():
            self.showNormal()
        if self._pip_active and self._pip_restore is not None:
            geo = self._pip_restore["geometry"]
            maximized = bool(self._pip_restore.get("maximized"))
        else:
            geo = self.geometry()
            maximized = self.isMaximized()
        self.settings.window = {
            "x": geo.x(),
            "y": geo.y(),
            "w": geo.width(),
            "h": geo.height(),
            "maximized": maximized,
        }
        self.settings.playlist_mode = self.playlist.mode.value
        self.settings.save()
        self._save_progress_now()
        self._stop_transcriber(wait_timeout=8.0)
        self._display_sleep_inhibitor.close()
        if self._airplay is not None:
            self._airplay.close()
        self.video_area.mpv_widget.shutdown()
        self.playback.terminate()
        super().closeEvent(event)
