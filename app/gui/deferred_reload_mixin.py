from PyQt5.QtCore import QTimer


class DeferredReloadMixin:
    def _init_deferred_reload(self, reload_callback, delay_ms=250):
        self._deferred_reload_callback = reload_callback
        self._deferred_reload_pending = False
        self._deferred_reload_timer = QTimer(self)
        self._deferred_reload_timer.setSingleShot(True)
        self._deferred_reload_delay_ms = max(int(delay_ms or 0), 0)
        self._deferred_reload_timer.timeout.connect(self._perform_deferred_reload)

    def schedule_deferred_reload(self, delay_ms=None):
        if getattr(self, '_deferred_reload_timer', None) is None:
            return
        self._deferred_reload_pending = True
        wait_ms = self._deferred_reload_delay_ms if delay_ms is None else max(int(delay_ms or 0), 0)
        self._deferred_reload_timer.start(wait_ms)

    def _perform_deferred_reload(self):
        if not getattr(self, '_deferred_reload_pending', False):
            return
        if hasattr(self, 'is_async_task_running') and self.is_async_task_running():
            return
        self._deferred_reload_pending = False
        callback = getattr(self, '_deferred_reload_callback', None)
        if callable(callback):
            callback()

    def _cleanup_async_task_thread(self):
        super()._cleanup_async_task_thread()
        self._perform_deferred_reload()
