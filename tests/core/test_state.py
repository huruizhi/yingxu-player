"""settings / store / storage 持久化模块的单元测试。"""

from pathlib import Path

import pytest

from player.core.settings import AI_MODELS, Settings, SubtitleSource
from player.core.storage import load_json, save_json_atomic
from player.core.store import Store


class TestStorage:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "x.json"
        save_json_atomic(path, {"a": 1, "b": "中文"})
        assert load_json(path, {}) == {"a": 1, "b": "中文"}

    def test_load_missing_returns_default(self, tmp_path):
        assert load_json(tmp_path / "nope.json", {"d": 1}) == {"d": 1}

    def test_load_corrupt_returns_default(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_json(path, {"d": 1}) == {"d": 1}

    def test_atomic_write_leaves_no_tmp(self, tmp_path):
        path = tmp_path / "x.json"
        save_json_atomic(path, {"a": 1})
        assert list(tmp_path.iterdir()) == [path]


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.subtitle_source is SubtitleSource.AUTO
        assert s.ai_model == "small"
        assert s.skip_credits_enabled is False
        assert s.volume == 60

    def test_round_trip(self, tmp_path):
        path = tmp_path / "settings.json"
        s = Settings(subtitle_source=SubtitleSource.FORCE_AI, ai_model="base", volume=80)
        s.save(path)
        s2 = Settings.load(path)
        assert s2.subtitle_source is SubtitleSource.FORCE_AI
        assert s2.ai_model == "base"
        assert s2.volume == 80

    def test_unknown_keys_ignored(self, tmp_path):
        path = tmp_path / "settings.json"
        save_json_atomic(path, {"ai_model": "base", "future_key": 1})
        assert Settings.load(path).ai_model == "base"

    def test_invalid_values_fall_back(self, tmp_path):
        path = tmp_path / "settings.json"
        save_json_atomic(path, {"ai_model": "gpt-9", "volume": 9999, "speed": 0.01})
        s = Settings.load(path)
        assert s.ai_model in AI_MODELS
        assert s.volume == 130
        assert s.speed == 1.0

    def test_subtitle_source_invalid_falls_back_to_auto(self, tmp_path):
        path = tmp_path / "settings.json"
        save_json_atomic(path, {"subtitle_source": "????"})
        assert Settings.load(path).subtitle_source is SubtitleSource.AUTO

    def test_recent_directories_round_trip_and_order(self, tmp_path):
        path = tmp_path / "settings.json"
        a, b = tmp_path / "a", tmp_path / "b"
        settings = Settings(file_path=path)
        settings.remember_directory(a)
        settings.remember_directory(b)
        settings.remember_directory(a)
        settings.save()

        assert Settings.load(path).recent_directories == [str(a), str(b)]


@pytest.fixture()
def media(tmp_path: Path) -> Path:
    f = tmp_path / "ep1.mkv"
    f.write_bytes(b"")
    return f


class TestStoreProgress:
    def test_round_trip_and_resume_gate(self, media, tmp_path):
        store = Store(tmp_path / "state.json")
        store.set_progress(media, position=120.0, duration=1800.0)
        store.save()

        reloaded = Store(tmp_path / "state.json")
        assert reloaded.get_progress(media) == 120.0

    def test_too_early_not_resumed(self, media, tmp_path):
        store = Store(tmp_path / "state.json")
        store.set_progress(media, position=10.0, duration=1800.0)
        assert store.get_progress(media) is None

    def test_near_end_restarts(self, media, tmp_path):
        store = Store(tmp_path / "state.json")
        store.set_progress(media, position=1797.0, duration=1800.0)
        assert store.get_progress(media) is None

    def test_short_file_not_resumed(self, media, tmp_path):
        store = Store(tmp_path / "state.json")
        store.set_progress(media, position=40.0, duration=50.0)
        assert store.get_progress(media) is None


class TestStoreCredits:
    def test_file_level_precedence_over_dir(self, tmp_path):
        ep1 = tmp_path / "ep1.mkv"
        ep2 = tmp_path / "ep2.mkv"
        store = Store(tmp_path / "state.json")
        store.mark_credits(ep1, 1500.0)
        store.mark_credits(ep2, 1400.0)  # 目录级被 ep2 的标记覆盖
        # 目录级记录对同目录其他文件生效
        other = tmp_path / "ep3.mkv"
        assert store.get_credits_start(other) == 1400.0
        # 文件级优先于目录级
        assert store.get_credits_start(ep1) == 1500.0

    def test_clear_removes_file_and_dir(self, tmp_path):
        ep1 = tmp_path / "ep1.mkv"
        store = Store(tmp_path / "state.json")
        store.mark_credits(ep1, 1500.0)
        assert store.clear_credits(ep1) is True
        assert store.get_credits_start(ep1) is None
        assert store.get_credits_start(tmp_path / "ep2.mkv") is None
        assert store.clear_credits(ep1) is False

    def test_no_credits_returns_none(self, media, tmp_path):
        assert Store(tmp_path / "state.json").get_credits_start(media) is None

    def test_persistence_across_instances(self, tmp_path):
        store = Store(tmp_path / "state.json")
        store.mark_credits(tmp_path / "ep1.mkv", 900.0)
        reloaded = Store(tmp_path / "state.json")
        assert reloaded.get_credits_start(tmp_path / "ep9.mkv") == 900.0
        assert "files" in reloaded.all_credits()

    def test_progress_pruned_to_cap(self, tmp_path):
        store = Store(tmp_path / "state.json")
        for i in range(510):
            f = tmp_path / f"v{i}.mkv"
            store.set_progress(f, 60.0, 600.0)
        assert len(store._progress) == 500
