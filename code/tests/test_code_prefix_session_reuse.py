import unittest
from contextlib import contextmanager

from app.core.enrichment_status import ENRICHED_STATUS
from app.services.enrichment import CodePrefixEnrichmentService, CodePrefixJavtxtEnrichmentService


class _CountingScraper:
    def __init__(self):
        self.session_enter_count = 0
        self.page = object()

    @contextmanager
    def session(self):
        self.session_enter_count += 1
        yield self.page


class _CountingResolver:
    def __init__(self):
        self.session_enter_count = 0

    @contextmanager
    def session(self):
        self.session_enter_count += 1
        yield None


class _CodePrefixBatchReuseService(CodePrefixEnrichmentService):
    def __init__(self, scraper):
        super().__init__(database=object(), scraper=scraper)
        self.seen_pages = []
        self.seen_prefixes = []

    def _candidate_prefixes(self, limit):
        return ['AAA', 'BBB'][:limit]

    def _remaining_prefix_count(self):
        return 0

    def _enrich_single_prefix(self, page, prefix):
        self.seen_pages.append(page)
        self.seen_prefixes.append(prefix)
        return {
            'prefix': prefix,
            'status': ENRICHED_STATUS,
            'video_count': 1,
        }


class _CodePrefixJavtxtBatchReuseService(CodePrefixJavtxtEnrichmentService):
    def __init__(self, resolver):
        super().__init__(database=object())
        self.author_resolver = resolver
        self.seen_prefixes = []

    def _ready_prefix_infos(self):
        return [
            {'prefix': 'AAA', 'pending_video_count': 1},
            {'prefix': 'BBB', 'pending_video_count': 1},
        ]

    def _blocked_prefix_count(self):
        return 0

    def _remaining_prefix_video_count(self, prefixes=None):
        target_prefixes = prefixes if prefixes is not None else self._ready_prefixes()
        return len(target_prefixes)

    def _pending_prefix_video_count(self, prefix):
        return 0

    def _enrich_single_prefix(self, prefix, max_video_count, progress_state):
        self.seen_prefixes.append((prefix, max_video_count))
        progress_state['processed_video_count'] = int(progress_state.get('processed_video_count', 0) or 0) + 1
        progress_state['success_video_count'] = int(progress_state.get('success_video_count', 0) or 0) + 1
        return {
            'prefix': prefix,
            'status': ENRICHED_STATUS,
            'video_count': 1,
            'processed_video_count': 1,
            'success_video_count': 1,
            'failed_video_count': 0,
            'remaining_video_count': 0,
            'count_unit': '视频',
        }


class CodePrefixSessionReuseTest(unittest.TestCase):
    def test_avfan_code_prefix_batch_reuses_one_browser_session(self):
        scraper = _CountingScraper()
        service = _CodePrefixBatchReuseService(scraper)

        result = service.enrich_next_prefixes(2)

        self.assertEqual(result['processed_count'], 2)
        self.assertEqual(scraper.session_enter_count, 1)
        self.assertEqual(service.seen_prefixes, ['AAA', 'BBB'])
        self.assertEqual(service.seen_pages, [scraper.page, scraper.page])

    def test_javtxt_code_prefix_batch_reuses_one_browser_session(self):
        resolver = _CountingResolver()
        service = _CodePrefixJavtxtBatchReuseService(resolver)

        result = service.enrich_next_prefixes(2)

        self.assertEqual(result['processed_count'], 2)
        self.assertEqual(result['success_count'], 2)
        self.assertEqual(resolver.session_enter_count, 1)
        self.assertEqual(service.seen_prefixes, [('AAA', 2), ('BBB', 1)])


if __name__ == '__main__':
    unittest.main()
