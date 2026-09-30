"""AI 链路真机冒烟：模型下载 → PyAV 解码 → faster-whisper 转写。

用法：python scripts/smoke_ai.py [媒体文件] [模型大小]
首次运行会下载模型（tiny 约 75MB），之后离线。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from player.ai.audio_source import AudioDecoder
from player.ai.whisper_backend import WhisperBackend


def main() -> int:
    media = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/media/speech.mp4")
    model_size = sys.argv[2] if len(sys.argv) > 2 else "tiny"

    print(f"[ai-smoke] media={media} model={model_size}")
    decoder = AudioDecoder(media)
    duration = decoder.duration()
    print(f"[ai-smoke] 音频时长: {duration:.2f}s")

    backend = WhisperBackend(model_size=model_size, language="auto")

    def progress(fraction: float | None, message: str) -> None:
        pct = f"{int(fraction * 100)}%" if fraction is not None else "..."
        print(f"[ai-smoke] {message} {pct}")

    started = time.monotonic()
    backend.ensure_loaded(progress=progress)
    print(f"[ai-smoke] 模型就绪，耗时 {time.monotonic() - started:.1f}s")

    pcm = decoder.read(0.0, duration)
    print(f"[ai-smoke] 解码 PCM: {len(pcm)} 样本 ({len(pcm) / 16000:.2f}s)")
    started = time.monotonic()
    segments = backend.transcribe(pcm)
    elapsed = time.monotonic() - started
    print(f"[ai-smoke] 转写耗时 {elapsed:.2f}s（音频 {duration:.2f}s → 实时率 {elapsed / max(duration, 0.01):.2f}x）")
    for seg in segments:
        print(f"  [{seg.start:7.2f} → {seg.end:7.2f}] {seg.text}")
    decoder.close()
    print("[ai-smoke] OK" if segments else "[ai-smoke] 无转写结果（可能无语音）")
    return 0 if segments else 1


if __name__ == "__main__":
    sys.exit(main())
