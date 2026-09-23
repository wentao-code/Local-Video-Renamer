import json
import threading
from urllib.request import Request, urlopen

from app.plugins.local_video_renamer_adapter import LocalVideoRenamerAdapter


def test_adapter_manifest_declares_control_contract_without_button_bindings():
    adapter = LocalVideoRenamerAdapter()

    manifest = adapter.manifest()

    assert manifest["plugin_id"] == "local_video_renamer"
    assert manifest["protocol"]["status"] == "/api/v1/status"
    assert manifest["protocol"]["commands"] == "/api/v1/commands"
    assert manifest["reporting"]["client"] == "feishu_plugin_sdk.ReportClient"
    assert {action["name"] for action in manifest["actions"]} == {"start", "stop", "status"}
    assert manifest["integration"]["bound"] is False
    assert "GUI" in manifest["integration"]["message"]


def test_unbound_adapter_rejects_commands_without_touching_business_logic():
    adapter = LocalVideoRenamerAdapter()
    assert adapter.status()["control_bound"] is False

    start = adapter.handle_command("start", "req-start")
    stop = adapter.handle_command("stop", "req-stop")

    assert start["accepted"] is False
    assert stop["accepted"] is False
    assert start["status"] == "rejected"
    assert start["request_id"] == "req-start"
    assert "尚未绑定" in start["reason"]


def test_adapter_invokes_only_explicitly_injected_handlers():
    calls = []
    adapter = LocalVideoRenamerAdapter(
        start_handler=lambda request_id: calls.append(("start", request_id))
        or {"task_id": "task-1"},
        stop_handler=lambda request_id: calls.append(("stop", request_id))
        or {"task_id": "task-1"},
    )

    assert adapter.handle_command("start", "req-start")["accepted"] is True
    assert adapter.handle_command("stop", "req-stop")["accepted"] is True
    assert calls == [("start", "req-start"), ("stop", "req-stop")]


def test_adapter_control_server_exposes_authenticated_status_and_gui_queue():
    calls = []
    adapter = LocalVideoRenamerAdapter(
        start_handler=lambda request_id: calls.append(request_id)
        or {"task_id": "task-1"},
    )
    server = adapter.create_control_server(token="secret", port=0, command_timeout=1)
    server.start_in_thread()
    try:
        request = Request(
            server.base_url + "/api/v1/status",
            headers={"Authorization": "Bearer secret"},
        )
        with urlopen(request, timeout=2) as response:
            status = json.loads(response.read())
        assert status["plugin_id"] == "local_video_renamer"
        assert status["control_bound"] is True

        manifest_request = Request(
            server.base_url + "/api/v1/manifest",
            headers={"Authorization": "Bearer secret"},
        )
        with urlopen(manifest_request, timeout=2) as response:
            manifest = json.loads(response.read())
        assert manifest["plugin_id"] == "local_video_renamer"
        assert manifest["protocol"]["manifest"] == "/api/v1/manifest"

        command_request = Request(
            server.base_url + "/api/v1/commands",
            data=json.dumps({"request_id": "req-1", "action": "start"}).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
            },
        )
        result = []
        thread = threading.Thread(
            target=lambda: result.append(json.loads(urlopen(command_request, timeout=2).read()))
        )
        thread.start()
        assert server.wait_for_command(1)
        assert server.drain() == 1
        thread.join(timeout=2)

        assert result[0]["accepted"] is True
        assert calls == ["req-1"]
    finally:
        server.stop()
