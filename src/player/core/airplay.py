"""macOS AirPlay route picker and AVPlayer bridge."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from player.core.playlist import VIDEO_EXTENSIONS

DIRECT_SUFFIXES = {".mp4", ".m4v", ".mov"}


def can_airplay(path: Path) -> bool:
    """Whether a video can be sent directly or remuxed without re-encoding."""
    return path.suffix.lower() in VIDEO_EXTENSIONS


def remux_to_mp4(source_path: Path, output_path: Path) -> None:
    """Repackage video/audio streams into MP4 without changing the codecs."""
    import av

    with av.open(str(source_path)) as source:
        with av.open(str(output_path), mode="w", format="mp4") as output:
            streams = [stream for stream in source.streams if stream.type in ("video", "audio")]
            if not any(stream.type == "video" for stream in streams):
                raise ValueError("文件中没有可投屏的视频轨道")
            mapping = {stream.index: output.add_stream_from_template(stream) for stream in streams}
            for packet in source.demux(streams):
                if packet.dts is None:
                    continue
                packet.stream = mapping[packet.stream.index]
                output.mux(packet)


class _RemuxSignals(QObject):
    finished = Signal(int, object, object, object)


class _RemuxJob(QRunnable):
    def __init__(self, generation: int, source: Path):
        super().__init__()
        self.generation = generation
        self.source = source
        self.signals = _RemuxSignals()

    def run(self) -> None:
        fd, name = tempfile.mkstemp(prefix="yingxu-airplay-", suffix=".mp4")
        os.close(fd)
        output = Path(name)
        try:
            remux_to_mp4(self.source, output)
        except Exception as exc:
            output.unlink(missing_ok=True)
            self.signals.finished.emit(self.generation, self.source, None, str(exc))
        else:
            self.signals.finished.emit(self.generation, self.source, output, None)


class AirPlayButton(QWidget):
    """Host Apple's native route picker inside a Qt control-bar slot."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setToolTip("投屏到 AirPlay 设备")
        self.setAccessibleName("投屏到 AirPlay 设备")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._picker = None
        self._native_view = None

    def bind(self, player) -> None:
        self._ensure_picker()
        if self._picker is not None:
            self._picker.setPlayer_(player)

    def _ensure_picker(self) -> None:
        if self._picker is not None or sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            return
        import objc
        from AppKit import NSViewHeightSizable, NSViewWidthSizable
        from AVKit import AVRoutePickerView

        self._native_view = objc.objc_object(c_void_p=int(self.winId()))
        self._picker = AVRoutePickerView.alloc().initWithFrame_(self._native_view.bounds())
        self._picker.setRoutePickerButtonBordered_(False)
        self._picker.setPrioritizesVideoDevices_(True)
        self._picker.setRoutePickerButtonRemainsHighlightedWhileRoutesPresented_(True)
        self._picker.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self._native_view.addSubview_(self._picker)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._picker is not None:
            self._picker.setFrame_(self._native_view.bounds())


class AirPlaySession(QObject):
    """AVPlayer state used only while an AirPlay route is active."""

    remux_finished = Signal(object, object)
    picker_opened = Signal()
    picker_closed = Signal()

    def __init__(self, button: AirPlayButton):
        super().__init__()
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            raise RuntimeError("AirPlay is available on macOS only")
        from AVFoundation import AVPlayer, AVPlayerItem

        self.button = button
        self._AVPlayerItem = AVPlayerItem
        self.player = AVPlayer.alloc().init()
        self.player.setAllowsExternalPlayback_(True)
        self.player.setAllowsAirPlayVideo_(True)
        button.bind(self.player)
        self._pool = QThreadPool.globalInstance()
        self._generation = 0
        self._source_path: Path | None = None
        self._prepared_path: Path | None = None
        self._pending_position = 0.0
        self._load_error: str | None = None
        self._closed = False
        self.remux_finished.connect(self._on_remux_finished)
        self._install_picker_delegate(button)

    def _install_picker_delegate(self, button: AirPlayButton) -> None:
        """Start muted playback while the route menu is open; AirPlay needs an active item."""
        import objc
        from Foundation import NSObject

        session = self

        class RoutePickerDelegate(NSObject):
            @objc.typedSelector(b"v@:@")
            def routePickerViewWillBeginPresentingRoutes_(self, picker):
                session.picker_opened.emit()

            @objc.typedSelector(b"v@:@")
            def routePickerViewDidEndPresentingRoutes_(self, picker):
                session.picker_closed.emit()

        self._picker_delegate = RoutePickerDelegate.alloc().init()
        if button._picker is not None:
            button._picker.setDelegate_(self._picker_delegate)

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self, path: Path, position: float = 0.0) -> str:
        """Load a directly playable file, or asynchronously remux its streams.

        Returns ``ready``, ``preparing``, or ``unsupported``.
        """
        self._generation += 1
        generation = self._generation
        self._clear_item()
        self._source_path = path
        self._pending_position = max(0.0, position)
        self._load_error = None
        if not can_airplay(path):
            self._source_path = None
            return "unsupported"
        if path.suffix.lower() in DIRECT_SUFFIXES:
            self._replace_with_file(path, position)
            return "ready" if self.is_ready() else "preparing"

        job = _RemuxJob(generation, path)
        job.signals.finished.connect(self.remux_finished.emit)
        self._pool.start(job)
        return "preparing"

    def _on_remux_finished(self, generation: int, source: Path, output: Path | None, error: str | None):
        if self._closed or generation != self._generation or source != self._source_path:
            if output is not None:
                Path(output).unlink(missing_ok=True)
            return
        if error is not None or output is None:
            self._load_error = error or "媒体文件无法转换为 AirPlay 格式"
            return
        self._prepared_path = Path(output)
        self._replace_with_file(self._prepared_path, self._pending_position)

    def _replace_with_file(self, path: Path, position: float) -> None:
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(str(path.resolve()))
        item = self._AVPlayerItem.playerItemWithURL_(url)
        self.player.replaceCurrentItemWithPlayerItem_(item)
        self.seek(position)
        self.player.pause()

    def _clear_item(self) -> None:
        self.player.pause()
        self.player.replaceCurrentItemWithPlayerItem_(None)
        if self._prepared_path is not None:
            self._prepared_path.unlink(missing_ok=True)
            self._prepared_path = None

    def is_ready(self) -> bool:
        item = self.player.currentItem()
        return item is not None and int(item.status()) == 1  # AVPlayerItemStatusReadyToPlay

    def item_failed(self) -> bool:
        item = self.player.currentItem()
        return item is not None and int(item.status()) == 2

    def item_error(self) -> str:
        item = self.player.currentItem()
        if item is None or item.error() is None:
            return self._load_error or "AVPlayer 无法播放此编码"
        return str(item.error().localizedDescription())

    def is_active(self) -> bool:
        try:
            return bool(self.player.isExternalPlaybackActive())
        except (AttributeError, TypeError):
            return bool(self.player.externalPlaybackActive())

    def position(self) -> float | None:
        from CoreMedia import CMTimeGetSeconds

        seconds = float(CMTimeGetSeconds(self.player.currentTime()))
        return seconds if seconds >= 0 else None

    def duration(self) -> float | None:
        from CoreMedia import CMTimeGetSeconds

        item = self.player.currentItem()
        if item is None:
            return None
        seconds = float(CMTimeGetSeconds(item.duration()))
        return seconds if seconds >= 0 else None

    def seek(self, seconds: float) -> None:
        from CoreMedia import CMTimeMakeWithSeconds

        self.player.seekToTime_(CMTimeMakeWithSeconds(max(0.0, seconds), 600))

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.player.pause()
        else:
            self.player.play()

    def set_volume(self, volume: int) -> None:
        self.player.setVolume_(min(1.0, max(0.0, volume / 100.0)))

    def set_speed(self, speed: float) -> None:
        paused = self.player.rate() == 0
        self.player.setRate_(float(speed))
        if paused:
            self.player.pause()

    def close(self) -> None:
        self._closed = True
        self._generation += 1
        self._clear_item()
        self.button.bind(None)
