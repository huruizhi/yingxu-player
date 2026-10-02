"""播放内核新增能力：截图、音画同步、画面调整、AB 循环、章节。

使用 vo=null 的真实 mpv：这些能力全部是属性/命令层，不依赖渲染。
共享模块级实例，避免在 CI 上高频创建/销毁 mpv 进程内上下文；
且必须先建 QApplication（与生产启动顺序一致）再创建 mpv 实例——
CI runner 上"先建 mpv 后建 QApplication"的进程会在后续 mpv 创建时段错误。
"""

import pytest

from player.core.playback import Playback

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(scope="module")
def playback():
    player = Playback(video_out="null", audio_out="null")
    yield player
    player.terminate()


def test_sub_and_audio_delay_roundtrip(playback):
    playback.set_sub_delay(0.3)
    playback.set_audio_delay(-0.2)
    assert playback.sub_delay() == pytest.approx(0.3, abs=1e-3)
    assert playback.audio_delay() == pytest.approx(-0.2, abs=1e-3)
    playback.set_sub_delay(0)
    playback.set_audio_delay(0)
    assert playback.sub_delay() == 0.0
    assert playback.audio_delay() == 0.0


def test_video_zoom_clamped_and_reset(playback):
    assert playback.adjust_video_zoom(10) == pytest.approx(3.0)
    assert playback.adjust_video_zoom(-10) == pytest.approx(-1.0)
    assert playback.adjust_video_zoom(0.1) == pytest.approx(-0.9)
    playback.reset_video_zoom()
    assert playback.video_zoom() == 0.0


def test_video_rotate_validates(playback):
    playback.set_video_rotate(90)
    assert playback._int_prop("video-rotate") == 90
    with pytest.raises(ValueError):
        playback.set_video_rotate(45)


def test_aspect_override_accepts_and_resets(playback):
    playback.set_aspect_override("16:9")
    playback.set_aspect_override(None)  # 不抛异常即通过；"no" 由 mpv 接受


def test_ab_loop_roundtrip(playback):
    playback.set_ab_loop(1.5, 4.0)
    assert playback.ab_loop() == (pytest.approx(1.5), pytest.approx(4.0))
    playback.set_ab_loop(None, None)
    assert playback.ab_loop() == (None, None)


def test_state_empty_without_file(playback):
    assert playback.chapters() == []
    assert playback.current_chapter() is None
    assert playback.video_size() is None


def test_screenshot_without_file_fails(playback, tmp_path):
    target = tmp_path / "shot.png"
    assert playback.screenshot_to_file(target) is False
    assert not target.exists()


def test_terminate_is_idempotent():
    player = Playback(video_out="null", audio_out="null")
    player.terminate()
    player.terminate()
