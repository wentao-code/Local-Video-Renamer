"""Control adapter scaffold for Local Video Renamer.

This module deliberately contains no GUI or business-operation bindings yet.
Callers can inject task callbacks later and keep the Feishu protocol stable.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from feishu_plugin_sdk import PluginManifest, ReportClient, RemoteControlServer, StatusSnapshot


Handler = Callable[[str], Mapping[str, Any] | None]


class LocalVideoRenamerAdapter:
    """Expose the shared plugin contract without triggering local operations."""

    PLUGIN_ID = "local_video_renamer"
    LABEL = "Local Video Renamer"
    VERSION = "0.1.0"
    UNBOUND_REASON = "Local Video Renamer 控制适配器尚未绑定 GUI 业务入口"

    def __init__(
        self,
        *,
        start_handler: Handler | None = None,
        stop_handler: Handler | None = None,
        status_snapshot: StatusSnapshot | None = None,
    ) -> None:
        self._start_handler = start_handler
        self._stop_handler = stop_handler
        self._status = status_snapshot or StatusSnapshot(
            plugin_id=self.PLUGIN_ID,
            gui_running=True,
            ready=True,
            busy=False,
            task_id=None,
        )

    @property
    def status_snapshot(self) -> StatusSnapshot:
        return self._status

    @property
    def control_bound(self) -> bool:
        return self._start_handler is not None or self._stop_handler is not None

    def status(self) -> dict[str, Any]:
        status = self._status.get()
        status.setdefault("plugin_id", self.PLUGIN_ID)
        status["control_bound"] = self.control_bound
        status["ready"] = bool(status.get("ready", True))
        return status

    def update_status(self, **values: Any) -> None:
        """Allow a future GUI/task bridge to publish state without changing routes."""
        self._status.update(**values)

    def manifest(self) -> dict[str, Any]:
        return PluginManifest(
            plugin_id=self.PLUGIN_ID,
            label=self.LABEL,
            version=self.VERSION,
            actions=(
                {
                    "name": "start",
                    "label": "开始本地视频处理",
                    "aliases": ["本地视频：开始处理", "local video renamer start"],
                },
                {
                    "name": "stop",
                    "label": "停止本地视频处理",
                    "aliases": ["本地视频：停止处理", "local video renamer stop"],
                },
                {
                    "name": "status",
                    "label": "查看本地视频处理状态",
                    "aliases": ["本地视频：状态", "local video renamer status"],
                },
            ),
            integration={
                "bound": self.control_bound,
                "message": self.UNBOUND_REASON if not self.control_bound else "已注入控制回调",
            },
        ).to_json()

    def handle_command(self, action: str, request_id: str) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        normalized_request_id = str(request_id or "").strip()
        if normalized_action not in {"start", "stop"}:
            return {
                "request_id": normalized_request_id,
                "accepted": False,
                "status": "rejected",
                "reason": f"不支持的控制动作：{normalized_action or '空动作'}",
            }

        handler = self._start_handler if normalized_action == "start" else self._stop_handler
        if handler is None:
            return {
                "request_id": normalized_request_id,
                "accepted": False,
                "status": "rejected",
                "reason": self.UNBOUND_REASON,
            }

        result = dict(handler(normalized_request_id) or {})
        result.setdefault("request_id", normalized_request_id)
        result.setdefault("accepted", True)
        result.setdefault("status", "accepted" if result["accepted"] else "rejected")
        return result

    def create_control_server(
        self,
        *,
        token: str,
        host: str = "127.0.0.1",
        port: int = 0,
        command_timeout: float = 2.0,
    ) -> RemoteControlServer:
        """Create the SDK server; the caller owns startup, draining, and shutdown."""
        return RemoteControlServer(
            self.status,
            self.handle_command,
            token=token,
            host=host,
            port=port,
            manifest_provider=self.manifest,
            required_ready_fields=("gui_running", "ready"),
            refusal_messages={
                "gui_running": "Local Video Renamer 未运行",
                "ready": "Local Video Renamer 当前未准备好",
                "busy": "Local Video Renamer 当前已有任务运行中",
            },
            command_timeout=command_timeout,
            timeout_message="Local Video Renamer 未响应控制请求",
            queue_full_message="Local Video Renamer 控制队列已满",
            shutdown_message="Local Video Renamer 正在关闭",
        )

    @staticmethod
    def create_report_client(
        controller_url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = 3.0,
    ) -> ReportClient:
        return ReportClient(controller_url, token, timeout=timeout)
