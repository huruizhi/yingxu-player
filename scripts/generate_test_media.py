"""Generate tiny synthetic media fixtures for integration tests."""

from __future__ import annotations

import subprocess
import tempfile
import os
from pathlib import Path

OUTPUT = Path(
    os.environ.get("YINGXU_TEST_MEDIA_DIR", str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media"))
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
    _generate_if_missing(OUTPUT / "plain.mkv", "-f", "lavfi", "-i", video, "-f", "lavfi", "-i", audio, *common)

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


if __name__ == "__main__":
    main()
