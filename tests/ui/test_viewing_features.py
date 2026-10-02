"""主窗口观看功能：截图、音画同步、画面调整、AB 循环、章节、置顶、画中画。"""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from player.core.playback import Playback
from player.core.settings import Settings, SubtitleSource
from player.core.store import Store
from player.ui.main_window import MainWindow
from player.ui.timeline_slider import TimelineSlider

MEDIA = Path(__file__).resolve().parent.parent / "fixtures" / "media"
CHAPTERS = Path(__file__).resolve().parent.parent / "fixtures" / "media_chapters"

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture()
def window(tmp_path):
    settings = Settings(subtitle_source=SubtitleSource.OFF)
    store = Store(tmp_path / "state.json")
    playback = Playback(video_out="null", audio_out="null")  # 离屏测试无渲染与音频设备
    win = MainWindow(settings, store, tmp_path / "sub_cache", playback=playback)
    yield win
    try:
        win.video_area.mpv_widget.shutdown()
        playback.terminate()
    except Exception:
        pass


# ---- 画面调整 ----


def test_aspect_cycle_and_menu_state(window):
    window._cycle_aspect_override()
    assert window._aspect_override == "4:3"
    assert window._aspect_actions["4:3"].isChecked()
    window._cycle_aspect_override()
    assert window._aspect_override == "16:9"
    for _ in range(3):  # 1.85:1 → 2.35:1 → 跟随视频
        window._cycle_aspect_override()
    assert window._aspect_override is None
    assert window._aspect_actions[None].isChecked()


def test_rotate_cycle(window):
    window._cycle_rotate()
    assert window._video_rotate == 90
    assert window._rotate_actions[90].isChecked()
    window._set_video_rotate(0)
    assert window._rotate_actions[0].isChecked()


def test_zoom_osd(window, monkeypatch):
    messages = []
    monkeypatch.setattr(window.video_area, "show_osd", messages.append)
    window._adjust_zoom(0.1)
    assert any("缩放" in m for m in messages)
    window._reset_zoom()
    assert any("100%" in m for m in messages)


def test_adjustments_reset_on_new_file(window, qtbot):
    window._adjust_sub_delay(0.3)
    window._cycle_aspect_override()
    window.open_path(MEDIA / "plain.mkv")
    qtbot.waitUntil(lambda: window.playback.duration() is not None, timeout=15000)
    assert window.playback.sub_delay() == 0.0
    assert window._aspect_override is None
    assert window._aspect_actions[None].isChecked()
    window.close()


# ---- 音画同步 ----


def test_delays_adjust_and_reset(window):
    window._adjust_sub_delay(0.1)
    window._adjust_sub_delay(0.1)
    assert window.playback.sub_delay() == pytest.approx(0.2, abs=1e-3)
    window._adjust_sub_delay(0)
    assert window.playback.sub_delay() == 0.0
    window._adjust_audio_delay(-0.1)
    assert window.playback.audio_delay() == pytest.approx(-0.1, abs=1e-3)
    window._adjust_audio_delay(0)
    assert window.playback.audio_delay() == 0.0


# ---- AB 循环 ----


def test_ab_loop_cycle_sets_then_clears(window, monkeypatch):
    positions = iter([3.0, 5.0, None])
    monkeypatch.setattr(window.playback, "position", lambda: next(positions, None))

    window._cycle_ab_loop()
    assert window._ab_a == pytest.approx(3.0)
    assert window._ab_b is None
    assert "终点" in window.act_ab_loop.text()
    assert window.timeline._loop_range is None  # 两点齐全才显示区间

    window._cycle_ab_loop()
    assert window._ab_b == pytest.approx(5.0)
    assert "清除" in window.act_ab_loop.text()
    assert window.timeline._loop_range is not None

    window._cycle_ab_loop()
    assert window._ab_a is None and window._ab_b is None
    assert window.timeline._loop_range is None
    assert "起点" in window.act_ab_loop.text()


def test_ab_loop_rejects_b_not_after_a(window, monkeypatch):
    monkeypatch.setattr(window.playback, "position", lambda: 5.0)
    window._cycle_ab_loop()
    window._cycle_ab_loop()  # B 与 A 同点 → 拒绝
    assert window._ab_b is None


def test_ab_loop_requires_media(window):
    window._cycle_ab_loop()  # 无文件 → position None → 不设置
    assert window._ab_a is None
    assert "起点" in window.act_ab_loop.text()


# ---- 截图 ----


def test_screenshot_requires_media(window, monkeypatch):
    messages = []
    monkeypatch.setattr(window.video_area, "show_osd", messages.append)
    window._take_screenshot()
    assert any("先打开视频" in m for m in messages)


def test_screenshot_targets_configured_directory(window, qtbot, tmp_path, monkeypatch):
    window.open_path(MEDIA / "plain.mkv")
    qtbot.waitUntil(lambda: window.playback.duration() is not None, timeout=15000)
    saved = []
    monkeypatch.setattr(window, "_screenshot_directory", lambda: tmp_path / "shots")
    monkeypatch.setattr(window.playback, "screenshot_to_file", lambda p: saved.append(Path(p)) or True)
    window._take_screenshot()
    assert saved
    assert saved[0].parent == tmp_path / "shots"
    assert saved[0].suffix == ".png"
    assert "plain" in saved[0].stem
    window.close()


# ---- 章节 ----


def test_chapter_menu_and_navigation(window, qtbot):
    window.open_path(CHAPTERS / "chapters.mkv")
    qtbot.waitUntil(lambda: bool(window.playback.chapters()), timeout=15000)
    window.playback.pause()
    chapters = window.playback.chapters()
    assert [c.title for c in chapters] == ["开场", "中段", "结尾"]
    assert window.timeline._chapters  # 进度条刻度已随信号更新

    window._rebuild_chapter_menu()
    items = window._chapter_menu.actions()[3:]  # 前 3 项：上一章/下一章/分隔线
    assert len(items) == 3
    assert "开场" in items[0].text()

    items[2].trigger()
    qtbot.waitUntil(lambda: window.playback.current_chapter() == 2, timeout=15000)
    window._jump_chapter(-1)
    qtbot.waitUntil(lambda: window.playback.current_chapter() == 1, timeout=15000)
    window.close()


def test_chapter_jump_without_chapters(window):
    window._jump_chapter(+1)  # 无文件 → 仅 OSD 提示，不崩溃
    assert window.playback.current_chapter() is None


# ---- 窗口置顶与画中画 ----


def test_topmost_toggle(window):
    window.show()
    window.act_topmost.trigger()  # checkable：trigger 翻转后 handler 读取新状态
    assert window.windowFlags() & Qt.WindowStaysOnTopHint
    window.act_topmost.trigger()
    assert not (window.windowFlags() & Qt.WindowStaysOnTopHint)
    window.close()


def test_pip_requires_media(window, monkeypatch):
    messages = []
    monkeypatch.setattr(window.video_area, "show_osd", messages.append)
    window._toggle_pip()
    assert not window._pip_active
    assert any("先打开视频" in m for m in messages)


def test_pip_enter_and_exit(window, qtbot):
    window.show()
    window.open_path(MEDIA / "plain.mkv")
    qtbot.waitUntil(lambda: window.playback.duration() is not None, timeout=15000)
    original = window.geometry()

    window._toggle_pip()
    assert window._pip_active
    assert window.windowFlags() & Qt.WindowStaysOnTopHint
    assert window.width() < 600
    assert "退出" in window.act_pip.text()
    assert window.video_area.control_bar.pip_btn.isChecked()

    window._toggle_pip()
    assert not window._pip_active
    assert not (window.windowFlags() & Qt.WindowStaysOnTopHint)
    restored = window.geometry()
    assert (restored.x(), restored.y()) == (original.x(), original.y())
    assert (restored.width(), restored.height()) == (original.width(), original.height())
    assert not window.video_area.control_bar.pip_btn.isChecked()
    window.close()


# ---- 进度条绘制 ----


def test_timeline_slider_loop_and_chapters():
    slider = TimelineSlider()
    slider.resize(400, 22)
    slider.set_position(4.0, 12.0)
    slider.set_covered([(0.0, 3.0)])
    slider.set_chapters([0.0, 4.0, 8.0])
    slider.set_loop_range(2.0, 6.0)
    assert slider._loop_range == (2.0, 6.0)
    slider.grab()  # 触发绘制，不崩溃即通过
    slider.set_loop_range(None, None)
    assert slider._loop_range is None
