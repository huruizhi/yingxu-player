from pathlib import Path

from player.core.airplay import can_airplay


def test_airplay_file_container_support_is_explicit():
    assert can_airplay(Path("movie.mp4"))
    assert can_airplay(Path("movie.MOV"))
    assert can_airplay(Path("movie.m4v"))
    assert not can_airplay(Path("movie.mkv"))
    assert not can_airplay(Path("movie.avi"))
