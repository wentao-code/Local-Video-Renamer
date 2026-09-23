# Feishu Plugin Adapter

Local Video Renamer contains a Feishu control adapter at
`app/plugins/local_video_renamer_adapter.py`.

The adapter currently provides:

- a validated shared-SDK manifest with stable `start`, `stop`, and read-only
  `status` action names;
- a thread-safe status snapshot;
- read-only status synchronized from the GUI's `GuiTaskQueue`, including the
  active task title and queued task count;
- the shared SDK control-server factory;
- the shared SDK task-report client factory;
- explicit rejection while no GUI/business callback is bound.

The control server exposes the manifest at `GET /api/v1/manifest` in addition
to the shared status and command endpoints. See
`feishu-pc-controller/docs/CONTROL_PROTOCOL.md` for the wire contract.

The GUI starts the status endpoint when `FEISHU_CONTROL_TOKEN` is configured
in the process environment or `user_data/config/.env`. It publishes queue
status from the Qt GUI thread into a thread-safe snapshot. No start or stop
callbacks are installed, so Feishu cannot trigger scan, rename, or task cancellation.
`start` and `stop` remain rejected until a separate, explicitly approved
business integration is implemented.

The controller and GUI must use the same `FEISHU_CONTROL_TOKEN`. The endpoint
uses `127.0.0.1:8763` by default; `LOCAL_VIDEO_RENAMER_CONTROL_HOST`,
`LOCAL_VIDEO_RENAMER_CONTROL_PORT`, and `LOCAL_VIDEO_RENAMER_CONTROL_TIMEOUT`
can override those values. Ensure the standalone adapter process is not
already occupying this port; it does not have access to the GUI's live queue.
The tracked `.env.example` is a template; the app's actual local configuration
is stored under `user_data/config/.env` and is ignored by Git.

The shared SDK must be installed in the Python environment running this project:

```powershell
python -m pip install -e D:\pycharm_pro\feishu-pc-controller
```

The standalone `app.plugins.local_video_renamer_control_server` entry point
does not attach to the GUI task queue. Do not use it as the live status
endpoint; without a GUI snapshot it reports the task state as unknown.
