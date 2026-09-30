from uuid import uuid4

from player.single_instance import SingleInstance


def test_second_instance_forwards_media_open_to_primary(qapp, qtbot):
    server_name = f"yingxu-test-{uuid4().hex}"
    primary = SingleInstance(server_name)
    secondary = SingleInstance(server_name)

    assert primary.is_primary
    assert not secondary.is_primary

    with qtbot.waitSignal(primary.request_received, timeout=1000) as request:
        assert secondary.forward("/影片/第一集.mkv")

    assert request.args == ["/影片/第一集.mkv"]


def test_second_instance_can_request_window_activation(qapp, qtbot):
    server_name = f"yingxu-test-{uuid4().hex}"
    primary = SingleInstance(server_name)
    secondary = SingleInstance(server_name)

    assert primary.is_primary

    with qtbot.waitSignal(primary.request_received, timeout=1000) as request:
        # Send another request after the event loop begins waiting.
        assert secondary.forward(None)

    assert request.args == [None]
