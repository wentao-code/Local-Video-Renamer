from app.gui import main_window


def test_local_video_renamer_reports_start_and_accepted_normal_close():
    class Reporter:
        def __init__(self):
            self.calls = []

        def started(self):
            self.calls.append(("started",))

        def stopping(self):
            self.calls.append(("stopping",))

        def stopped(self, reason):
            self.calls.append(("stopped", reason))

    window = main_window.VidNormApp.__new__(main_window.VidNormApp)
    window._feishu_lifecycle_reporter = Reporter()

    main_window.VidNormApp._report_feishu_lifecycle_started(window)
    main_window.VidNormApp._report_feishu_lifecycle_stopped(window)

    assert window._feishu_lifecycle_reporter.calls == [
        ("started",),
        ("stopping",),
        ("stopped", "normal_exit"),
    ]


def test_feishu_shutdown_request_is_correlated_to_project_stop_event(monkeypatch):
    context = []
    window = main_window.VidNormApp.__new__(main_window.VidNormApp)
    window._feishu_status_adapter = type(
        "Adapter", (), {"status": lambda self: {"busy": False, "queue_depth": 0}}
    )()
    window._feishu_lifecycle_reporter = type(
        "Reporter",
        (),
        {"set_shutdown_context": lambda self, request_id: context.append(request_id)},
    )()
    monkeypatch.setattr(main_window.QTimer, "singleShot", lambda *_args: None)

    response = main_window.VidNormApp._request_feishu_shutdown(window, "close-1")

    assert response["accepted"] is True
    assert context == ["close-1"]
