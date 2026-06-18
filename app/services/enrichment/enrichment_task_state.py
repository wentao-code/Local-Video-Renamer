from threading import Event, Lock


class EnrichmentTaskState:
    def __init__(self):
        self.cancel_event = Event()
        self._lock = Lock()
        self.is_running = False
        self.active_kind = ''

    def begin(self, task_kind, reset_progress):
        with self._lock:
            if self.is_running:
                raise RuntimeError('当前已有补全任务正在运行，请稍后再试。')
            self.is_running = True
            self.active_kind = str(task_kind or '').strip()
            self.cancel_event.clear()
            reset_progress()

    def end(self):
        self.is_running = False
        self.active_kind = ''
        self.cancel_event.clear()

    def request_cancel(self, set_message):
        if not self.is_running:
            return {
                'cancel_requested': False,
                'message': '当前没有正在运行的补全任务。',
            }

        self.cancel_event.set()
        set_message(self.active_kind)
        return {
            'cancel_requested': True,
            'message': '已请求停止补全任务，当前条目处理完成后会停止。',
        }
