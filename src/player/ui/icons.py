"""Small, consistent vector icons for playback controls."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "play": '<path d="m9 5 11 7-11 7Z" fill="currentColor" stroke="none"/>',
    "pause": '<rect x="7" y="5" width="3.5" height="14" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="5" width="3.5" height="14" rx="1" fill="currentColor" stroke="none"/>',
    "previous": '<path d="M6 5v14m13-14L8 12l11 7Z"/>',
    "next": '<path d="M18 5v14M5 5l11 7-11 7Z"/>',
    "subtitles": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 10h3m4 0h3M7 14h5m3 0h2"/>',
    "volume": '<path d="m11 5-5 4H3v6h3l5 4Zm4 4a5 5 0 0 1 0 6m3-9a9 9 0 0 1 0 12"/>',
    "fullscreen": '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
    # Four inward arrows make the fullscreen-exit action read as "shrink".
    "exit_fullscreen": '<path d="M3 3l5 5M5 8h3V5m13-2-5 5m0-3v3h3M3 21l5-5m0 3v-3H5m16 5-5-5m3 0h-3v3"/>',
    "playlist": '<path d="M4 6h16M4 11h16M4 16h9m4-1 4 3-4 3Z"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "skip": '<path d="m4 6 8 6-8 6Zm9 0 8 6-8 6Z"/>',
    "open": '<path d="M4 7a2 2 0 0 1 2-2h4l2 3h6a2 2 0 0 1 2 2v8H4Z"/><path d="M12 11v5m-2.5-2.5L12 11l2.5 2.5"/>',
    # 画中画：外层窗口 + 右下角小画面
    "pip": '<rect x="3" y="5" width="18" height="14" rx="2"/><rect x="11.5" y="12" width="7" height="5" rx="1" fill="currentColor" stroke="none"/>',
}


@lru_cache(maxsize=64)
def icon(name: str, color: str = "#eceef3", size: int = 24) -> QIcon:
    result = QIcon()
    for mode, state, tint in (
        (QIcon.Normal, QIcon.Off, color),
        (QIcon.Active, QIcon.Off, color),
        (QIcon.Disabled, QIcon.Off, "#626874"),
        (QIcon.Normal, QIcon.On, "#90b9ff"),
        (QIcon.Active, QIcon.On, "#90b9ff"),
    ):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{tint}" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round" color="{tint}">'
            f"{_PATHS[name]}</svg>"
        )
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
        painter.end()
        result.addPixmap(pixmap, mode, state)
    return result
