from player.updates import is_newer_version, version_tuple


def test_version_tuple_accepts_release_tags():
    assert version_tuple("v1.2.3") == (1, 2, 3)
    assert version_tuple("1.2.3-rc.1") == (1, 2, 3)


def test_version_tuple_rejects_unparseable_versions():
    assert version_tuple("latest") is None
    assert version_tuple("1.2") is None


def test_detects_only_newer_versions():
    assert is_newer_version("v0.2.0", "0.1.0")
    assert not is_newer_version("0.1.0", "0.1.0")
    assert not is_newer_version("0.0.9", "0.1.0")
    assert not is_newer_version("latest", "0.1.0")
