"""领先播放进度的后台转写调度器。

策略：后台线程持续把播放位置之后 LOOKAHEAD 秒窗口内的未转写区间转写掉，
使字幕"追平并领先"播放进度——观感即实时。领先窗口没有欠账后，转写全文件
剩余部分（低优先），完成即写缓存。用户 seek 后位置重定锚，自动改转新区域。

纯 Python 线程实现；通过回调上报状态（UI 层自行封送线程）。
"""

from __future__ import annotations

import threading
from pathlib import Path

from player.ai.audio_source import AudioDecoder
from player.ai.base import STTBackend
from player.ai.subtitles import SubtitleStore, gaps_in_ranges

DONE_STATUS = "字幕已就绪"


class Transcriber:
    LOOKAHEAD = 60.0  # 领先播放位置的转写目标（秒）
    CHUNK = 30.0  # 单次转写窗口（秒）
    CONTEXT = 2.0  # 窗口前部补充的上下文音频（秒），转写结果中丢弃
    IDLE_SLEEP = 0.5
    ERROR_BACKOFF = 2.0  # 单窗口转写失败后的退避
    BEHIND_MARGIN = 15.0  # 播放位置前方不足该秒数的未转写内容时提示"落后"

    def __init__(
        self,
        backend: STTBackend,
        decoder: AudioDecoder,
        subtitles: SubtitleStore,
        media_path: Path,
        duration: float,
        on_status=None,
    ):
        self._backend = backend
        self._decoder = decoder
        self._subtitles = subtitles
        self._media_path = Path(media_path)
        self._duration = max(0.0, float(duration))
        self._on_status = on_status or (lambda text: None)
        self._position = 0.0
        self._position_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._done_announced = False

    # ---- 生命周期 ----

    def start(self, initial_position: float = 0.0) -> None:
        self.notify_position(initial_position)
        self._thread = threading.Thread(target=self._run, name="ai-transcriber", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 8.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._decoder.close()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- 播放联动 ----

    def notify_position(self, t: float) -> None:
        with self._position_lock:
            self._position = max(0.0, float(t))

    def _current_position(self) -> float:
        with self._position_lock:
            return self._position

    # ---- 调度核心 ----

    @classmethod
    def next_chunk(cls, covered_ranges, position: float, duration: float) -> tuple[float, float] | None:
        """选择下一个待转写区间。

        优先级：播放位置之后的领先窗口 → 全文件补全。covered_ranges 为
        [(start, end)] 列表（IntervalSet.ranges() 的快照）。
        """
        for gap in gaps_in_ranges(covered_ranges, position, min(position + cls.LOOKAHEAD, duration)):
            return gap
        for gap in gaps_in_ranges(covered_ranges, 0.0, duration):
            return gap
        return None

    # ---- 工作线程 ----

    def _run(self) -> None:
        while not self._stop_event.is_set():
            position = self._current_position()
            chunk = self.next_chunk(self._subtitles.covered.ranges(), position, self._duration)
            if chunk is None:
                if not self._done_announced:
                    self._done_announced = True
                    try:
                        self._subtitles.save_cache(self._media_path)
                    except Exception:
                        pass
                    self._status(DONE_STATUS)
                self._stop_event.wait(self.IDLE_SLEEP * 4)
                continue

            start, _gap_end = chunk
            chunk_end = min(start + self.CHUNK, self._duration)
            if chunk_end - start < 0.2:  # 尾部极短残余
                self._subtitles.covered.add(start, chunk_end + 0.01)
                continue

            if not self._transcribe_one(start, chunk_end, position):
                self._stop_event.wait(self.ERROR_BACKOFF)  # 出错后稍作退避再继续
                continue
            self._stop_event.wait(0.05)

        self._decoder.close()

    def _transcribe_one(self, start: float, chunk_end: float, position: float) -> bool:
        """转写单个窗口；成功返回 True。"""
        ctx_start = max(0.0, start - self.CONTEXT)
        try:
            self._backend.ensure_loaded(progress=self._status_progress)
            pcm = self._decoder.read(ctx_start, chunk_end - ctx_start + 0.5)
            segments = self._backend.transcribe(pcm)
        except Exception as exc:  # 单窗口失败不终止整体
            self._status(f"转写出错：{exc}")
            self._subtitles.covered.add(start, chunk_end)  # 跳过问题区间避免死循环
            return False

        shifted = [
            seg.shifted(ctx_start) for seg in segments if seg.start + ctx_start >= start - 0.05
        ]
        self._subtitles.add_segments(shifted)
        self._subtitles.covered.add(start, chunk_end)
        self._report_progress(position)
        return True

    def _report_progress(self, position: float) -> None:
        ranges = self._subtitles.covered.ranges()
        if gaps_in_ranges(ranges, position, min(position + self.BEHIND_MARGIN, self._duration)):
            self._status("字幕正在追赶播放进度…（可在设置中换小模型）")
        else:
            ratio = self._subtitles.coverage_ratio(self._duration)
            self._status(f"AI 字幕转写中 {int(ratio * 100)}%")

    def _status(self, text: str) -> None:
        try:
            self._on_status(text)
        except Exception:
            pass

    def _status_progress(self, fraction: float | None, message: str) -> None:
        if fraction is None or fraction >= 1.0:
            self._status(message)
        else:
            self._status(f"{message} {int(fraction * 100)}%")
