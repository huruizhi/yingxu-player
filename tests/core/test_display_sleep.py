from player.core.display_sleep import DisplaySleepInhibitor


class FakeBackend:
    def __init__(self):
        self.acquired = 0
        self.released = 0

    def acquire(self):
        self.acquired += 1
        return True

    def release(self):
        self.released += 1


def test_inhibitor_is_idempotent_and_releases_after_playback():
    backend = FakeBackend()
    inhibitor = DisplaySleepInhibitor(backend=backend)

    inhibitor.set_playing_video(True)
    inhibitor.set_playing_video(True)
    assert inhibitor.inhibited
    assert backend.acquired == 1

    inhibitor.set_playing_video(False)
    inhibitor.close()
    assert not inhibitor.inhibited
    assert backend.released == 1


def test_inhibitor_does_nothing_when_platform_backend_is_unavailable():
    inhibitor = DisplaySleepInhibitor(backend_factory=lambda: None)

    inhibitor.set_playing_video(True)

    assert not inhibitor.inhibited
