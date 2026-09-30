"""JSON 文件读写工具：带原子写入，避免写入中断损坏配置。"""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_json(path: Path, default: dict) -> dict:
    """读取 JSON；文件缺失或损坏时返回 default 的副本。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(default)
    if not isinstance(data, dict):
        return dict(default)
    return data


def save_json_atomic(path: Path, data: dict) -> None:
    """先写临时文件再原子替换，防止半写状态。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
