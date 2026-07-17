import json


def test_failed_snapshot_step_does_not_stop_following_steps(tmp_path):
    from app.gui.snapshot_refresh_orchestrator import SnapshotRefreshOrchestrator

    calls = []

    def failing_step():
        calls.append('failed')
        raise RuntimeError('network down')

    def succeeding_step():
        calls.append('succeeded')

    result = SnapshotRefreshOrchestrator(tmp_path / 'refresh.json', max_attempts=1).run(
        [
            {'key': 'first', 'runner': failing_step},
            {'key': 'second', 'runner': succeeding_step},
        ]
    )

    assert calls == ['failed', 'succeeded']
    assert result['failed'] == [{'key': 'first', 'error': 'network down', 'attempts': 1}]
    assert result['completed'] == ['second']


def test_each_snapshot_step_retries_independently(tmp_path):
    from app.gui.snapshot_refresh_orchestrator import SnapshotRefreshOrchestrator

    attempts = {'first': 0, 'second': 0}

    def first_step():
        attempts['first'] += 1
        if attempts['first'] == 1:
            raise RuntimeError('temporary')

    def second_step():
        attempts['second'] += 1

    result = SnapshotRefreshOrchestrator(tmp_path / 'refresh.json', max_attempts=2).run(
        [
            {'key': 'first', 'runner': first_step},
            {'key': 'second', 'runner': second_step},
        ]
    )

    assert attempts == {'first': 2, 'second': 1}
    assert result['failed'] == []
    assert result['completed'] == ['first', 'second']


def test_partial_refresh_resumes_only_unfinished_steps(tmp_path):
    from app.gui.snapshot_refresh_orchestrator import SnapshotRefreshOrchestrator

    checkpoint = tmp_path / 'refresh.json'
    first_calls = []

    def first_run_step():
        first_calls.append('first')

    def first_run_failed_step():
        first_calls.append('second')
        raise RuntimeError('offline')

    first_result = SnapshotRefreshOrchestrator(checkpoint, max_attempts=1).run(
        [
            {'key': 'first', 'runner': first_run_step},
            {'key': 'second', 'runner': first_run_failed_step},
        ]
    )
    assert first_result['status'] == 'partial'

    second_calls = []

    def resumed_first_step():
        second_calls.append('first')

    def resumed_second_step():
        second_calls.append('second')

    second_result = SnapshotRefreshOrchestrator(checkpoint, max_attempts=1).run(
        [
            {'key': 'first', 'runner': resumed_first_step},
            {'key': 'second', 'runner': resumed_second_step},
        ]
    )

    assert second_calls == ['second']
    assert second_result['status'] == 'completed'
    assert json.loads(checkpoint.read_text(encoding='utf-8'))['status'] == 'completed'
