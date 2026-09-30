"""WhisperBackend 语言映射与下载进度回调的单元测试（不加载真实模型）。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

import numpy as np

from player.ai.base import Segment
from player.ai.whisper_backend import WhisperBackend, _progress_tqdm


class _StubModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, pcm, language=None, **kwargs):
        self.calls.append({"language": language, **kwargs})
        return iter([Segment(0.0, 1.0, "x")]), None


class TestLanguageMapping:
    def make(self, language="auto"):
        backend = WhisperBackend(model_size="tiny", language=language)
        backend._model = _StubModel()
        return backend, backend._model

    def test_auto_maps_to_none(self):
        backend, stub = self.make("auto")
        backend.transcribe(np.zeros(1600, dtype=np.float32))
        assert stub.calls[0]["language"] is None

    def test_explicit_language_passes_through(self):
        backend, stub = self.make("zh")
        backend.transcribe(np.zeros(1600, dtype=np.float32))
        assert stub.calls[0]["language"] == "zh"

    def test_transcribe_arg_overrides_backend_language(self):
        backend, stub = self.make("zh")
        backend.transcribe(np.zeros(1600, dtype=np.float32), language="en")
        assert stub.calls[0]["language"] == "en"

    def test_uses_speed_first_settings(self):
        backend, stub = self.make()
        backend.transcribe(np.zeros(1600, dtype=np.float32))
        call = stub.calls[0]
        assert call["vad_filter"] is True
        assert call["beam_size"] == 1
        assert call["condition_on_previous_text"] is False

    def test_empty_text_filtered(self):
        backend, _ = self.make()
        stub = backend._model
        stub.transcribe = lambda pcm, language=None, **kw: (
            iter([Segment(0, 1, "  "), Segment(1, 2, "有字")]),
            None,
        )
        segs = backend.transcribe(np.zeros(1600, dtype=np.float32))
        assert [s.text for s in segs] == ["有字"]


class TestProgressTqdm:
    def test_update_reports_fraction(self):
        reports = []
        cls = _progress_tqdm(lambda f, m: reports.append((f, m)))
        bar = cls(total=10)
        bar.update(4)
        assert reports and reports[-1][0] == pytest_approx(0.4)

    def test_broken_callback_does_not_raise(self):
        cls = _progress_tqdm(lambda f, m: (_ for _ in ()).throw(RuntimeError))
        bar = cls(total=10)
        bar.update(1)  # 不应抛出


def pytest_approx(v):
    import pytest

    return pytest.approx(v)


def test_shared_model_serializes_concurrent_transcriptions():
    backend = WhisperBackend(model_size="tiny")

    class ConcurrentModel:
        def __init__(self):
            self.lock = Lock()
            self.active = 0
            self.max_active = 0

        def transcribe(self, pcm, language=None, **kwargs):
            def generate():
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                sleep(0.03)
                with self.lock:
                    self.active -= 1
                yield Segment(0.0, 1.0, "x")

            return generate(), None

    model = ConcurrentModel()
    backend._model = model
    pcm = np.zeros(1600, dtype=np.float32)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: backend.transcribe(pcm), range(2)))

    assert len(results) == 2
    assert model.max_active == 1
