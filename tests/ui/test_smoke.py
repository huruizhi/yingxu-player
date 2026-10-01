"""主窗口冒烟测试：真实 mpv 内核（离屏）+ 真实播放列表逻辑。

AI 字幕默认关闭（OFF），避免单测触发模型下载；AI 真实链路由
scripts/smoke_ai.py 单独验证。
"""

from pathlib import Path

import pytest

from player.core.playback import Playback
from player.core.settings import Settings, SubtitleSource
from player.core.store import Store
from player.ui.main_window import MainWindow

MEDIA = Path(__file__).resolve().parent.parent / "fixtures" / "media"

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture()
def window(tmp_path):
    settings = Settings(subtitle_source=SubtitleSource.OFF)
    store = Store(tmp_path / "state.json")
    playback = Playback(video_out="null")  # 离屏测试无渲染上下文，用 null 视频输出
    win = MainWindow(settings, store, tmp_path / "sub_cache", playback=playback)
    yield win
    try:
        win.video_area.mpv_widget.shutdown()
        playback.terminate()
    except Exception:
        pass


def test_window_init(window):
    assert window.windowTitle() == "映序"
    assert window.playback is not None
    window.close()


def test_open_file_builds_directory_playlist(window, qtbot):
    window.open_path(MEDIA / "speech.mp4")
    assert len(window.playlist) == 3  # 同目录三个媒体文件
    assert window.playlist.current_item == MEDIA / "speech.mp4"
    assert window.windowTitle().startswith("speech.mp4")
    window.close()


def test_open_directory_plays_first(window, qtbot):
    window.open_path(MEDIA)
    assert len(window.playlist) == 3
    assert window.playlist.current_item is not None
    assert window.settings.recent_directories[0] == str(MEDIA)
    assert window._dialog_start_directory() == str(MEDIA)
    assert window._recent_dirs_menu.actions()[0].toolTip() == str(MEDIA)
    window.close()


def test_recent_directory_shortcut_opens_saved_directory(window, monkeypatch):
    window.settings.remember_directory(MEDIA)
    window._refresh_recent_directories()
    opened = []
    monkeypatch.setattr(window, "open_path", opened.append)

    window.video_area.empty_state.recent_layout.itemAt(1).widget().click()

    assert opened == [MEDIA]
    window.close()


def test_playback_reaches_playing_state(window, qtbot):
    window.open_path(MEDIA / "plain.mkv")
    # mpv 事件线程 → Qt 信号需要事件循环运转
    qtbot.waitUntil(lambda: window.playback.duration() is not None, timeout=15000)
    assert window.playback.duration() == pytest.approx(12.0, abs=1.0)
    window.close()


def test_mark_credits_persists(window, qtbot, tmp_path):
    window.open_path(MEDIA / "plain.mkv")
    qtbot.waitUntil(lambda: window.playback.duration() is not None, timeout=15000)
    qtbot.waitUntil(lambda: window.playback.position() is not None, timeout=15000)
    window._mark_credits()
    assert window.skipper.has_mark()
    assert window.store.get_credits_start(MEDIA / "plain.mkv") is not None
    window.close()


def test_manual_skip_advances_playlist(window, qtbot):
    window.open_path(MEDIA)
    qtbot.waitUntil(lambda: window.playback.duration() is not None, timeout=15000)
    first = window.playlist.current_item
    window.skipper.manual_skip()
    assert window.playlist.current_item != first
    window.close()


def test_subtitle_policy_auto_enables_for_unsubtitled_file(window, qtbot):
    window.settings.subtitle_source = SubtitleSource.AUTO
    window.open_path(MEDIA / "plain.mkv")
    qtbot.waitUntil(lambda: window.playback.sub_tracks() is not None, timeout=15000)
    # 无内置字幕 → AUTO 策略下 AI 字幕应标记为启用（但 duration 就绪前不启动线程）
    qtbot.waitUntil(lambda: window._ai_active, timeout=15000)
    window.close()


def test_subtitle_policy_auto_disables_when_embedded_subs(window, qtbot):
    window.settings.subtitle_source = SubtitleSource.AUTO
    window.open_path(MEDIA / "test_with_subs.mkv")
    qtbot.waitUntil(lambda: bool(window.playback.sub_tracks()), timeout=15000)
    qtbot.wait(500)  # 等策略应用
    assert window._ai_active is False  # 有内置字幕 → 不启用 AI
    window.close()


def test_fullscreen_toggle(window, qtbot):
    window.show()
    window.toggle_fullscreen()
    assert window.isFullScreen()
    assert window.act_fullscreen.text() == "退出全屏"
    window.toggle_fullscreen()
    assert not window.isFullScreen()
    assert window.act_fullscreen.text() == "进入全屏"
    window.close()


def test_auto_hide_hides_controls_when_idle(window, qtbot):
    window.open_path(MEDIA / "plain.mkv")
    qtbot.waitUntil(lambda: window.playback.duration() is not None, timeout=15000)
    window._auto_hide._last_activity -= 10  # 回拨活动时钟模拟长时间无操作
    window._on_tick()
    assert window.video_area.controls_shown is False
    window._on_mouse_activity()
    assert window.video_area.controls_shown is True
    window.close()


def test_playlist_button_unchecks_when_drawer_auto_hides(window, qtbot):
    window.show()
    window.open_path(MEDIA / "plain.mkv")
    drawer = window.video_area.drawer
    drawer._auto_hide.setInterval(40)

    window.playlist_btn.click()
    assert drawer.isVisible()
    assert window.playlist_btn.isChecked()

    qtbot.waitUntil(lambda: not drawer.isVisible(), timeout=1500)
    assert not window.playlist_btn.isChecked()
    window.close()


def test_secondary_launch_opens_media_in_existing_window(window, monkeypatch):
    opened = []
    monkeypatch.setattr(window, "open_path", opened.append)

    window.handle_secondary_launch("/Movies/Second.mkv")

    assert window.isVisible()
    assert opened == [Path("/Movies/Second.mkv")]
    window.close()
