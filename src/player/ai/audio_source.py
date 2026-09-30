"""PyAV 音频解码：媒体文件 → 16kHz 单声道 float32 PCM，按需分块读取（可 seek）。

供 AI 转写独立于播放管线取音频：不依赖系统混音器，静音播放也能生成字幕。
read/close 线程安全（内部加锁），保证调度器 stop 时与工作线程的解码不竞态。
"""

from __future__ import annotations

import threading
from pathlib import Path

import av
import numpy as np

SAMPLE_RATE = 16000

try:  # PyAV 14+ 基类为 FFmpegError，旧版叫 AVError
    from av.error import FFmpegError as _FFmpegError
except ImportError:  # pragma: no cover
    from av.error import AVError as _FFmpegError


class AudioDecodeError(RuntimeError):
    pass


class AudioDecoder:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._closed = False
        try:
            self._container = av.open(str(path))
        except _FFmpegError as exc:
            raise AudioDecodeError(f"无法打开媒体文件：{exc}") from exc
        try:
            self._stream = next(s for s in self._container.streams.audio)
        except StopIteration as exc:
            self._container.close()
            raise AudioDecodeError("该文件没有音频轨，无法生成 AI 字幕") from exc
        self._stream.thread_type = "AUTO"

    # ---- 查询 ----

    def duration(self) -> float:
        with self._lock:
            if self._closed:
                return 0.0
            if self._stream.duration is not None and self._stream.time_base:
                return float(self._stream.duration * self._stream.time_base)
            if self._container.duration is not None:
                return float(self._container.duration / av.time_base)
            return 0.0

    # ---- 读取 ----

    def read(self, start: float, max_seconds: float) -> np.ndarray:
        """解码 [start, start+max_seconds) 的音频。

        seek 尽量精准；返回长度略短于请求值表示已到文件结尾。
        """
        start = max(0.0, float(start))
        max_seconds = max(0.0, float(max_seconds))
        end = start + max_seconds
        total = int(round(max_seconds * SAMPLE_RATE))
        if total == 0:
            return np.zeros(0, dtype=np.float32)

        with self._lock:
            if self._closed:
                raise AudioDecodeError("解码器已关闭")
            return self._read_locked(start, end, total)

    def _read_locked(self, start: float, end: float, total: int) -> np.ndarray:
        tb = self._stream.time_base or av.time_base
        try:
            self._container.seek(int(round(start / tb)), stream=self._stream)
        except _FFmpegError:
            self._container.seek(0, stream=self._stream)  # 兜底：从头解码

        # 每次读取重建重采样器，避免上一块的残留样本串入
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        out = np.zeros(total, dtype=np.float32)

        for frame in self._container.decode(self._stream):
            if frame.pts is not None:
                frame_start = float(frame.pts * tb)
            else:
                frame_start = start  # 个别容器 seek 后无 pts，按目标起点近似
            frame_dur = frame.samples / float(frame.rate) if frame.rate else 0.0
            if frame_start + frame_dur <= start:
                continue
            if frame_start >= end:
                break

            for rf in resampler.resample(frame):
                arr = rf.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
                if arr.size == 0:
                    continue
                offset = int(round((frame_start - start) * SAMPLE_RATE))
                dst0 = max(0, offset)
                src0 = max(0, -offset)
                n = min(arr.size - src0, total - dst0)
                if n > 0:
                    out[dst0 : dst0 + n] = arr[src0 : src0 + n]
            if frame_start + frame_dur >= end:
                break
        return out

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._container.close()
            except Exception:
                pass
