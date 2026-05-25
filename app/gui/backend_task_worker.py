from PyQt5.QtCore import QObject, pyqtSignal


class BackendTaskWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self):
        try:
            result = self.task()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)
