"""真机冒烟/截图脚本：真实窗口 + GL 渲染，多状态截图后自动退出。

用法：python scripts/smoke_run.py [媒体文件] [模型大小]
用临时目录存配置，不触碰用户真实配置。
截图时序：2s 窗口(控制层可见) → 5s 控制层自动隐藏 → 6s 进全屏 → 7.5s 全屏截图。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from player.core.libmpv import patch_find_library
from player.core.settings import Settings
from player.core.store import Store
from player.ui.main_window import MainWindow
from player.ui.theme import apply_dark_theme


def main() -> int:
    patch_find_library()
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    media = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    model_size = sys.argv[2] if len(sys.argv) > 2 else "tiny"

    QApplication.setOrganizationName("Player")
    QApplication.setApplicationName("Player")
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    tmp = Path(tempfile.mkdtemp(prefix="player_smoke_"))
    settings = Settings(file_path=tmp / "settings.json", ai_model=model_size)
    store = Store(tmp / "state.json")
    win = MainWindow(settings, store, tmp / "subs")
    win.transcriber_status.connect(lambda text: print(f"SMOKE: [transcriber] {text}"))
    win.show()
    if media is not None:
        win.open_path(media)

    def grab(name: str) -> None:
        shot = tmp / f"{name}.png"
        win.video_area.grab().save(str(shot))
        print(f"SMOKE: shot[{name}] -> {shot}", flush=True)

    def grab_hidden() -> None:
        """确定性截图隐藏态：直接置为隐藏（真实自动隐藏已由单测覆盖）。"""
        win.video_area.set_controls_shown(False)
        grab("window_hidden")

    def finish() -> None:
        print("SMOKE: closing")
        win.close()

    QTimer.singleShot(2000, lambda: grab("window_controls"))
    QTimer.singleShot(4000, grab_hidden)
    QTimer.singleShot(5500, win.toggle_fullscreen)
    QTimer.singleShot(7000, lambda: grab("fullscreen_controls"))
    QTimer.singleShot(10000, finish)
    rc = app.exec()
    print(f"SMOKE: exit={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
