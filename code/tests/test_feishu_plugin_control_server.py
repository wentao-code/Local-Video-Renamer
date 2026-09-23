import threading

import pytest

from app.plugins import local_video_renamer_control_server as control_server


def test_parser_reads_local_adapter_environment(monkeypatch):
    monkeypatch.setenv("FEISHU_CONTROL_TOKEN", "secret")
    monkeypatch.setenv("LOCAL_VIDEO_RENAMER_CONTROL_HOST", "127.0.0.1")
    monkeypatch.setenv("LOCAL_VIDEO_RENAMER_CONTROL_PORT", "8763")
    monkeypatch.setenv("LOCAL_VIDEO_RENAMER_CONTROL_TIMEOUT", "1.5")

    args = control_server.build_parser().parse_args([])

    assert args.token == "secret"
    assert args.host == "127.0.0.1"
    assert args.port == 8763
    assert args.timeout == 1.5


def test_run_service_requires_control_token():
    with pytest.raises(ValueError, match="FEISHU_CONTROL_TOKEN"):
        control_server.run_service(
            host="127.0.0.1",
            port=0,
            token="",
            command_timeout=1,
            stop_event=threading.Event(),
        )


def test_run_service_starts_drains_and_stops_injected_control(monkeypatch):
    calls = []
    stop_event = threading.Event()

    class FakeControl:
        base_url = "http://127.0.0.1:8763"

        def start_in_thread(self):
            calls.append("start")

        def drain(self):
            calls.append("drain")
            stop_event.set()

        def stop(self):
            calls.append("stop")

    class FakeAdapter:
        def create_control_server(self, **kwargs):
            calls.append(kwargs)
            return FakeControl()

    monkeypatch.setattr(control_server, "LocalVideoRenamerAdapter", FakeAdapter)

    control_server.run_service(
        host="127.0.0.1",
        port=8763,
        token="secret",
        command_timeout=1,
        stop_event=stop_event,
    )

    assert calls[0] == {
        "token": "secret",
        "host": "127.0.0.1",
        "port": 8763,
        "command_timeout": 1,
    }
    assert calls[1:] == ["start", "drain", "stop"]
