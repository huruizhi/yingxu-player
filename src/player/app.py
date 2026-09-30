"""应用入口：python -m player.app [--smoke] [媒体文件|目录]。

--smoke：临时配置 + 自动退出 + 打印 AI 状态，用于打包产物的自动化验证
（例如 dist/Yingxu.app/Contents/MacOS/Yingxu --smoke 某文件）。
模型可用环境变量 PLAYER_SMOKE_MODEL 覆盖（默认 tiny，避免大下载）。
"""

from __future__ import annotations

if __name__ == "__main__":
    # PyInstaller reuses the executable for multiprocessing helpers such as
    # resource_tracker. Divert those helpers before importing Qt/mpv so they
    # do not initialize another player window.
    from multiprocessing import freeze_support

    freeze_support()

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
from player.single_instance import SingleInstance
from player.ui.main_window import MainWindow
from player.ui.theme import apply_dark_theme

_QT_OPTIONS_WITH_VALUE = {
    "-display",
    "-geometry",
    "-name",
    "-platform",
    "-platformpluginpath",
    "-plugin",
    "-qmljsdebugger",
    "-session",
    "-stylesheet",
    "-style",
}


def parse_launch_args(argv: list[str]) -> tuple[list[str], bool, Path | None]:
    """Return Qt arguments, smoke mode, and the first positional media path.

    Launch Services and developer launchers can add switches before a file
    path. Those switches must not be mistaken for media files.
    """
    qt_args = [argv[0]]
    smoke = False
    media_path = None
    positional_only = False
    skip_value = False

    for arg in argv[1:]:
        if arg == "--smoke":
            smoke = True
            continue
        if arg == "--" and not positional_only:
            positional_only = True
            continue
        if not positional_only and skip_value:
            qt_args.append(arg)
            skip_value = False
            continue
        if not positional_only and arg in _QT_OPTIONS_WITH_VALUE:
            qt_args.append(arg)
            skip_value = True
            continue
        if not positional_only and arg.startswith("-"):
            qt_args.append(arg)
            continue

        qt_args.append(arg)
        if media_path is None:
            media_path = Path(arg).expanduser()

    return qt_args, smoke, media_path


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


def _app_icon_path() -> Path:
    """Resolve the app icon in source checkouts and macOS bundles."""
    relative_path = Path("assets") / "yingxu-icon.png"
    if hasattr(sys, "_MEIPASS"):
        bundle_resources = Path(sys.executable).resolve().parents[1] / "Resources"
        roots = (Path(sys._MEIPASS), bundle_resources)
    else:
        roots = (Path(__file__).resolve().parents[2],)
    return next(
        (root / relative_path for root in roots if (root / relative_path).is_file()), roots[0] / relative_path
    )


def main() -> int:
    args, smoke, media_path = parse_launch_args(sys.argv)
    single_instance = None
    if not smoke:
        single_instance = SingleInstance("dev.yingxu.player")
        if not single_instance.is_primary:
            if single_instance.forward(str(media_path) if media_path is not None else None):
                return 0
            raise RuntimeError("映序已在运行，但无法连接到现有进程")

    patch_find_library()  # 必须在 mpv 绑定首次加载前生效
    _apply_surface_format()
    # 保留旧配置命名，升级品牌时不改变现有设置与缓存目录。
    QApplication.setOrganizationName("Player")
    QApplication.setApplicationName("Player")
    app = QApplication(args)
    from PySide6.QtGui import QIcon

    app.setWindowIcon(QIcon(str(_app_icon_path())))
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

    if single_instance is not None:

        def handle_secondary_launch(path: str | None) -> None:
            if window.isMinimized():
                window.showNormal()
            else:
                window.show()
            window.raise_()
            window.activateWindow()
            if path:
                window.open_path(Path(path))

        single_instance.request_received.connect(handle_secondary_launch)

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
    if media_path is not None:
        window.open_path(media_path)
    if not smoke:
        QTimer.singleShot(2500, window.check_for_updates)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
