"""片尾跳过状态机的单元测试。"""

from player.ai.skip import CreditsSkipper
from player.core.store import Store


def make_skipper(tmp_path, mark=None, enabled=True, store_dir="state.json"):
    store = Store(tmp_path / store_dir)
    media = tmp_path / "ep1.mkv"
    media.write_bytes(b"")
    if mark is not None:
        store.mark_credits(media, mark)
    skipper = CreditsSkipper(store)
    skipper.enabled = enabled
    skipper.on_file_opened(media)
    fired = []
    skipper.on_skip = lambda: fired.append(1)
    return skipper, fired, media


class TestCreditsSkipper:
    def test_triggers_once_inside_window(self, tmp_path):
        skipper, fired, _ = make_skipper(tmp_path, mark=1500.0, enabled=True)
        assert skipper.on_position(1000.0) is False
        assert skipper.on_position(1501.0) is True  # 进入片尾区间
        assert fired == [1]
        assert skipper.on_position(1520.0) is False  # 只触发一次
        assert skipper.on_position(1490.0) is False

    def test_disabled_never_triggers(self, tmp_path):
        skipper, fired, _ = make_skipper(tmp_path, mark=1500.0, enabled=False)
        assert skipper.on_position(1510.0) is False
        assert fired == []

    def test_no_mark_never_triggers(self, tmp_path):
        skipper, fired, _ = make_skipper(tmp_path, mark=None, enabled=True)
        assert skipper.on_position(1510.0) is False
        assert fired == []

    def test_outside_grace_window_not_triggered(self, tmp_path):
        skipper, fired, _ = make_skipper(tmp_path, mark=1500.0, enabled=True)
        assert skipper.on_position(1500.0 + 91.0) is False
        assert fired == []

    def test_reopen_resets_triggered(self, tmp_path):
        skipper, fired, media = make_skipper(tmp_path, mark=1500.0, enabled=True)
        assert skipper.on_position(1505.0) is True
        skipper.on_file_opened(media)
        assert skipper.on_position(1506.0) is True
        assert fired == [1, 1]

    def test_manual_skip_ignores_enabled_and_mark(self, tmp_path):
        skipper, fired, _ = make_skipper(tmp_path, mark=None, enabled=False)
        assert skipper.manual_skip() is True
        assert fired == [1]

    def test_has_mark(self, tmp_path):
        skipper, _, _ = make_skipper(tmp_path, mark=100.0, enabled=True, store_dir="s1.json")
        assert skipper.has_mark() is True
        skipper2, _, _ = make_skipper(tmp_path, mark=None, enabled=True, store_dir="s2.json")
        assert skipper2.has_mark() is False
