"""Playlist overlay layout and overflow behavior."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from player.ui.playlist_drawer import PlaylistDrawer
from player.ui.playlist_panel import PlaylistPanel


def test_playlist_panel_never_shows_scrollbars(qapp):
    panel = PlaylistPanel()
    assert panel.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert panel.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert panel.textElideMode() == Qt.ElideMiddle


def test_drawer_sizes_to_entries_and_stays_above_transport(qapp):
    parent = QWidget()
    parent.resize(900, 700)
    parent.control_bar = QWidget(parent)
    parent.control_bar.setGeometry(100, 568, 700, 112)
    drawer = PlaylistDrawer(parent)
    drawer.populate([Path(f"Episode {i}.mkv") for i in range(3)], Path("Episode 1.mkv"))

    rect = drawer._target_rect(parent)
    assert rect.height() < parent.height() - 2 * 16
    assert rect.bottom() < parent.control_bar.y()
    assert drawer.count_label.text() == "3 项"


def test_drawer_auto_hides_after_inactivity(qapp, qtbot):
    parent = QWidget()
    parent.resize(900, 700)
    parent.control_bar = QWidget(parent)
    parent.control_bar.setGeometry(100, 568, 700, 112)
    drawer = PlaylistDrawer(parent)
    drawer._auto_hide.setInterval(40)

    drawer.slide_in()
    assert drawer._auto_hide.isActive()
    qtbot.waitUntil(lambda: not drawer.isVisible(), timeout=1000)
