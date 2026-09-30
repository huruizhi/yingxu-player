from player.app import parse_launch_args


def test_launcher_switch_is_not_treated_as_media():
    args, smoke, media = parse_launch_args(["Yingxu", "-B", "--smoke"])

    assert args == ["Yingxu", "-B"]
    assert smoke
    assert media is None


def test_qt_option_value_is_not_treated_as_media():
    args, smoke, media = parse_launch_args(["Yingxu", "-platform", "cocoa", "/Movies/example.mkv"])

    assert args == ["Yingxu", "-platform", "cocoa", "/Movies/example.mkv"]
    assert not smoke
    assert str(media) == "/Movies/example.mkv"


def test_double_dash_allows_leading_hyphen_media_name():
    args, smoke, media = parse_launch_args(["Yingxu", "--", "-B"])

    assert args == ["Yingxu", "-B"]
    assert not smoke
    assert str(media) == "-B"
