"""语音识别后端抽象与公共数据结构。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

# 进度回调：fraction 为 0~1（None 表示不确定），message 为人类可读状态
DownloadProgressFn = Callable[[float | None, str], None]


class ModelLoadError(RuntimeError):
    """模型下载/加载失败（致命：转写会话应中止而非逐块重试）。"""


@dataclass(frozen=True)
class Segment:
    """一条字幕分段：媒体时间轴（秒）+ 文本。"""

    start: float
    end: float
    text: str

    def shifted(self, offset: float) -> Segment:
        return Segment(self.start + offset, self.end + offset, self.text)


class STTBackend(ABC):
    """语音识别后端接口。实现只需在单个调度线程内被调用。"""

    name: str = "stt"

    @abstractmethod
    def is_loaded(self) -> bool:
        """模型是否已加载。"""

    @abstractmethod
    def ensure_loaded(self, progress: DownloadProgressFn | None = None) -> None:
        """加载（必要时下载）模型；下载/加载进度通过 progress 回调上报。"""

    @abstractmethod
    def transcribe(self, pcm: np.ndarray, language: str | None = None) -> list[Segment]:
        """转写 16kHz 单声道 float32 PCM；返回时间戳相对 PCM 起点的分段。"""
