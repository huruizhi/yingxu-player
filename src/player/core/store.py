"""媒体状态持久化：每个文件的播放进度、片尾标记（单文件与同目录两级）。

按文件绝对路径为键，JSON 存储；mark_credits 同时写入文件级与目录级记录，
使同目录的剧集标记一次即可全部生效。
"""

from __future__ import annotations

from pathlib import Path

from player.core.storage import load_json, save_json_atomic

# 恢复进度的门槛：短于该时长的文件不记忆进度
MIN_DURATION_FOR_RESUME = 60.0


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        data = load_json(self.path, {})
        self._progress: dict[str, dict] = data.get("progress", {})
        self._credits_files: dict[str, float] = data.get("credits_files", {})
        self._credits_dirs: dict[str, float] = data.get("credits_dirs", {})

    # ---- 播放进度 ----

    def get_progress(self, path: Path) -> float | None:
        """返回可恢复的播放位置；不适用的情形（太短/接近结尾）返回 None。"""
        entry = self._progress.get(self._key(path))
        if not entry:
            return None
        position, duration = entry.get("position", 0.0), entry.get("duration", 0.0)
        if duration < MIN_DURATION_FOR_RESUME:
            return None
        if position >= duration - 5.0:  # 已接近结尾，重头播
            return None
        if position < 30.0:  # 刚开头，无需恢复
            return None
        return float(position)

    def set_progress(self, path: Path, position: float, duration: float) -> None:
        self._progress[self._key(path)] = {
            "position": round(float(position), 3),
            "duration": round(float(duration), 3),
        }
        self._prune_progress()

    def forget_progress(self, path: Path) -> None:
        self._progress.pop(self._key(path), None)

    def _prune_progress(self) -> None:
        """最多保留 500 条进度记录，超出时丢弃最旧的（按插入顺序近似）。"""
        if len(self._progress) <= 500:
            return
        for key in list(self._progress)[: len(self._progress) - 500]:
            del self._progress[key]

    # ---- 片尾标记 ----

    def mark_credits(self, path: Path, seconds: float) -> None:
        """在给定时间点标记片尾；同时写入文件级与目录级记录。"""
        self._credits_files[self._key(path)] = float(seconds)
        self._credits_dirs[self._dir_key(path)] = float(seconds)
        self.save()

    def get_credits_start(self, path: Path) -> float | None:
        """片尾起点：文件级记录优先于目录级。"""
        file_entry = self._credits_files.get(self._key(path))
        if file_entry is not None:
            return float(file_entry)
        dir_entry = self._credits_dirs.get(self._dir_key(path))
        if dir_entry is not None:
            return float(dir_entry)
        return None

    def clear_credits(self, path: Path) -> bool:
        """清除该文件的片尾标记（含其目录级记录）。返回是否有变更。"""
        changed = self._credits_files.pop(self._key(path), None) is not None
        changed = self._credits_dirs.pop(self._dir_key(path), None) is not None or changed
        if changed:
            self.save()
        return changed

    def all_credits(self) -> dict[str, list]:
        """全部片尾标记，供设置界面管理：{"files": {...}, "dirs": {...}}。"""
        return {
            "files": dict(self._credits_files),
            "dirs": dict(self._credits_dirs),
        }

    # ---- 持久化 ----

    def save(self) -> None:
        save_json_atomic(
            self.path,
            {
                "progress": self._progress,
                "credits_files": self._credits_files,
                "credits_dirs": self._credits_dirs,
            },
        )

    @staticmethod
    def _key(path: Path) -> str:
        return str(Path(path).resolve())

    @staticmethod
    def _dir_key(path: Path) -> str:
        return str(Path(path).resolve().parent)
