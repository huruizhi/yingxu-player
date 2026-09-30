# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：打包映序 macOS .app 并捆绑 libmpv。

构建：make package（.venv/bin/python -m PyInstaller packaging/player.spec --noconfirm）
产物：dist/Yingxu.app（显示名称：映序）
"""

import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
sys.path.insert(0, str(ROOT / "src"))

from player.core.libmpv import find_libmpv  # noqa: E402

libmpv = find_libmpv()
if libmpv is None:
    raise SystemExit("未找到 libmpv，请先 brew install mpv")
print(f"bundling libmpv: {libmpv}")

# faster-whisper 的 assets/（silero VAD onnx）必须打包，否则 .app 内 AI 字幕报错
fw_datas = collect_data_files("faster_whisper")
print(f"faster_whisper data files: {[src for _, src in fw_datas]}")
icon_path = ROOT / "assets" / "yingxu.icns"
fw_datas.append((str(ROOT / "assets" / "yingxu-icon.png"), "assets"))

block_cipher = None

a = Analysis(
    [str(ROOT / "src" / "player" / "app.py")],
    pathex=[str(ROOT / "src")],
    binaries=[(libmpv, ".")],
    datas=fw_datas,
    hiddenimports=["mpv"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Yingxu",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # .app 不带终端窗口
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Yingxu",
)
app = BUNDLE(
    coll,
    name="Yingxu.app",
    icon=str(icon_path),
    info_plist={
        "CFBundleName": "映序",
        "CFBundleDisplayName": "映序",
        "CFBundleIdentifier": "dev.yingxu.player",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
