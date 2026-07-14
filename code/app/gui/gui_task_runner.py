from PyQt5.QtCore import QThread


class GuiTaskRunner:
    def __init__(self, parent, worker, finished_handler, failed_handler, cleanup_handler=None):
        self.parent = parent
        self.worker = worker
        self.thread = QThread(parent)
        self.finished_handler = finished_handler
        self.failed_handler = failed_handler
        self.cleanup_handler = cleanup_handler

    def start(self):
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.finished_handler)
        self.worker.failed.connect(self.failed_handler)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.thread.start()

    def _cleanup(self):
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        if self.cleanup_handler is not None:
            self.cleanup_handler()
        self.worker = None
        self.thread = None
