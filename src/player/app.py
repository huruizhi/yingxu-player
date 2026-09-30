"""应用入口：python -m player.app [媒体文件|目录]。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
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
    patch_find_library()  # 必须在 mpv 绑定首次加载前生效
    _apply_surface_format()
    QApplication.setOrganizationName("Player")
    QApplication.setApplicationName("Player")
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    settings_path, store_path, subtitle_cache = _config_paths()
    settings = Settings.load(settings_path)
    store = Store(store_path)
    window = MainWindow(settings, store, subtitle_cache)
    window.show()

    if len(sys.argv) > 1:
        window.open_path(Path(sys.argv[1]))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
