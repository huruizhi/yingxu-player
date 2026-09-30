"""faster-whisper 后端：模型懒加载、下载进度回调、分块转写。

模型经 huggingface_hub 下载后缓存本地，之后完全离线运行。
下载依次尝试官方源与 hf-mirror.com 镜像；最终失败抛出带指引的
ModelLoadError（致命——转写会话应中止而非逐块重试）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

from player.ai.base import (
    DownloadProgressFn,
    ModelLoadError,
    Segment,
    STTBackend,
)

_DOWNLOAD_ENDPOINTS = (
    ("官方源", None),
    ("镜像源 hf-mirror.com", "https://hf-mirror.com"),
)


class WhisperBackend(STTBackend):
    name = "whisper"

    def __init__(self, model_size: str = "small", language: str = "auto"):
        self.model_size = model_size
        self.language = language
        self._model = None
        self._load_error: str | None = None
        self._model_lock = threading.RLock()

    # ---- 模型管理 ----

    def is_loaded(self) -> bool:
        with self._model_lock:
            return self._model is not None

    def ensure_loaded(self, progress: DownloadProgressFn | None = None) -> None:
        with self._model_lock:
            if self._model is not None:
                return
            if self._load_error is not None:  # 已失败过：立即短路，不反复重试
                raise ModelLoadError(self._load_error)
            from faster_whisper import WhisperModel

            try:
                model_path = self._ensure_model_downloaded(progress)
                if progress:
                    progress(None, "正在加载模型…")
                self._model = WhisperModel(model_path, device="cpu", compute_type="int8")
            except Exception as exc:
                self._load_error = self._friendly_error(exc)
                raise ModelLoadError(self._load_error) from exc
            if progress:
                progress(1.0, "模型就绪")

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        return (
            f"AI 字幕模型加载失败：{exc}。"
            "已自动尝试官方源与 hf-mirror 镜像；请检查网络，"
            "或在 设置→AI 字幕模型 中换小模型后重试。"
        )

    def _ensure_model_downloaded(self, progress: DownloadProgressFn | None) -> str:
        from faster_whisper.utils import _MODELS
        from huggingface_hub import snapshot_download

        repo = _MODELS.get(self.model_size, self.model_size)
        try:  # 已缓存则离线加载，避免启动时联网校验
            return str(snapshot_download(repo, local_files_only=True))
        except Exception:
            pass
        last_error: Exception | None = None
        for label, endpoint in _DOWNLOAD_ENDPOINTS:
            try:
                if progress:
                    progress(0.0, f"首次使用：下载模型 {self.model_size}（{label}）")
                kwargs: dict = {}
                if endpoint:
                    kwargs["endpoint"] = endpoint
                if progress is not None:
                    kwargs["tqdm_class"] = _progress_tqdm(progress)
                return str(snapshot_download(repo, **kwargs))
            except Exception as exc:
                last_error = exc
                if progress:
                    progress(None, f"{label}下载失败，尝试备用源…")
        raise RuntimeError(f"模型下载失败（已尝试 {len(_DOWNLOAD_ENDPOINTS)} 个源）") from last_error

    # ---- 转写 ----

    def transcribe(self, pcm: np.ndarray, language: str | None = None) -> list[Segment]:
        with self._model_lock:
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
