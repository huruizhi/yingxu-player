"""macOS AirPlay route picker and AVPlayer bridge.

AVRoutePickerView only routes AVFoundation players. The app keeps mpv as its
normal playback engine and uses this small bridge while the user is casting.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

AIRPLAY_SUFFIXES = {".mp4", ".m4v", ".mov"}


def can_airplay(path: Path) -> bool:
    """Common AVFoundation movie containers supported for direct casting."""
    return path.suffix.lower() in AIRPLAY_SUFFIXES


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


class AirPlaySession:
    """AVPlayer state used only while an AirPlay route is active."""

    def __init__(self, button: AirPlayButton):
        if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
            raise RuntimeError("AirPlay is available on macOS only")
        from AVFoundation import AVPlayer, AVPlayerItem

        self.button = button
        self._AVPlayerItem = AVPlayerItem
        self.player = AVPlayer.alloc().init()
        self.player.setAllowsExternalPlayback_(True)
        self.player.setAllowsAirPlayVideo_(True)
        button.bind(self.player)
        self._path: Path | None = None

    def load(self, path: Path, position: float = 0.0) -> bool:
        if not can_airplay(path):
            self._path = None
            self.player.replaceCurrentItemWithPlayerItem_(None)
            return False
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(str(path.resolve()))
        item = self._AVPlayerItem.playerItemWithURL_(url)
        self.player.replaceCurrentItemWithPlayerItem_(item)
        self._path = path
        self.seek(position)
        self.player.pause()
        return True

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
        self.player.pause()
        self.player.replaceCurrentItemWithPlayerItem_(None)
        self.button.bind(None)
