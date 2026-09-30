"""播放列表面板：条目双击/回车播放，高亮当前项。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem


class PlaylistPanel(QListWidget):
    item_activated = Signal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("playlistPanel")
        self.setUniformItemSizes(True)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.ElideMiddle)
        self.itemActivated.connect(self._on_activated)
        self.itemDoubleClicked.connect(self._on_activated)

    def _on_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.item_activated.emit(Path(path))

    def populate(self, paths: list[Path], current: Path | None) -> None:
        self.blockSignals(True)
        self.clear()
        current_row = -1
        for i, p in enumerate(paths):
            item = QListWidgetItem(p.name)
            item.setData(Qt.UserRole, str(p))
            item.setToolTip(str(p))
            self.addItem(item)
            if current is not None and p == current:
                current_row = i
        self.blockSignals(False)
        if current_row >= 0:
            self.setCurrentRow(current_row)
            self.scrollToItem(self.item(current_row), QListWidget.EnsureVisible)

    def highlight_current(self, path: Path | None) -> None:
        if path is None:
            self.setCurrentRow(-1)
            return
        for i in range(self.count()):
            if Path(self.item(i).data(Qt.UserRole)) == path:
                self.setCurrentRow(i)
                self.scrollToItem(self.item(i), QListWidget.EnsureVisible)
                return
        self.setCurrentRow(-1)
