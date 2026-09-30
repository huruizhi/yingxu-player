"""AI 字幕分段存储、转写覆盖区间跟踪与 .srt 缓存/导出。

SubtitleStore 只保存"当前文件"的分段；按媒体文件指纹持久化为 .srt 缓存，
二次打开同文件直接载入缓存，不再耗 CPU 转写。所有方法线程安全。
"""

from __future__ import annotations

import bisect
import hashlib
import re
import threading
from pathlib import Path

from player.ai.base import Segment

_SRT_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
_EVENT_RE = re.compile(r"^\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*$")


def _parse_srt_time(text: str) -> float:
    m = _SRT_TIME_RE.match(text.strip())
    if not m:
        raise ValueError(f"非法 SRT 时间: {text!r}")
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def format_srt_time(t: float) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[Segment]) -> str:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


def parse_srt(text: str) -> list[Segment]:
    """容错解析 SRT：跳过无法解析的块。"""
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        timing_idx = next((i for i, ln in enumerate(lines) if _EVENT_RE.match(ln)), None)
        if timing_idx is None:
            continue
        m = _EVENT_RE.match(lines[timing_idx])
        assert m is not None
        try:
            start = _parse_srt_time(m.group(1))
            end = _parse_srt_time(m.group(2))
        except ValueError:
            continue
        body = "\n".join(lines[timing_idx + 1 :]).strip()
        if not body:
            continue
        segments.append(Segment(start, max(start, end), body))
    return sorted(segments, key=lambda s: s.start)


def gaps_in_ranges(ranges: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    """计算 [start, end) 与已覆盖区间列表的差集（纯函数，供 IntervalSet 与调度器共用）。"""
    gaps: list[tuple[float, float]] = []
    cursor = start
    for lo, hi in ranges:
        if hi <= cursor:
            continue
        if lo >= end:
            break
        if lo > cursor:
            gaps.append((cursor, min(lo, end)))
        cursor = max(cursor, hi)
        if cursor >= end:
            break
    if cursor < end:
        gaps.append((cursor, end))
    return [(a, b) for a, b in gaps if b > a]


class IntervalSet:
    """合并去重的浮点区间集合，用于跟踪已转写范围。线程安全。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ranges: list[list[float]] = []

    def add(self, start: float, end: float) -> None:
        if end <= start:
            return
        with self._lock:
            new = [float(start), float(end)]
            merged: list[list[float]] = []
            for rng in self._ranges:
                if rng[1] < new[0] or rng[0] > new[1]:
                    merged.append(rng)
                else:
                    new[0] = min(new[0], rng[0])
                    new[1] = max(new[1], rng[1])
            merged.append(new)
            merged.sort()
            self._ranges = merged

    def gaps_in(self, start: float, end: float) -> list[tuple[float, float]]:
        """返回 [start, end) 与已覆盖范围的差集。"""
        with self._lock:
            return gaps_in_ranges(self._ranges, start, end)

    def total(self) -> float:
        with self._lock:
            return sum(hi - lo for lo, hi in self._ranges)

    def ranges(self) -> list[tuple[float, float]]:
        with self._lock:
            return [(lo, hi) for lo, hi in self._ranges]

    def clear(self) -> None:
        with self._lock:
            self._ranges = []


class SubtitleStore:
    """当前文件的 AI 字幕运行时存储 + .srt 缓存。"""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._segments: list[Segment] = []
        self._starts: list[float] = []
        self.covered = IntervalSet()

    # ---- 缓存 ----

    @staticmethod
    def fingerprint(media_path: Path) -> str:
        p = Path(media_path)
        try:
            stat = p.stat()
            raw = f"{p.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
        except OSError:
            raw = str(p)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def cache_path(self, media_path: Path) -> Path:
        return self.cache_dir / f"{self.fingerprint(media_path)}.srt"

    def try_load_cache(self, media_path: Path, duration: float) -> bool:
        """加载该文件的缓存字幕；成功后视整个时长为已覆盖。"""
        cache = self.cache_path(media_path)
        try:
            segments = parse_srt(cache.read_text(encoding="utf-8"))
        except OSError:
            return False
        if not segments:
            return False
        with self._lock:
            self._segments = segments
            self._starts = [s.start for s in segments]
        self.covered.clear()
        self.covered.add(0.0, max(duration, segments[-1].end))
        return True

    def save_cache(self, media_path: Path) -> None:
        with self._lock:
            body = to_srt(self._segments)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path(media_path).write_text(body, encoding="utf-8")

    def export_srt(self, media_path: Path) -> Path:
        """导出 .srt 到媒体文件旁；重名时用 .ai.srt 避免覆盖既有字幕。"""
        base = Path(media_path)
        dest = base.with_suffix(".srt")
        if dest.exists():
            dest = base.with_suffix(".ai.srt")
        dest.write_text(to_srt(self.all_segments()), encoding="utf-8")
        return dest

    # ---- 运行时 ----

    def clear_runtime(self) -> None:
        with self._lock:
            self._segments = []
            self._starts = []
        self.covered.clear()

    def add_segments(self, segments: list[Segment]) -> None:
        with self._lock:
            for seg in segments:
                idx = bisect.bisect_left(self._starts, seg.start)
                self._starts.insert(idx, seg.start)
                self._segments.insert(idx, seg)

    def all_segments(self) -> list[Segment]:
        with self._lock:
            return list(self._segments)

    def current(self, t: float) -> Segment | None:
        """返回时刻 t 正在显示的分段；没有则 None。"""
        with self._lock:
            idx = bisect.bisect_right(self._starts, t) - 1
            if idx < 0:
                return None
            seg = self._segments[idx]
            if seg.start <= t <= seg.end:
                return seg
            return None

    def coverage_ratio(self, duration: float) -> float:
        if duration <= 0:
            return 0.0
        return min(1.0, self.covered.total() / duration)
