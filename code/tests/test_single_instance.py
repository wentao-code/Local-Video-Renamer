from pathlib import Path

from app.gui.single_instance import SingleInstanceGuard


def test_single_instance_guard_allows_only_one_owner(tmp_path):
    lock_path = Path(tmp_path) / 'vidnorm.lock'
    first = SingleInstanceGuard(lock_path)
    second = SingleInstanceGuard(lock_path)

    try:
        assert first.acquire()
        assert not second.acquire()
    finally:
        second.release()
        first.release()

