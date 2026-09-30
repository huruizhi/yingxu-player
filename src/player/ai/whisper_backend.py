"""faster-whisper 后端：模型懒加载、下载进度回调、分块转写。

模型经 huggingface_hub 下载后缓存本地，之后完全离线运行。
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from player.ai.base import DownloadProgressFn, Segment, STTBackend


class WhisperBackend(STTBackend):
    name = "whisper"

    def __init__(self, model_size: str = "small", language: str = "auto"):
        self.model_size = model_size
        self.language = language
        self._model = None

    # ---- 模型管理 ----

    def is_loaded(self) -> bool:
        return self._model is not None

    def ensure_loaded(self, progress: DownloadProgressFn | None = None) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        model_path = self._ensure_model_downloaded(progress)
        if progress:
            progress(None, "正在加载模型…")
        self._model = WhisperModel(model_path, device="cpu", compute_type="int8")
        if progress:
            progress(1.0, "模型就绪")

    def _ensure_model_downloaded(self, progress: DownloadProgressFn | None) -> str:
        from faster_whisper.utils import _MODELS
        from huggingface_hub import snapshot_download

        repo = _MODELS.get(self.model_size, self.model_size)
        try:  # 已缓存则离线加载，避免启动时联网校验
            return str(snapshot_download(repo, local_files_only=True))
        except Exception:
            pass
        if progress:
            progress(0.0, f"首次使用：下载模型 {self.model_size}（之后离线可用）")
        if progress is None:
            return str(snapshot_download(repo))
        return str(snapshot_download(repo, tqdm_class=_progress_tqdm(progress)))

    # ---- 转写 ----

    def transcribe(self, pcm: np.ndarray, language: str | None = None) -> list[Segment]:
        if self._model is None:
            self.ensure_loaded()
        assert self._model is not None
        lang = language or (None if self.language in ("auto", "") else self.language)
        segments, _info = self._model.transcribe(
            pcm,
            language=lang,
            vad_filter=True,
            beam_size=1,  # 转写速度优先
            condition_on_previous_text=False,  # 分块转写时避免跨块幻觉
        )
        result: list[Segment] = []
        for s in segments:
            text = (s.text or "").strip()
            if text:
                result.append(Segment(float(s.start), float(s.end), text))
        return result


def _progress_tqdm(progress: DownloadProgressFn) -> Callable:
    """生成 tqdm 子类，把 huggingface 下载进度转给回调。"""
    from tqdm import tqdm

    class _ProgressTqdm(tqdm):
        def update(self, n=1):
            try:
                if self.total:
                    fraction = min(1.0, max(0.0, (self.n + n) / self.total))
                    progress(fraction, f"下载模型 {self.desc or ''}".strip())
            except Exception:
                pass
            return super().update(n)

    return _ProgressTqdm
