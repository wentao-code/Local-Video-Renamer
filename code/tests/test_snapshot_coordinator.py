from app.backend.snapshot_coordinator import SnapshotCoordinator
from app.backend.service import BackendService
from app.core.snapshot_store import SnapshotStore
from unittest.mock import Mock


def test_snapshot_coordinator_persists_payload_and_invalidates_prefix(tmp_path):
    coordinator = SnapshotCoordinator(SnapshotStore(tmp_path / 'snapshots'))
    payload = coordinator.build_payload(
        refreshed_at='2026-07-29 12:00:00',
        refresh_duration_ms=1200,
        rows=[{'code': 'RCTD-116'}],
    )

    with coordinator.guard('video_library'):
        coordinator.write('video_library/index', payload)

    assert coordinator.read('video_library/index') == payload
    assert payload['refresh_duration_text'] == '1秒'
    coordinator.delete_prefix('video_library')
    assert coordinator.read('video_library/index') is None


def test_snapshot_coordinator_reuses_named_lock():
    coordinator = SnapshotCoordinator(None)

    assert coordinator.lock_for('actor_detail') is coordinator.lock_for('actor_detail')


def test_backend_service_page_snapshot_helpers_delegate_to_coordinator():
    service = BackendService.__new__(BackendService)
    service.snapshot_coordinator = Mock()
    service.snapshot_coordinator.read.return_value = {'cached': True}

    assert BackendService._read_page_snapshot(service, 'video_library/index') == {'cached': True}
    BackendService._write_page_snapshot(service, 'video_library/index', {'cached': True})
    BackendService._delete_page_snapshot(service, 'video_library/index')
    BackendService._delete_page_snapshot_prefix(service, 'video_library')

    service.snapshot_coordinator.write.assert_called_once_with('video_library/index', {'cached': True})
    service.snapshot_coordinator.delete.assert_called_once_with('video_library/index')
    service.snapshot_coordinator.delete_prefix.assert_called_once_with('video_library')
