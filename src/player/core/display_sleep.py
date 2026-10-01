"""Keep the display awake while video is actively playing on macOS."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

_CF_STRING_ENCODING_UTF8 = 0x08000100
_IOPM_ASSERTION_LEVEL_ON = 255
_DISPLAY_SLEEP_ASSERTION = "PreventUserIdleDisplaySleep"


class _MacOSDisplaySleepAssertion:
    def __init__(self) -> None:
        self._core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self._iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        self._core_foundation.CFStringCreateWithCString.argtypes = (
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        )
        self._core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
        self._core_foundation.CFRelease.argtypes = (ctypes.c_void_p,)
        self._create_assertion = self._iokit.IOPMAssertionCreateWithName
        self._create_assertion.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        )
        self._create_assertion.restype = ctypes.c_int32
        self._release_assertion = self._iokit.IOPMAssertionRelease
        self._release_assertion.argtypes = (ctypes.c_uint32,)
        self._release_assertion.restype = ctypes.c_int32
        self._allocator = ctypes.c_void_p.in_dll(self._core_foundation, "kCFAllocatorDefault").value
        self._assertion_id: int | None = None

    def _make_string(self, value: str) -> ctypes.c_void_p:
        result = self._core_foundation.CFStringCreateWithCString(
            self._allocator,
            value.encode("utf-8"),
            _CF_STRING_ENCODING_UTF8,
        )
        if not result:
            raise RuntimeError("CFStringCreateWithCString failed")
        return result

    def acquire(self) -> bool:
        assertion_type = self._make_string(_DISPLAY_SLEEP_ASSERTION)
        reason = self._make_string("Yingxu video playback")
        try:
            assertion_id = ctypes.c_uint32()
            status = self._create_assertion(
                assertion_type,
                _IOPM_ASSERTION_LEVEL_ON,
                reason,
                ctypes.byref(assertion_id),
            )
            if status != 0:
                return False
            self._assertion_id = assertion_id.value
            return True
        finally:
            self._core_foundation.CFRelease(assertion_type)
            self._core_foundation.CFRelease(reason)

    def release(self) -> None:
        if self._assertion_id is None:
            return
        assertion_id, self._assertion_id = self._assertion_id, None
        self._release_assertion(assertion_id)


class DisplaySleepInhibitor:
    """Idempotently hold and release a platform display-sleep assertion."""

    def __init__(self, backend=None, backend_factory: Callable[[], object] | None = None) -> None:
        self._backend = backend
        self._backend_factory = backend_factory or self._create_backend
        self._inhibited = False

    @staticmethod
    def _create_backend():
        if sys.platform != "darwin":
            return None
        try:
            return _MacOSDisplaySleepAssertion()
        except (AttributeError, OSError, RuntimeError):
            return None

    @property
    def inhibited(self) -> bool:
        return self._inhibited

    def set_playing_video(self, playing: bool) -> None:
        if playing == self._inhibited:
            return
        if playing:
            if self._backend is None:
                self._backend = self._backend_factory()
            if self._backend is not None:
                self._inhibited = self._backend.acquire()
        else:
            if self._backend is not None:
                self._backend.release()
            self._inhibited = False

    def close(self) -> None:
        self.set_playing_video(False)
