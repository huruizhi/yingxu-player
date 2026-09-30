"""字幕存储、SRT 解析/生成与区间集合的单元测试。"""

from pathlib import Path

from player.ai.base import Segment
from player.ai.subtitles import (
    IntervalSet,
    SubtitleStore,
    format_srt_time,
    gaps_in_ranges,
    parse_srt,
    to_srt,
)


class TestSrtFormat:
    def test_format_time(self):
        assert format_srt_time(0) == "00:00:00,000"
        assert format_srt_time(3661.5) == "01:01:01,500"
        assert format_srt_time(-1) == "00:00:00,000"

    def test_round_trip_with_multiline_chinese(self):
        segs = [
            Segment(1.0, 2.5, "你好，世界"),
            Segment(3.0, 4.0, "第二行\n第三行"),
        ]
        parsed = parse_srt(to_srt(segs))
        assert len(parsed) == 2
        assert parsed[0].start == 1.0 and parsed[0].end == 2.5
        assert parsed[0].text == "你好，世界"
        assert parsed[1].text == "第二行\n第三行"

    def test_parse_tolerates_index_lines_and_blank_blocks(self):
        srt = "\n\n1\n00:00:01,000 --> 00:00:02,000\nhello\n\n garbage \n\n2\n00:00:03,000 --> 00:00:04,000\nworld\n"
        segs = parse_srt(srt)
        assert [s.text for s in segs] == ["hello", "world"]


class TestIntervalSet:
    def test_add_and_merge(self):
        s = IntervalSet()
        s.add(0, 10)
        s.add(20, 30)
        s.add(8, 22)
        assert s.ranges() == [(0.0, 30.0)]

    def test_gaps_in(self):
        s = IntervalSet()
        s.add(10, 20)
        assert s.gaps_in(0, 30) == [(0.0, 10.0), (20.0, 30.0)]
        assert s.gaps_in(12, 15) == []
        assert s.gaps_in(15, 25) == [(20.0, 25.0)]
        assert s.gaps_in(20, 10) == []

    def test_total_and_clear(self):
        s = IntervalSet()
        s.add(0, 5)
        s.add(5, 8)
        assert s.total() == 8.0
        s.clear()
        assert s.ranges() == [] and s.total() == 0.0

    def test_gaps_in_ranges_pure_function(self):
        ranges = [(0, 10), (20, 30)]
        assert gaps_in_ranges(ranges, 5, 25) == [(10.0, 20.0)]
        assert gaps_in_ranges(ranges, 100, 200) == [(100.0, 200.0)]


class TestSubtitleStore:
    def make_store(self, tmp_path: Path) -> SubtitleStore:
        return SubtitleStore(tmp_path / "cache")

    def test_add_and_current_lookup(self, tmp_path):
        store = self.make_store(tmp_path)
        store.add_segments([Segment(10.0, 12.0, "b"), Segment(0.0, 2.0, "a")])
        assert store.current(1.0).text == "a"
        assert store.current(11.0).text == "b"
        assert store.current(5.0) is None  # 间隙
        assert store.current(13.0) is None  # 结束之后
        assert store.current(-1) is None

    def test_cache_round_trip(self, tmp_path):
        media = tmp_path / "ep1.mkv"
        media.write_bytes(b"x")
        store = self.make_store(tmp_path)
        store.add_segments([Segment(0.0, 1.0, "hello")])
        store.save_cache(media)

        store2 = self.make_store(tmp_path)
        assert store2.try_load_cache(media, duration=600.0) is True
        assert store2.current(0.5).text == "hello"
        assert store2.covered.ranges() == [(0.0, 600.0)]

    def test_try_load_cache_missing_returns_false(self, tmp_path):
        media = tmp_path / "ep1.mkv"
        media.write_bytes(b"x")
        store = self.make_store(tmp_path)
        assert store.try_load_cache(media, 100.0) is False

    def test_fingerprint_is_stable_and_path_distinct(self, tmp_path):
        a = tmp_path / "a.mkv"
        b = tmp_path / "b.mkv"
        a.write_bytes(b"x")
        b.write_bytes(b"x")
        store = self.make_store(tmp_path)
        assert store.fingerprint(a) == store.fingerprint(a)
        assert store.fingerprint(a) != store.fingerprint(b)

    def test_export_srt_avoids_overwrite(self, tmp_path):
        media = tmp_path / "ep1.mkv"
        media.write_bytes(b"x")
        (tmp_path / "ep1.srt").write_text("existing", encoding="utf-8")
        store = self.make_store(tmp_path)
        store.add_segments([Segment(0.0, 1.0, "hi")])
        dest = store.export_srt(media)
        assert dest.name == "ep1.ai.srt"

    def test_coverage_ratio(self, tmp_path):
        store = self.make_store(tmp_path)
        store.covered.add(0, 50)
        assert store.coverage_ratio(200.0) == 0.25
