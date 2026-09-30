"""真机冒烟脚本：真实窗口 + GL 渲染，定时自动退出。

用法：python scripts/smoke_run.py [媒体文件]
用临时目录存配置，不触碰用户真实配置。
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

    QApplication.setOrganizationName("Player")
    QApplication.setApplicationName("Player")
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    tmp = Path(tempfile.mkdtemp(prefix="player_smoke_"))
    settings = Settings(file_path=tmp / "settings.json")
    store = Store(tmp / "state.json")
    win = MainWindow(settings, store, tmp / "subs")
    win.show()
    if len(sys.argv) > 1:
        win.open_path(Path(sys.argv[1]))

    def grab() -> None:
        shot = tmp / "frame.png"
        win.video_area.grab().save(str(shot))
        print(f"SMOKE: frame saved to {shot}")

    def finish() -> None:
        print("SMOKE: closing")
        win.close()

    QTimer.singleShot(5000, grab)
    QTimer.singleShot(9000, finish)
    rc = app.exec()
    print(f"SMOKE: exit={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
