import unittest

from app.services.enrichment.video_source_enrichment_service import VideoSourceEnrichmentService


class EmptyDatabase:
    def list_videos_for_enrichment(self, limit, source_key, candidate_filter=None):
        return []

    def count_pending_video_enrichments(self, source_key, candidate_filter=None):
        return 0


class FailingSessionScraper:
    def __init__(self):
        self.session_calls = 0

    def session(self):
        self.session_calls += 1
        raise AssertionError('empty candidate runs must not open a browser session')


class VideoSourceEnrichmentServiceTest(unittest.TestCase):
    def test_empty_candidate_list_does_not_open_scraper_session(self):
        scraper = FailingSessionScraper()
        service = VideoSourceEnrichmentService(EmptyDatabase(), scraper=scraper)

        result = service.enrich_next_videos(1)

        self.assertEqual(scraper.session_calls, 0)
        self.assertEqual(result['processed_count'], 0)
        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['failed_count'], 0)


if __name__ == '__main__':
    unittest.main()
