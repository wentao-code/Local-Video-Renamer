import unittest
from contextlib import contextmanager

from app.core.enrichment_status import ENRICHED_STATUS
from app.services.enrichment import ActorJavtxtEnrichmentService, CodePrefixJavtxtEnrichmentService


class _ResolverWithSession:
    @contextmanager
    def session(self):
        yield None


class _ActorRemainingCountService(ActorJavtxtEnrichmentService):
    def __init__(self):
        super().__init__(database=object())
        self.seen = []

    def _ready_actor_infos(self):
        return [
            {'actor_name': 'A', 'pending_video_count': 4},
            {'actor_name': 'B', 'pending_video_count': 3},
        ]

    def _blocked_actor_count(self):
        return 0

    def _remaining_actor_video_count(self, ready_actor_names=None):
        raise AssertionError('full actor remaining recount should not run')

    def _enrich_single_actor(self, actor_name, max_video_count, progress_state):
        updates = {
            'A': {'processed': 3, 'success': 3, 'failed': 0, 'remaining': 1},
            'B': {'processed': 2, 'success': 2, 'failed': 0, 'remaining': 0},
        }[actor_name]
        self.seen.append((actor_name, max_video_count))
        progress_state['processed_video_count'] = int(progress_state.get('processed_video_count', 0) or 0) + updates['processed']
        progress_state['success_video_count'] = int(progress_state.get('success_video_count', 0) or 0) + updates['success']
        progress_state['failed_video_count'] = int(progress_state.get('failed_video_count', 0) or 0) + updates['failed']
        return {
            'actor_name': actor_name,
            'status': ENRICHED_STATUS,
            'video_count': updates['processed'],
            'processed_video_count': updates['processed'],
            'success_video_count': updates['success'],
            'failed_video_count': updates['failed'],
            'remaining_video_count': updates['remaining'],
            'count_unit': '视频',
        }


class _PrefixRemainingCountService(CodePrefixJavtxtEnrichmentService):
    def __init__(self):
        super().__init__(database=object())
        self.author_resolver = _ResolverWithSession()
        self.seen = []

    def _ready_prefix_infos(self):
        return [
            {'prefix': 'AAA', 'pending_video_count': 4},
            {'prefix': 'BBB', 'pending_video_count': 3},
        ]

    def _blocked_prefix_count(self):
        return 0

    def _remaining_prefix_video_count(self, prefixes=None):
        raise AssertionError('full prefix remaining recount should not run')

    def _enrich_single_prefix(self, prefix, max_video_count, progress_state):
        updates = {
            'AAA': {'processed': 4, 'success': 4, 'failed': 0, 'remaining': 0},
            'BBB': {'processed': 1, 'success': 1, 'failed': 0, 'remaining': 2},
        }[prefix]
        self.seen.append((prefix, max_video_count))
        progress_state['processed_video_count'] = int(progress_state.get('processed_video_count', 0) or 0) + updates['processed']
        progress_state['success_video_count'] = int(progress_state.get('success_video_count', 0) or 0) + updates['success']
        progress_state['failed_video_count'] = int(progress_state.get('failed_video_count', 0) or 0) + updates['failed']
        return {
            'prefix': prefix,
            'status': ENRICHED_STATUS,
            'video_count': updates['processed'],
            'processed_video_count': updates['processed'],
            'success_video_count': updates['success'],
            'failed_video_count': updates['failed'],
            'remaining_video_count': updates['remaining'],
            'count_unit': '视频',
        }


class JavtxtBatchRemainingCountTest(unittest.TestCase):
    def test_actor_batch_uses_incremental_remaining_count(self):
        service = _ActorRemainingCountService()

        result = service.enrich_next_actors(10)

        self.assertEqual(result['processed_count'], 5)
        self.assertEqual(result['success_count'], 5)
        self.assertEqual(result['remaining_count'], 1)
        self.assertEqual(service.seen, [('A', 10), ('B', 7)])

    def test_prefix_batch_uses_incremental_remaining_count(self):
        service = _PrefixRemainingCountService()

        result = service.enrich_next_prefixes(10)

        self.assertEqual(result['processed_count'], 5)
        self.assertEqual(result['success_count'], 5)
        self.assertEqual(result['remaining_count'], 2)
        self.assertEqual(service.seen, [('AAA', 10), ('BBB', 6)])


if __name__ == '__main__':
    unittest.main()
