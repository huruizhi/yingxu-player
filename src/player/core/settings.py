"""应用设置：字幕源策略、AI 模型、片尾开关、音量等。

纯逻辑模块；文件位置由 UI 层决定（QStandardPaths）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from pathlib import Path

from player.core.storage import load_json, save_json_atomic


class SubtitleSource(StrEnum):
    AUTO = "auto"  # 内置字幕优先，无内置字幕轨时才启用 AI 生成
    FORCE_AI = "force_ai"  # 强制 AI 字幕（自动隐藏内置字幕轨，避免重叠）
    OFF = "off"  # 关闭 AI 字幕（内置字幕轨照常显示）

    @classmethod
    def _missing_(cls, value):
        return cls.AUTO


AI_MODELS = ("tiny", "base", "small", "medium")
AI_LANGUAGES = ("auto", "zh", "en")
MAX_RECENT_DIRECTORIES = 8


@dataclass
class Settings:
    subtitle_source: SubtitleSource = SubtitleSource.AUTO
    ai_model: str = "small"
    ai_language: str = "auto"
    skip_credits_enabled: bool = False
    volume: int = 60
    speed: float = 1.0
    playlist_mode: str = "all"  # LoopMode 的值
    recent_directories: list[str] = field(default_factory=list)
    window: dict = field(default_factory=dict)  # 窗口几何 {x,y,w,h,maximized}
    file_path: Path | None = None  # 持久化位置；None 表示不落盘（测试/临时）

    def __post_init__(self):
        if self.ai_model not in AI_MODELS:
            self.ai_model = "small"
        if self.ai_language not in AI_LANGUAGES:
            self.ai_language = "auto"
        self.subtitle_source = SubtitleSource(self.subtitle_source)
        try:
            self.volume = int(self.volume)
        except (TypeError, ValueError):
            self.volume = 60
        self.volume = min(130, max(0, self.volume))
        try:
            self.speed = float(self.speed)
        except (TypeError, ValueError):
            self.speed = 1.0
        if not 0.25 <= self.speed <= 4.0:
            self.speed = 1.0
        if not isinstance(self.recent_directories, list):
            self.recent_directories = []
        self.recent_directories = list(
            dict.fromkeys(path for path in self.recent_directories if isinstance(path, str) and path)
        )[:MAX_RECENT_DIRECTORIES]

    def remember_directory(self, directory: Path) -> None:
        path = str(Path(directory).expanduser().resolve())
        self.recent_directories = [path, *(p for p in self.recent_directories if p != path)]
        self.recent_directories = self.recent_directories[:MAX_RECENT_DIRECTORIES]

    @classmethod
    def load(cls, path: Path) -> Settings:
        data = load_json(path, {})
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in data.items() if k in known})
        settings.file_path = Path(path)
        return settings

    def save(self, path: Path | None = None) -> None:
        target = Path(path) if path is not None else self.file_path
        if target is None:
            return
        data = asdict(self)
        data.pop("file_path", None)
        data["subtitle_source"] = self.subtitle_source.value
        save_json_atomic(target, data)
