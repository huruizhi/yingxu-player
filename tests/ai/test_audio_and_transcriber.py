"""音频解码与转写调度器的测试。

test_audio_source 用标准库 wave 生成真实 wav（无需 ffmpeg）；
test_transcriber 用假 STT + 假解码器驱动真实线程，验证调度与收敛。
"""

import time
import wave
from threading import Event

import numpy as np
import pytest

from player.ai.audio_source import SAMPLE_RATE, AudioDecodeError, AudioDecoder
from player.ai.base import Segment, STTBackend
from player.ai.subtitles import SubtitleStore
from player.ai.transcriber import DONE_STATUS, Transcriber


def write_sine_wav(path, seconds=3.0, rate=8000, freq=440.0):
    n = int(seconds * rate)
    t = np.arange(n) / rate
    samples = (np.sin(2 * np.pi * freq * t) * 20000).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(samples.tobytes())


@pytest.fixture()
def wav_file(tmp_path):
    path = tmp_path / "tone.wav"
    write_sine_wav(path)
    return path


class TestAudioDecoder:
    def test_duration(self, wav_file):
        decoder = AudioDecoder(wav_file)
        try:
            assert decoder.duration() == pytest.approx(3.0, abs=0.1)
        finally:
            decoder.close()

    def test_read_from_start(self, wav_file):
        decoder = AudioDecoder(wav_file)
        try:
            pcm = decoder.read(0.0, 3.0)
            assert len(pcm) == pytest.approx(3.0 * SAMPLE_RATE, rel=0.01)
            assert pcm.dtype == np.float32
            assert np.abs(pcm).max() > 0.1  # 正弦波非静音
        finally:
            decoder.close()

    def test_read_middle_chunk(self, wav_file):
        decoder = AudioDecoder(wav_file)
        try:
            pcm = decoder.read(1.0, 1.0)
            assert len(pcm) == pytest.approx(1.0 * SAMPLE_RATE, rel=0.01)
            assert np.abs(pcm).max() > 0.1
        finally:
            decoder.close()

    def test_read_past_end_shorter(self, wav_file):
        decoder = AudioDecoder(wav_file)
        try:
            pcm = decoder.read(2.5, 5.0)
            assert 0 < len(pcm) <= 5.0 * SAMPLE_RATE
        finally:
            decoder.close()

    def test_invalid_file_raises(self, tmp_path):
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"this is not audio")
        with pytest.raises(AudioDecodeError):
            AudioDecoder(bad)


class FakeBackend(STTBackend):
    """可编程假 STT：按调用次数返回预设分段。"""

    name = "fake"

    def __init__(self, segments_per_call=None):
        self.calls: list[float] = []  # 每次 PCM 时长
        self.segments_per_call = list(segments_per_call or [])
        self.loaded = False
        self.load_progress = []

    def is_loaded(self):
        return self.loaded

    def ensure_loaded(self, progress=None):
        if not self.loaded:
            self.load_progress.append(progress)
        self.loaded = True

    def transcribe(self, pcm, language=None):
        dur = len(pcm) / SAMPLE_RATE
        self.calls.append(dur)
        idx = min(len(self.segments_per_call), len(self.calls)) - 1
        return list(self.segments_per_call[max(0, idx)])


class FakeDecoder:
    """假解码器：返回指定时长的静音 PCM，并记录请求区间。"""

    def __init__(self, total=0.0):
        self.total = total
        self.requests: list[tuple[float, float]] = []
        self.closed = False

    def read(self, start, max_seconds):
        self.requests.append((start, max_seconds))
        return np.zeros(int(max_seconds * SAMPLE_RATE), dtype=np.float32)

    def close(self):
        self.closed = True


class FastTranscriber(Transcriber):
    CHUNK = 1.0
    LOOKAHEAD = 2.0
    IDLE_SLEEP = 0.01
    ERROR_BACKOFF = 0.01
    BEHIND_MARGIN = 0.5


def wait_until(predicate, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestTranscriber:
    def make(self, tmp_path, duration=4.0, backend=None, initial=0.0):
        subtitles = SubtitleStore(tmp_path / "cache")
        backend = backend or FakeBackend(segments_per_call=[[Segment(0.0, 0.8, "hi")]])
        decoder = FakeDecoder(total=duration)
        statuses: list[str] = []
        transcriber = FastTranscriber(
            backend,
            decoder,
            subtitles,
            tmp_path / "media.mkv",
            duration,
            on_status=statuses.append,
        )
        transcriber.start(initial)
        return transcriber, backend, decoder, subtitles, statuses

    def test_transcribes_ahead_and_completes(self, tmp_path):
        transcriber, backend, decoder, subtitles, statuses = self.make(tmp_path)
        try:
            assert wait_until(lambda: subtitles.covered.ranges() and subtitles.covered.ranges()[-1][1] >= 4.0)
            # 全部转写完毕后进入完成状态并写缓存
            assert wait_until(lambda: DONE_STATUS in statuses)
            assert (tmp_path / "cache").exists()
            assert any(p.suffix == ".srt" for p in (tmp_path / "cache").iterdir())
            assert backend.calls, "至少调用了一次转写"
            assert decoder.requests, "至少读取了一次音频"
        finally:
            transcriber.stop()

    def test_segments_landed_in_store(self, tmp_path):
        transcriber, _b, _d, subtitles, _s = self.make(tmp_path)
        try:
            assert wait_until(lambda: subtitles.all_segments())
            seg = subtitles.all_segments()[0]
            assert seg.text == "hi"
        finally:
            transcriber.stop()

    def test_stop_joins_promptly(self, tmp_path):
        transcriber, *_rest = self.make(tmp_path)
        started = time.monotonic()
        transcriber.stop(timeout=5.0)
        assert time.monotonic() - started < 5.0
        assert not transcriber.is_running()

    def test_stop_can_request_cancellation_without_blocking(self, tmp_path):
        class SlowLoadBackend(FakeBackend):
            def __init__(self):
                super().__init__()
                self.loading = Event()
                self.release = Event()

            def ensure_loaded(self, progress=None):
                self.loading.set()
                self.release.wait(timeout=2)
                self.loaded = True

        backend = SlowLoadBackend()
        transcriber, _, decoder, _, _ = self.make(tmp_path, backend=backend)
        try:
            assert backend.loading.wait(timeout=2)
            started = time.monotonic()
            transcriber.stop(timeout=0)

            assert time.monotonic() - started < 0.1
            assert transcriber.is_running()
            backend.release.set()
            assert wait_until(lambda: not transcriber.is_running())
            assert decoder.requests == []
            assert decoder.closed
        finally:
            backend.release.set()
            transcriber.stop(timeout=2)

    def test_error_marks_chunk_covered_and_continues(self, tmp_path):
        class BrokenBackend(FakeBackend):
            def transcribe(self, pcm, language=None):
                super().transcribe(pcm, language)
                raise RuntimeError("boom")

        transcriber, backend, _d, subtitles, statuses = self.make(
            tmp_path, backend=BrokenBackend([[Segment(0, 1, "x")]])
        )
        try:
            # 出错区间被标记为已覆盖，不会死循环；文件最终完成
            assert wait_until(lambda: DONE_STATUS in statuses)
            assert subtitles.covered.total() >= 4.0
            assert subtitles.all_segments() == []  # 全部失败，无字幕
            assert any("boom" in s for s in statuses)
        finally:
            transcriber.stop()

    def test_next_chunk_prefers_position_window(self):
        ranges = [(0.0, 10.0), (100.0, 200.0)]
        # 位置 0：领先窗口 [0, 60] 内的缺口是 (10, 60)
        assert Transcriber.next_chunk(ranges, 0.0, 200.0) == (10.0, 60.0)
        # 位置 150：领先窗口 [150, 200] 已覆盖，退回全文件补全缺口 (10, 100)
        assert Transcriber.next_chunk(ranges, 150.0, 200.0) == (10.0, 100.0)
        # 全覆盖返回 None
        full = [(0.0, 200.0)]
        assert Transcriber.next_chunk(full, 50.0, 200.0) is None
