"""libmpv 播放适配层。

将 mpv 属性/命令封装为面向 UI 的接口。mpv 的属性回调发生在其内部事件线程，
经 Qt 信号（跨线程自动排队）送达主线程，UI 层无需关心线程问题。
播放内核由此模块唯一封装，必要时可整体替换。

渲染说明：mpv 以 vo=libmpv 模式创建，画面由 ui/mpv_widget.py 借助
MpvRenderContext 绘制进 QOpenGLWidget，本模块不负责渲染。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from player.core.libmpv import patch_find_library

OBSERVED_PROPERTIES = ("time-pos", "duration", "pause", "eof-reached", "track-list", "path", "chapter-list")

# 属性名 → 本类对应的回调方法名；__init__ 注册、terminate 注销共用同一份映射
_OBSERVERS = {
    "time-pos": "_on_time_pos",
    "duration": "_on_duration",
    "pause": "_on_pause",
    "eof-reached": "_on_eof",
    "track-list": "_on_track_list",
    "path": "_on_path",
    "chapter-list": "_on_chapter_list",
}

ASPECT_PRESETS = ("4:3", "16:9", "1.85:1", "2.35:1")
ROTATE_STEPS = (0, 90, 180, 270)
ZOOM_MIN = -1.0
ZOOM_MAX = 3.0


@dataclass(frozen=True)
class Track:
    """音轨/字幕轨/视频轨信息。"""

    id: int
    type: str  # "audio" / "sub" / "video"
    title: str = ""
    lang: str = ""
    codec: str = ""
    default: bool = False
    selected: bool = False


@dataclass(frozen=True)
class Chapter:
    """文件内嵌章节。index 从 0 计数，time 为章节起点（秒）。"""

    index: int
    title: str = ""
    time: float = 0.0


class PlaybackError(RuntimeError):
    pass


class Playback(QObject):
    """播放器封装：加载、播放控制、轨道选择、属性信号。"""

    position_changed = Signal(float)
    duration_changed = Signal(float)
    paused_changed = Signal(bool)
    file_changed = Signal(str)
    tracks_changed = Signal()
    chapters_changed = Signal()
    end_reached = Signal()

    def __init__(
        self, parent: QObject | None = None, video_out: str = "libmpv", audio_out: str | None = None
    ):
        super().__init__(parent)
        try:
            patch_find_library()  # Homebrew libmpv 不在 ctypes 默认搜索路径
            import mpv as mpv_module
        except (ImportError, OSError) as exc:  # libmpv 缺失时 OSError
            raise PlaybackError("无法加载 libmpv，请先执行 `brew install mpv`") from exc

        self._mpv_module = mpv_module
        self._eof = False
        self._tracks: list[Track] = []
        self._chapters: list[Chapter] = []
        options = dict(
            vo=video_out,  # libmpv=画面交给渲染上下文；null 供无渲染测试
            hwdec="auto-safe",  # macOS 上自动启用 VideoToolbox 硬解
            keep_open="yes",  # 播到结尾停在最后一帧，由应用决定连播
            stop_screensaver="yes",  # 播放视频时阻止屏幕保护程序启动
            idle="yes",
            osc=False,  # 使用自绘控制栏
            audio_display="no",
            input_vo_keyboard=False,
            loglevel="warn",
            log_handler=self._log,
        )
        if audio_out is not None:
            options["ao"] = audio_out  # 测试环境禁用真实音频设备，避免 CI 上的资源竞争
        try:
            self._mpv = mpv_module.MPV(**options)
        except Exception as exc:
            raise PlaybackError(f"初始化 libmpv 失败：{exc}") from exc

        for name, handler_name in _OBSERVERS.items():
            self._mpv.observe_property(name, getattr(self, handler_name))

    # ---- 生命周期 ----

    @property
    def mpv_instance(self):
        """渲染控件用于创建 MpvRenderContext 的底层实例。"""
        return self._mpv

    def terminate(self) -> None:
        """销毁 mpv 句柄；幂等，重复调用安全。

        先注销全部属性观察器再 terminate：mpv 销毁期间事件线程仍可能投递
        属性事件，回调进入已进入销毁流程的实例会放大底层库的销毁竞争。
        """
        mpv = getattr(self, "_mpv", None)
        self._mpv = None
        if mpv is None:
            return
        for name, handler_name in _OBSERVERS.items():
            try:
                mpv.unobserve_property(name, getattr(self, handler_name))
            except Exception:
                pass
        try:
            mpv.terminate()
        except Exception:
            pass

    @staticmethod
    def _log(level: str, prefix: str, text: str) -> None:
        if level in ("warn", "error", "fatal"):
            print(f"[mpv/{level}] {prefix}: {text}", file=sys.stderr)

    # ---- mpv 回调（mpv 事件线程）----

    def _on_time_pos(self, _name: str, value: float | None) -> None:
        if value is not None:
            self.position_changed.emit(float(value))

    def _on_duration(self, _name: str, value: float | None) -> None:
        if value is not None:
            self.duration_changed.emit(float(value))

    def _on_pause(self, _name: str, value: bool | None) -> None:
        if value is not None:
            self.paused_changed.emit(bool(value))

    def _on_eof(self, _name: str, value: bool | None) -> None:
        if value and not self._eof:
            self._eof = True
            self.end_reached.emit()

    def _on_track_list(self, _name: str, value) -> None:
        tracks: list[Track] = []
        for entry in value or []:
            if not isinstance(entry, dict):
                continue
            tracks.append(
                Track(
                    id=int(entry.get("id", 0)),
                    type=str(entry.get("type", "")),
                    title=str(entry.get("title") or ""),
                    lang=str(entry.get("lang") or ""),
                    codec=str(entry.get("codec") or ""),
                    default=bool(entry.get("default")),
                    selected=bool(entry.get("selected")),
                )
            )
        self._tracks = tracks
        self.tracks_changed.emit()

    def _on_path(self, _name: str, value: str | None) -> None:
        if value:
            self.file_changed.emit(value)

    def _on_chapter_list(self, _name: str, value) -> None:
        chapters: list[Chapter] = []
        for index, entry in enumerate(value or []):
            if not isinstance(entry, dict):
                continue
            try:
                time = float(entry.get("time") or 0.0)
            except (TypeError, ValueError):
                continue
            chapters.append(Chapter(index=index, title=str(entry.get("title") or ""), time=time))
        self._chapters = chapters
        self.chapters_changed.emit()

    # ---- 加载与基础控制 ----

    def _alive(self) -> bool:
        return self._mpv is not None

    def load(self, path: Path) -> None:
        """加载文件并开始播放；换文件时清掉画面/同步类调整（策略见 README）。"""
        if not self._alive():
            return
        self._eof = False
        self._mpv.command("loadfile", str(path), "replace")
        self._reset_per_file_props()
        self._set_prop("pause", False)

    def _reset_per_file_props(self) -> None:
        for name, value in (
            ("sub-delay", 0.0),
            ("audio-delay", 0.0),
            ("ab-loop-a", "no"),
            ("ab-loop-b", "no"),
            ("video-zoom", 0.0),
            ("video-rotate", 0),
            ("video-aspect-override", "no"),
        ):
            self._set_prop(name, value)

    def stop(self) -> None:
        if self._alive():
            self._mpv.command("stop")

    def play(self) -> None:
        self._set_prop("pause", False)

    def pause(self) -> None:
        self._set_prop("pause", True)

    def toggle_play(self) -> None:
        self._set_prop("pause", not self.is_paused())

    def seek_relative(self, seconds: float) -> None:
        self._try(lambda: self._mpv.command("seek", seconds, "relative"))

    def seek_absolute(self, seconds: float, exact: bool = True) -> None:
        flag = "absolute+exact" if exact else "absolute"
        self._try(lambda: self._mpv.command("seek", seconds, flag))

    def set_volume(self, volume: int) -> None:
        self._set_prop("volume", int(min(130, max(0, volume))))

    def set_speed(self, speed: float) -> None:
        self._set_prop("speed", float(speed))

    # ---- 状态查询 ----

    def position(self) -> float | None:
        if self._mpv is None:
            return None
        try:
            value = self._mpv.time_pos
        except Exception:
            return None
        return float(value) if value is not None else None

    def duration(self) -> float | None:
        if self._mpv is None:
            return None
        try:
            value = self._mpv.duration
        except Exception:
            return None
        return float(value) if value is not None else None

    def is_paused(self) -> bool:
        if self._mpv is None:
            return True
        try:
            return bool(self._mpv.pause)
        except Exception:
            return True

    def media_title(self) -> str:
        if self._mpv is None:
            return ""
        try:
            return str(self._mpv.media_title or "")
        except Exception:
            return ""

    def tracks(self, track_type: str | None = None) -> list[Track]:
        if track_type is None:
            return list(self._tracks)
        return [t for t in self._tracks if t.type == track_type]

    def audio_tracks(self) -> list[Track]:
        return self.tracks("audio")

    def sub_tracks(self) -> list[Track]:
        return self.tracks("sub")

    # ---- 轨道选择 ----

    def select_audio_track(self, track_id: int) -> None:
        self._set_prop("aid", int(track_id))

    def select_sub_track(self, track_id: int | None) -> None:
        """选择内置字幕轨；None 表示隐藏全部内置字幕（AI 字幕接管）。"""
        self._set_prop("sid", "no" if track_id is None else int(track_id))

    def reset_sub_track_auto(self) -> None:
        """恢复 mpv 对内置字幕轨的自动选择。"""
        self._set_prop("sid", "auto")

    # ---- 截图 ----

    def screenshot_to_file(self, path: Path) -> bool:
        """把当前帧（含叠显字幕）写入 PNG；无画面或渲染失败时返回 False。"""
        if not self._alive():
            return False
        try:
            self._mpv.command("screenshot-to-file", str(path))
            return True
        except Exception:
            return False

    # ---- 音画同步 ----

    def sub_delay(self) -> float:
        """字幕相对播放位置的偏移（秒，正=延后）。"""
        return self._float_prop("sub-delay")

    def set_sub_delay(self, seconds: float) -> None:
        self._set_prop("sub-delay", round(float(seconds), 3))

    def audio_delay(self) -> float:
        """音频相对视频的偏移（秒，正=音频延后）。"""
        return self._float_prop("audio-delay")

    def set_audio_delay(self, seconds: float) -> None:
        self._set_prop("audio-delay", round(float(seconds), 3))

    # ---- 画面调整 ----

    def set_aspect_override(self, value: str | None) -> None:
        """强制画面比例；None 恢复跟随视频。"""
        self._set_prop("video-aspect-override", value if value else "no")

    def video_zoom(self) -> float:
        return self._float_prop("video-zoom")

    def adjust_video_zoom(self, delta: float) -> float:
        """在当前缩放上叠加 delta（log2 尺度），返回调整后的值。"""
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.video_zoom() + delta))
        self._set_prop("video-zoom", round(zoom, 4))
        return zoom

    def reset_video_zoom(self) -> None:
        self._set_prop("video-zoom", 0.0)

    def set_video_rotate(self, degrees: int) -> None:
        if degrees not in ROTATE_STEPS:
            raise ValueError(f"unsupported rotation: {degrees}")
        self._set_prop("video-rotate", degrees)

    def video_size(self) -> tuple[int, int] | None:
        width = self._int_prop("width")
        height = self._int_prop("height")
        if width and height:
            return width, height
        return None

    # ---- AB 循环 ----

    def set_ab_loop(self, a: float | None, b: float | None) -> None:
        """设置 A/B 循环点；两点齐全后由 mpv 自动往复。None 表示清除。"""
        self._set_prop("ab-loop-a", "no" if a is None else round(float(a), 3))
        self._set_prop("ab-loop-b", "no" if b is None else round(float(b), 3))

    def ab_loop(self) -> tuple[float | None, float | None]:
        return self._time_or_none(self._get_prop("ab-loop-a")), self._time_or_none(
            self._get_prop("ab-loop-b")
        )

    # ---- 章节 ----

    def chapters(self) -> list[Chapter]:
        return list(self._chapters)

    def current_chapter(self) -> int | None:
        value = self._int_prop("chapter")
        return value if value is not None and value >= 0 else None

    def select_chapter(self, index: int) -> None:
        self._set_prop("chapter", int(index))

    # ---- 内部 ----

    def _set_prop(self, name: str, value) -> None:
        """经 `set` 命令写属性：mpv 以字符串解析，兼容 int/float/bool/choice。"""
        if not self._alive():
            return
        text = "yes" if value is True else "no" if value is False else str(value)
        self._try(lambda: self._mpv.command("set", name, text))

    def _get_prop(self, name: str, default=None):
        """属性读取。走 MPV 的动态属性接口（python-mpv 的属性访问路径），
        覆盖 chapter/width 等纯属性；选项同名属性同样可读。"""
        if not self._alive():
            return default
        try:
            return getattr(self._mpv, name.replace("-", "_"))
        except Exception:
            return default

    def _float_prop(self, name: str) -> float:
        value = self._get_prop(name)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _int_prop(self, name: str) -> int | None:
        value = self._get_prop(name)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _time_or_none(value) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _try(fn) -> None:
        """mpv 属性/命令在无文件等情形下会抛错；静默忽略，状态由属性观察纠偏。"""
        try:
            fn()
        except Exception:
            pass
