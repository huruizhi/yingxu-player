"""目录扫描与播放列表：媒体扩展名过滤、自然排序、循环模式。

纯逻辑模块，不依赖 Qt，便于单元测试。
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".mov",
    ".avi",
    ".webm",
    ".ts",
    ".m4v",
    ".flv",
    ".wmv",
    ".mpg",
    ".mpeg",
}
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".wma"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# 同名不同格式的文件，mkv 排在其他格式之前（MKV 优先策略）
_EXTENSION_PRIORITY: dict[str, int] = {".mkv": 0}

_SPLIT_RE = re.compile(r"(\d+)")


def _chunk_key(chunk: str) -> tuple[int, int, str]:
    """数字块与非数字块归一为可比较的三元组，避免 int/str 混比报错。"""
    if chunk.isdigit():
        return (0, int(chunk), "")
    return (1, 0, chunk.lower())


def natural_key(name: str) -> tuple:
    """'ep2' 排在 'ep10' 之前的自然排序键。"""
    return tuple(_chunk_key(c) for c in _SPLIT_RE.split(name))


def scan_media_files(directory: Path) -> list[Path]:
    """扫描目录下的媒体文件：跳过隐藏文件，自然排序（mkv 同键优先）。"""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    files = [
        p
        for p in directory.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and not p.name.startswith("._")  # macOS 资源分叉文件
        and p.suffix.lower() in MEDIA_EXTENSIONS
    ]
    files.sort(
        key=lambda p: (
            natural_key(p.stem),
            (_EXTENSION_PRIORITY.get(p.suffix.lower(), 1), p.suffix.lower()),
            p.name,
        )
    )
    return files


class LoopMode(Enum):
    SINGLE = "single"  # 单曲循环
    ALL = "all"  # 列表循环
    SHUFFLE = "shuffle"  # 随机播放


@dataclass
class Playlist:
    """播放列表状态与切换逻辑。

    shuffle 使用注入的 rng，保证测试可复现。
    """

    items: list[Path] = field(default_factory=list)
    current: int = -1
    mode: LoopMode = LoopMode.ALL
    rng: random.Random = field(default_factory=random.Random)
    _shuffle_order: list[int] = field(default_factory=list)
    _shuffle_pos: int = -1

    # ---- 构造 ----

    def set_items(self, paths: Iterable[Path], keep_current: bool = False) -> None:
        old = self.current_item
        self.items = [Path(p) for p in paths]
        self.current = -1
        self._shuffle_order = []
        self._shuffle_pos = -1
        if keep_current and old is not None:
            self.jump_to_path(old)

    def load_directory(self, directory: Path, start_file: Path | None = None) -> None:
        """扫描目录生成列表；给定的起始文件被设为当前项。"""
        files = scan_media_files(Path(directory))
        self.set_items(files)
        if start_file is not None:
            self.jump_to_path(Path(start_file).resolve())

    # ---- 查询 ----

    @property
    def current_item(self) -> Path | None:
        if 0 <= self.current < len(self.items):
            return self.items[self.current]
        return None

    def __len__(self) -> int:
        return len(self.items)

    # ---- 切换 ----

    def next(self, auto: bool = False) -> Path | None:
        """返回下一个应播放的条目；列表为空返回 None。

        auto=True 表示播完自动连播：SINGLE 模式下重复当前项；
        auto=False 表示用户手动切下一首：SINGLE 模式下也前进。
        """
        if not self.items:
            return None
        if self.mode is LoopMode.SINGLE and auto:
            return self.current_item
        if self.mode is LoopMode.SHUFFLE:
            return self._next_shuffle()
        self.current = (self.current + 1) % len(self.items)
        return self.current_item

    def previous(self) -> Path | None:
        if not self.items:
            return None
        if self.mode is LoopMode.SHUFFLE:
            return self._previous_shuffle()
        self.current = (self.current - 1) % len(self.items)
        return self.current_item

    def jump_to(self, index: int) -> Path | None:
        if not 0 <= index < len(self.items):
            return None
        self.current = index
        if self.mode is LoopMode.SHUFFLE and self._shuffle_order:
            self._shuffle_pos = self._shuffle_order.index(index)
        return self.current_item

    def jump_to_path(self, path: Path) -> Path | None:
        path = Path(path).resolve()
        for i, item in enumerate(self.items):
            if item.resolve() == path:
                return self.jump_to(i)
        return None

    def set_mode(self, mode: LoopMode) -> None:
        self.mode = mode
        if mode is LoopMode.SHUFFLE:
            self._build_shuffle_order()

    def _build_shuffle_order(self) -> None:
        """生成不含当前项的随机顺序，保证换局后的下一项与当前不同。"""
        rest = [i for i in range(len(self.items)) if i != self.current]
        self.rng.shuffle(rest)
        self._shuffle_order = rest
        self._shuffle_pos = -1

    def _next_shuffle(self) -> Path | None:
        if len(self.items) == 1:
            return self.current_item
        if self._shuffle_pos >= len(self._shuffle_order) - 1:
            self._build_shuffle_order()
        self._shuffle_pos += 1
        self.current = self._shuffle_order[self._shuffle_pos]
        return self.current_item

    def _previous_shuffle(self) -> Path | None:
        if len(self.items) == 1:
            return self.current_item
        if self._shuffle_pos <= 0:
            self._build_shuffle_order()
            self._shuffle_pos = len(self._shuffle_order)
        self._shuffle_pos -= 1
        self.current = self._shuffle_order[self._shuffle_pos]
        return self.current_item
