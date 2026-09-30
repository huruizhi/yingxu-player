"""应用入口：python -m player.app [--smoke] [媒体文件|目录]。

--smoke：临时配置 + 自动退出 + 打印 AI 状态，用于打包产物的自动化验证
（例如 dist/Player.app/Contents/MacOS/Player --smoke 某文件）。
模型可用环境变量 PLAYER_SMOKE_MODEL 覆盖（默认 tiny，避免大下载）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from player.core.libmpv import patch_find_library
from player.core.settings import Settings
from player.core.store import Store
from player.ui.main_window import MainWindow
from player.ui.theme import apply_dark_theme


def _apply_surface_format() -> None:
    """请求 GL 3.3 Core：macOS 默认给 2.1 兼容上下文，mpv 的缩放器与
    VideoToolbox 硬解互操作在 GL<3.0 下会被禁用。"""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)


def _config_paths() -> tuple[Path, Path, Path]:
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    cache_dir = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation))
    return data_dir / "settings.json", data_dir / "state.json", cache_dir / "subtitles"


def main() -> int:
    args = [a for a in sys.argv if a != "--smoke"]
    smoke = len(args) != len(sys.argv)
    patch_find_library()  # 必须在 mpv 绑定首次加载前生效
    _apply_surface_format()
    QApplication.setOrganizationName("Player")
    QApplication.setApplicationName("Player")
    app = QApplication(args)
    apply_dark_theme(app)

    if smoke:
        tmp = Path(tempfile.mkdtemp(prefix="player_smoke_"))
        settings = Settings(
            file_path=tmp / "settings.json",
            ai_model=os.environ.get("PLAYER_SMOKE_MODEL", "tiny"),
        )
        settings_path, store_path, subtitle_cache = (
            tmp / "settings.json",
            tmp / "state.json",
            tmp / "subs",
        )
    else:
        settings_path, store_path, subtitle_cache = _config_paths()
        settings = Settings.load(settings_path)

    store = Store(store_path)
    window = MainWindow(settings, store, subtitle_cache)

    if smoke:
        window.transcriber_status.connect(lambda text: print(f"[smoke][ai] {text}", flush=True))

        def report() -> None:
            print(
                f"[smoke] segments={len(window.subtitles.all_segments())} "
                f"covered={window.subtitles.covered.ranges()}",
                flush=True,
            )

        QTimer.singleShot(7000, report)
        QTimer.singleShot(9500, window.close)

    window.show()
    if len(args) > 1:
        window.open_path(Path(args[1]))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
