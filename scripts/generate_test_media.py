"""Generate tiny synthetic media fixtures for integration tests."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

OUTPUT = Path(
    os.environ.get(
        "YINGXU_TEST_MEDIA_DIR", str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media")
    )
)


def _generate_if_missing(target: Path, *args: str) -> None:
    if target.exists():
        return
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, str(target)], check=True)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    video = "testsrc2=size=320x180:rate=12:duration=12"
    audio = "sine=frequency=440:sample_rate=44100:duration=12"
    common = ["-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-b:a", "64k", "-shortest"]

    _generate_if_missing(
        OUTPUT / "speech.mp4", "-f", "lavfi", "-i", video, "-t", "12", "-an", "-c:v", "mpeg4", "-q:v", "5"
    )
    _generate_if_missing(
        OUTPUT / "plain.mkv", "-f", "lavfi", "-i", video, "-f", "lavfi", "-i", audio, *common
    )

    subtitle_target = OUTPUT / "test_with_subs.mkv"
    if not subtitle_target.exists():
        with tempfile.TemporaryDirectory(prefix="yingxu-test-media-") as temp_dir:
            subtitle = Path(temp_dir) / "fixture.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\nSynthetic subtitle\n", encoding="utf-8")
            _generate_if_missing(
                subtitle_target,
                "-f",
                "lavfi",
                "-i",
                video,
                "-f",
                "lavfi",
                "-i",
                audio,
                "-i",
                str(subtitle),
                *common,
                "-c:s",
                "srt",
            )

    # 带章节的独立目录，避免混入 media/ 后改变既有播放列表数量的断言
    chapter_dir = OUTPUT.parent / "media_chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    chapters_target = chapter_dir / "chapters.mkv"
    if not chapters_target.exists():
        with tempfile.TemporaryDirectory(prefix="yingxu-test-media-") as temp_dir:
            metadata = Path(temp_dir) / "chapters.txt"
            metadata.write_text(
                ";FFMETADATA1\n"
                "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=4000\ntitle=开场\n"
                "[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=8000\ntitle=中段\n"
                "[CHAPTER]\nTIMEBASE=1/1000\nSTART=8000\nEND=12000\ntitle=结尾\n",
                encoding="utf-8",
            )
            _generate_if_missing(
                chapters_target,
                "-f",
                "lavfi",
                "-i",
                video,
                "-f",
                "lavfi",
                "-i",
                audio,
                "-i",
                str(metadata),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-map_chapters",
                "2",
                *common,
            )


if __name__ == "__main__":
    main()
