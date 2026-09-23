# Feishu Plugin Adapter

Local Video Renamer now contains a control-adapter scaffold at
`app/plugins/local_video_renamer_adapter.py`.

The adapter currently provides:

- a validated shared-SDK manifest with stable `start`, `stop`, and read-only
  `status` action names;
- a thread-safe status snapshot;
- the shared SDK control-server factory;
- the shared SDK task-report client factory;
- explicit rejection while no GUI/business callback is bound.

The control server exposes the manifest at `GET /api/v1/manifest` in addition
to the shared status and command endpoints. See
`feishu-pc-controller/docs/CONTROL_PROTOCOL.md` for the wire contract.

This phase intentionally does not connect Feishu commands to the existing
scan or rename buttons. `start_handler` and `stop_handler` are optional
callbacks for the later integration phase. When omitted, both commands return
`accepted=false` with a clear unbound-adapter reason.

Example setup for a future host integration:

```python
adapter = LocalVideoRenamerAdapter(
    start_handler=queue_local_video_task,
    stop_handler=request_local_video_stop,
)
control = adapter.create_control_server(
    token=control_token,
    host="127.0.0.1",
    port=8763,
)
control.start_in_thread()

# Run control.drain() from the owning GUI/event-loop thread.
```

The shared SDK must be installed in the Python environment running this
project, for example:

```powershell
python -m pip install -e D:\pycharm_pro\feishu-pc-controller
```

The unbound adapter can be run independently so the controller can discover
its Manifest and display its readiness state:

```powershell
$env:FEISHU_CONTROL_TOKEN = "the_same_token"
python -m app.plugins.local_video_renamer_control_server
```

It listens on `127.0.0.1:8763` by default. This process intentionally does
not execute rename work until a future host integration injects the existing
business callbacks.
