"""播放列表与目录扫描的单元测试。"""

from pathlib import Path

from player.core.playlist import LoopMode, Playlist, natural_key, scan_media_files


def make_files(tmp_path: Path, names: list[str]) -> list[Path]:
    for name in names:
        (tmp_path / name).write_bytes(b"")
    return sorted(tmp_path.iterdir())


class TestNaturalKey:
    def test_number_aware_order(self):
        assert natural_key("ep2") < natural_key("ep10")

    def test_mixed_digit_and_text_chunks_compare(self):
        # 数字块与文本块混排时不抛 TypeError
        assert natural_key("1x") != natural_key("ax")

    def test_leading_zeros_equal_numbers(self):
        assert natural_key("ep01") == natural_key("ep1")


class TestScanMediaFiles:
    def test_scans_and_natural_sorts(self, tmp_path):
        make_files(tmp_path, ["EP1.mkv", "EP2.mkv", "EP10.mkv", "EP3.mkv"])
        result = scan_media_files(tmp_path)
        assert [p.name for p in result] == ["EP1.mkv", "EP2.mkv", "EP3.mkv", "EP10.mkv"]

    def test_filters_non_media_and_hidden(self, tmp_path):
        make_files(tmp_path, ["a.mkv", "b.txt", "c.jpg", ".hidden.mkv", "._resource.mkv"])
        result = scan_media_files(tmp_path)
        assert [p.name for p in result] == ["a.mkv"]

    def test_audio_files_included(self, tmp_path):
        make_files(tmp_path, ["01.flac", "02.mp3", "note.md"])
        result = scan_media_files(tmp_path)
        assert [p.name for p in result] == ["01.flac", "02.mp3"]

    def test_mkv_preferred_on_same_stem(self, tmp_path):
        make_files(tmp_path, ["ep1.mp4", "ep1.mkv"])
        result = scan_media_files(tmp_path)
        assert result[0].suffix == ".mkv"

    def test_missing_directory_returns_empty(self, tmp_path):
        assert scan_media_files(tmp_path / "nope") == []


class TestPlaylistNavigation:
    def make_playlist(self, n=3, mode=LoopMode.ALL):
        pl = Playlist()
        pl.set_items([Path(f"/m/f{i}.mkv") for i in range(n)])
        pl.set_mode(mode)
        pl.jump_to(0)
        return pl

    def test_empty_playlist_returns_none(self):
        pl = Playlist()
        assert pl.next() is None
        assert pl.previous() is None
        assert pl.current_item is None

    def test_all_mode_wraps(self):
        pl = self.make_playlist(3)
        assert pl.next().name == "f1.mkv"
        assert pl.next().name == "f2.mkv"
        assert pl.next().name == "f0.mkv"  # 回绕

    def test_previous_wraps_backwards(self):
        pl = self.make_playlist(3)
        assert pl.previous().name == "f2.mkv"

    def test_single_mode_auto_repeats(self):
        pl = self.make_playlist(3, LoopMode.SINGLE)
        assert pl.next(auto=True).name == "f0.mkv"

    def test_single_mode_manual_advances(self):
        pl = self.make_playlist(3, LoopMode.SINGLE)
        assert pl.next(auto=False).name == "f1.mkv"

    def test_shuffle_never_repeats_current_at_cycle_edge(self):
        pl = self.make_playlist(5, LoopMode.SHUFFLE)
        seen = [pl.current_item]
        for _ in range(20):
            nxt = pl.next(auto=True)
            assert nxt != seen[-1]  # 换局瞬间也不与上一首重复
            seen.append(nxt)
        assert set(seen) == {Path(f"/m/f{i}.mkv") for i in range(5)}

    def test_shuffle_previous_returns_items(self):
        pl = self.make_playlist(4, LoopMode.SHUFFLE)
        for _ in range(6):
            assert pl.previous() is not None

    def test_jump_to_path_resolves(self, tmp_path):
        (tmp_path / "b.mkv").write_bytes(b"")
        (tmp_path / "a.mkv").write_bytes(b"")
        pl = Playlist()
        pl.load_directory(tmp_path)
        assert pl.jump_to_path(tmp_path / "a.mkv").name == "a.mkv"
        assert pl.current == 0

    def test_set_items_keep_current(self):
        pl = Playlist()
        pl.set_items([Path("/m/a.mkv"), Path("/m/b.mkv")])
        pl.jump_to(1)
        pl.set_items([Path("/m/x.mkv"), Path("/m/b.mkv"), Path("/m/c.mkv")], keep_current=True)
        assert pl.current_item == Path("/m/b.mkv")

    def test_load_directory_positions_on_start_file(self, tmp_path):
        make_files(tmp_path, ["e1.mkv", "e2.mkv", "e3.mkv"])
        pl = Playlist()
        pl.load_directory(tmp_path, start_file=tmp_path / "e2.mkv")
        assert pl.current_item.name == "e2.mkv"
        assert len(pl) == 3
