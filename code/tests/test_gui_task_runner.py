import os
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget

from app.gui.gui_task_runner import GuiTaskRunner
from app.gui import main_window


_APP = QApplication.instance() or QApplication([])


class _Worker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        self.finished.emit({'ok': True})


class GuiTaskRunnerTest(unittest.TestCase):
    def test_finished_handler_runs_on_parent_gui_thread(self):
        parent = QWidget()
        callback_threads = []
        runner = GuiTaskRunner(
            parent,
            _Worker(),
            lambda _result: callback_threads.append(QThread.currentThread()),
            lambda _message: None,
        )

        runner.start()
        deadline = time.time() + 2
        while not callback_threads and time.time() < deadline:
            _APP.processEvents()
            time.sleep(0.01)

        self.assertEqual(callback_threads, [parent.thread()])
        parent.deleteLater()
        _APP.processEvents()

    def test_progress_polling_is_started_as_background_runner(self):
        calls = []
        runners = []

        class _FakeRunner:
            def __init__(self, _parent, _worker, _finished, _failed, cleanup_handler=None):
                runners.append((_worker, _finished, _failed, cleanup_handler))

            def start(self):
                calls.append('start')

        def unexpected_sync_request():
            calls.append('sync-request')
            raise AssertionError('进度请求不能在 GUI 线程同步执行')

        stub = type('ProgressHost', (), {})()
        stub.enrichment_progress_runner = None
        stub.enrichment_progress_worker = None
        stub.backend_client = type('Client', (), {'get_enrichment_progress': unexpected_sync_request})()

        original_runner = main_window.GuiTaskRunner
        main_window.GuiTaskRunner = _FakeRunner
        try:
            main_window.VidNormApp.refresh_enrichment_progress(stub)
        finally:
            main_window.GuiTaskRunner = original_runner

        self.assertEqual(calls, ['start'])
        self.assertEqual(len(runners), 1)
        self.assertIsInstance(runners[0][0], main_window.EnrichmentProgressWorker)
