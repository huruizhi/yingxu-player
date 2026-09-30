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

OBSERVED_PROPERTIES = ("time-pos", "duration", "pause", "eof-reached", "track-list", "path")


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


class PlaybackError(RuntimeError):
    pass


class Playback(QObject):
    """播放器封装：加载、播放控制、轨道选择、属性信号。"""

    position_changed = Signal(float)
    duration_changed = Signal(float)
    paused_changed = Signal(bool)
    file_changed = Signal(str)
    tracks_changed = Signal()
    end_reached = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        try:
            patch_find_library()  # Homebrew libmpv 不在 ctypes 默认搜索路径
            import mpv as mpv_module
        except (ImportError, OSError) as exc:  # libmpv 缺失时 OSError
            raise PlaybackError("无法加载 libmpv，请先执行 `brew install mpv`") from exc

        self._mpv_module = mpv_module
        self._eof = False
        self._tracks: list[Track] = []
        try:
            self._mpv = mpv_module.MPV(
                vo="libmpv",  # 画面交给渲染上下文，不建独立窗口
                hwdec="auto-safe",  # macOS 上自动启用 VideoToolbox 硬解
                keep_open="yes",  # 播到结尾停在最后一帧，由应用决定连播
                idle="yes",
                osc=False,  # 使用自绘控制栏
                audio_display="no",
                input_vo_keyboard=False,
                loglevel="warn",
                log_handler=self._log,
            )
        except Exception as exc:
            raise PlaybackError(f"初始化 libmpv 失败：{exc}") from exc

        self._mpv.observe_property("time-pos", self._on_time_pos)
        self._mpv.observe_property("duration", self._on_duration)
        self._mpv.observe_property("pause", self._on_pause)
        self._mpv.observe_property("eof-reached", self._on_eof)
        self._mpv.observe_property("track-list", self._on_track_list)
        self._mpv.observe_property("path", self._on_path)

    # ---- 生命周期 ----

    @property
    def mpv_instance(self):
        """渲染控件用于创建 MpvRenderContext 的底层实例。"""
        return self._mpv

    def terminate(self) -> None:
        try:
            self._mpv.terminate()
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

    # ---- 加载与基础控制 ----

    def load(self, path: Path) -> None:
        """加载文件并开始播放。"""
        self._eof = False
        self._mpv.command("loadfile", str(path), "replace")
        self._mpv.set_property("pause", False)

    def stop(self) -> None:
        self._mpv.command("stop")

    def play(self) -> None:
        self._mpv.set_property("pause", False)

    def pause(self) -> None:
        self._mpv.set_property("pause", True)

    def toggle_play(self) -> None:
        try:
            self._mpv.set_property("pause", not bool(self._mpv.pause))
        except Exception:
            pass

    def seek_relative(self, seconds: float) -> None:
        self._try(lambda: self._mpv.command("seek", seconds, "relative"))

    def seek_absolute(self, seconds: float, exact: bool = True) -> None:
        flag = "absolute+exact" if exact else "absolute"
        self._try(lambda: self._mpv.command("seek", seconds, flag))

    def set_volume(self, volume: int) -> None:
        self._mpv.set_property("volume", int(min(130, max(0, volume))))

    def set_speed(self, speed: float) -> None:
        self._try(lambda: self._mpv.set_property("speed", float(speed)))

    # ---- 状态查询 ----

    def position(self) -> float | None:
        try:
            value = self._mpv.time_pos
        except Exception:
            return None
        return float(value) if value is not None else None

    def duration(self) -> float | None:
        try:
            value = self._mpv.duration
        except Exception:
            return None
        return float(value) if value is not None else None

    def is_paused(self) -> bool:
        try:
            return bool(self._mpv.pause)
        except Exception:
            return True

    def media_title(self) -> str:
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
        self._try(lambda: self._mpv.set_property("aid", int(track_id)))

    def select_sub_track(self, track_id: int | None) -> None:
        """选择内置字幕轨；None 表示隐藏全部内置字幕（AI 字幕接管）。"""
        value = "no" if track_id is None else int(track_id)
        self._try(lambda: self._mpv.set_property("sid", value))

    def reset_sub_track_auto(self) -> None:
        """恢复 mpv 对内置字幕轨的自动选择。"""
        self._try(lambda: self._mpv.set_property("sid", "auto"))

    # ---- 内部 ----

    @staticmethod
    def _try(fn) -> None:
        """mpv 属性/命令在无文件等情形下会抛错；静默忽略，状态由属性观察纠偏。"""
        try:
            fn()
        except Exception:
            pass
