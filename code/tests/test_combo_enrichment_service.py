import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.enrichment.combo_enrichment_service import ComboEnrichmentService


class _ComboProgressStub:
    def __init__(self):
        self.messages = []

    def update_subtask_message(self, task_key, message='', is_running=False, current_item=''):
        self.messages.append((task_key, message, is_running, current_item))


class _LoggerStub:
    def log(self, *_args, **_kwargs):
        return None


class _SingleRoundComboService(ComboEnrichmentService):
    def __init__(self):
        super().__init__(database=object(), combo_progress_service=_ComboProgressStub(), logger=_LoggerStub())
        self.execution_count = 0

    def _execute_subtask(self, task_definition, task_config):
        self.execution_count += 1
        return {
            'task_label': task_definition['task_label'],
            'entity_label': task_definition['task_label'],
            'count_unit': task_definition.get('count_unit', '项'),
            'processed_count': 2,
            'success_count': 2,
            'failed_count': 0,
            'remaining_count': 0,
            'stopped': False,
            'requires_manual_verification': False,
            'message': 'done',
        }


class _AlwaysRemainingComboService(ComboEnrichmentService):
    def __init__(self):
        super().__init__(database=object(), combo_progress_service=_ComboProgressStub(), logger=_LoggerStub())
        self.execution_count = 0

    def _execute_subtask(self, task_definition, task_config):
        self.execution_count += 1
        if self.execution_count >= 3:
            self.internal_stop_event.set()
        return {
            'task_label': task_definition['task_label'],
            'entity_label': task_definition['task_label'],
            'count_unit': task_definition.get('count_unit', '项'),
            'processed_count': 1,
            'success_count': 1,
            'failed_count': 0,
            'remaining_count': 10,
            'stopped': False,
            'requires_manual_verification': False,
            'message': '',
        }


class ComboEnrichmentServiceBatchLoopTest(unittest.TestCase):
    def test_batch_loop_does_not_wait_for_next_round_when_remaining_count_is_zero(self):
        service = _SingleRoundComboService()
        results_by_task = {}
        task_definition = {'task_key': 'actor_javtxt', 'task_label': '演员库 · 辛聚阁', 'count_unit': '视频'}
        task_config = {'limit': 5, 'batch_interval_minutes': 1}

        with patch('app.services.enrichment.combo_enrichment_service.time.sleep', side_effect=AssertionError('sleep should not run')):
            service._run_subtask_batch_loop(task_definition, task_config, results_by_task)

        self.assertEqual(service.execution_count, 1)
        self.assertEqual(results_by_task['actor_javtxt']['remaining_count'], 0)

    def test_batch_loop_stops_at_batch_count_limit(self):
        service = _AlwaysRemainingComboService()
        results_by_task = {}
        task_definition = {'task_key': 'actor_javtxt', 'task_label': '演员库 · 辛聚阁', 'count_unit': '视频'}
        task_config = {'limit': 5, 'batch_interval_minutes': 1, 'batch_count_limit': 2}

        with patch('app.services.enrichment.combo_enrichment_service.time.sleep', return_value=None):
            service._run_subtask_batch_loop(task_definition, task_config, results_by_task)

        self.assertEqual(service.execution_count, 2)
        self.assertEqual(results_by_task['actor_javtxt']['batch_count'], 2)


if __name__ == '__main__':
    unittest.main()
