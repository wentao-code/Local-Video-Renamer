from pathlib import Path

from PyQt5.QtCore import QLockFile


class SingleInstanceGuard:
    """Owns a lock file for the lifetime of the desktop client."""

    def __init__(self, lock_path):
        self.lock_path = Path(lock_path)
        self._lock = QLockFile(str(self.lock_path))
        self._lock.setStaleLockTime(30000)
        self._owns_lock = False

    def acquire(self):
        if self._owns_lock:
            return True
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._owns_lock = bool(self._lock.tryLock(0))
        return self._owns_lock

    def release(self):
        if self._owns_lock:
            self._lock.unlock()
            self._owns_lock = False

    def __del__(self):
        self.release()
