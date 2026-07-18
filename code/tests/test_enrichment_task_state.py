import time


def test_stale_in_memory_task_state_is_reconciled_when_database_has_no_running_items():
    from app.services.enrichment.enrichment_task_state import EnrichmentTaskState

    state = EnrichmentTaskState()
    state.begin('single', lambda: None)
    state.started_monotonic = time.monotonic() - 121

    assert state.reconcile(has_persisted_running_items=False, stale_after_seconds=120) is True
    assert state.is_running is False
    assert state.active_kind == ''


def test_recent_in_memory_task_state_is_not_reconciled_during_startup_window():
    from app.services.enrichment.enrichment_task_state import EnrichmentTaskState

    state = EnrichmentTaskState()
    state.begin('single', lambda: None)

    assert state.reconcile(has_persisted_running_items=False, stale_after_seconds=120) is False
    assert state.is_running is True
