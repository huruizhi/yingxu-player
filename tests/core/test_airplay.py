from pathlib import Path

import av

from player.core.airplay import can_airplay, remux_to_mp4


def test_airplay_supports_common_video_containers():
    assert can_airplay(Path("movie.mp4"))
    assert can_airplay(Path("movie.MOV"))
    assert can_airplay(Path("movie.m4v"))
    assert can_airplay(Path("movie.mkv"))
    assert can_airplay(Path("movie.avi"))
    assert not can_airplay(Path("subtitles.srt"))


def test_remux_mkv_to_mp4_without_reencoding(tmp_path):
    source = Path(__file__).parents[1] / "fixtures" / "media" / "plain.mkv"
    output = tmp_path / "cast.mp4"

    remux_to_mp4(source, output)

    with av.open(str(source)) as source_container, av.open(str(output)) as output_container:
        source_streams = {stream.type: stream.codec_context.name for stream in source_container.streams}
        output_streams = {stream.type: stream.codec_context.name for stream in output_container.streams}
        assert output_streams == source_streams
        assert output_streams["audio"] == "aac"
        assert abs(output_container.duration - source_container.duration) <= 50_000
