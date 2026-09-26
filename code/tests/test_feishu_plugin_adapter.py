import json
import threading
from types import SimpleNamespace
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
    assert adapter.status()["gui_running"] is False
    assert adapter.status()["task_status_known"] is False

    start = adapter.handle_command("start", "req-start")
    stop = adapter.handle_command("stop", "req-stop")

    assert start["accepted"] is False
    assert stop["accepted"] is False
    assert start["status"] == "rejected"
    assert start["request_id"] == "req-start"
    assert "尚未绑定" in start["reason"]


def test_adapter_publishes_live_queue_state_without_binding_commands():
    adapter = LocalVideoRenamerAdapter()
    adapter.sync_task_queue_status(
        [
            SimpleNamespace(
                task_id=17,
                trace_task_id="trace-17",
                title="扫描本地视频",
                source="主界面",
                status="正在执行",
            ),
            SimpleNamespace(
                task_id=18,
                trace_task_id="trace-18",
                title="导入视频库",
                source="主界面",
                status="等待中",
            ),
        ]
    )

    status = adapter.status()

    assert status["busy"] is True
    assert status["task_id"] == "trace-17"
    assert status["active_tasks"] == [
        {"task_id": "trace-17", "title": "扫描本地视频", "status": "正在执行"}
    ]
    assert status["queue_depth"] == 1
    assert status["queued_tasks"] == [
        {"task_id": "trace-18", "title": "导入视频库", "status": "等待中"}
    ]
    assert status["control_bound"] is False
    assert status["gui_running"] is True
    assert status["task_status_known"] is True


def test_adapter_reports_idle_when_queue_has_no_active_or_waiting_tasks():
    adapter = LocalVideoRenamerAdapter()
    adapter.sync_task_queue_status(
        [SimpleNamespace(task_id=1, trace_task_id="trace-1", title="已完成", status="已完成")]
    )

    status = adapter.status()

    assert status["busy"] is False
    assert status["task_id"] is None
    assert status["queue_depth"] == 0
    assert status["active_tasks"] == []
    assert status["task_status_known"] is True


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


def test_adapter_shutdown_uses_only_an_explicit_idle_gui_handler():
    calls = []
    adapter = LocalVideoRenamerAdapter(
        shutdown_handler=lambda request_id: calls.append(request_id)
        or {"message": "关闭请求已接受"}
    )
    adapter.update_status(gui_running=True, busy=False, queue_depth=0)

    response = adapter.handle_command("shutdown", "close-1")

    assert response["accepted"] is True
    assert response["message"] == "关闭请求已接受"
    assert calls == ["close-1"]


def test_adapter_shutdown_is_refused_while_queue_is_busy_or_nonempty():
    calls = []
    adapter = LocalVideoRenamerAdapter(shutdown_handler=lambda request_id: calls.append(request_id))
    adapter.update_status(gui_running=True, busy=True, queue_depth=0)

    active = adapter.handle_command("shutdown", "close-active")
    adapter.update_status(busy=False, queue_depth=1)
    queued = adapter.handle_command("shutdown", "close-queued")

    assert active["accepted"] is False
    assert queued["accepted"] is False
    assert "先结束任务" in active["reason"]
    assert calls == []


def test_adapter_control_server_exposes_authenticated_status_and_gui_queue():
    calls = []
    adapter = LocalVideoRenamerAdapter(
        start_handler=lambda request_id: calls.append(request_id)
        or {"task_id": "task-1"},
    )
    adapter.sync_task_queue_status(
        [{"task_id": 1, "trace_task_id": "trace-1", "title": "扫描本地视频", "status": "正在执行"}]
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
        assert status["task_status_known"] is True
        assert status["task_title"] == "扫描本地视频"
        assert status["busy"] is True
        adapter.sync_task_queue_status([])

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
