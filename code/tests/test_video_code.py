import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.core.filename_rules import extract_code_from_filename
from app.core.enrichment_sources import BAOMU_ACTOR_SOURCE, BINGHUO_ACTOR_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.core.javtxt_video_state import is_javtxt_eligible_movie, summarize_javtxt_movies
from app.core.video_code import compact_video_code, has_supported_video_code, standardize_video_code
from app.data.database_handler import STARTUP_MAINTENANCE_META_KEY, VideoDatabase
from app.scraper.javtxt_scraper import extract_page_code, is_not_found_detail_page
from app.services.parsers import extract_code
from app.services.resolvers import MovieAuthorResolver
from app.services.video import (
    MANUAL_CATEGORY_TIER_FIRST,
    MANUAL_CATEGORY_TIER_SECOND,
    MANUAL_CATEGORY_TIER_THIRD,
    VIDEO_CATEGORY_CO_STAR,
    classify_manual_category_tier,
    detect_video_category,
    VIDEO_CATEGORY_COLLECTION,
    VIDEO_CATEGORY_SINGLE,
)


class VideoCodeStandardizationTest(unittest.TestCase):
    def test_strips_leading_numeric_vendor_prefix(self):
        samples = {
            '168BOU001': 'BOU-001',
            '168BOU-001': 'BOU-001',
            '360MBMH058': 'MBMH-058',
            '360MBMH-058': 'MBMH-058',
            '013ONEZ075': 'ONEZ-075',
            '013ONEZ-075': 'ONEZ-075',
        }
        for raw_code, expected in samples.items():
            with self.subTest(raw_code=raw_code):
                self.assertEqual(standardize_video_code(raw_code), expected)

    def test_keeps_real_numeric_or_alphanumeric_prefixes_when_standardizing(self):
        samples = {
            '010216-061': '010216-061',
            'T28-123': 'T28-123',
            'S2MBD-123': 'S2MBD-123',
        }
        for raw_code, expected in samples.items():
            with self.subTest(raw_code=raw_code):
                self.assertEqual(standardize_video_code(raw_code), expected)

    def test_pure_numeric_prefix_codes_are_not_supported_for_web_lookup(self):
        self.assertFalse(has_supported_video_code('010216-061'))
        self.assertFalse(
            is_javtxt_eligible_movie(
                {
                    'code': '010216-061',
                    'title': 'sample',
                    'release_date': '2025-01-01',
                }
            )
        )
        self.assertEqual(extract_code('010216-061 sample'), '')
        self.assertIsNone(extract_code_from_filename('010216-061 sample'))

    def test_compact_code_uses_standardized_form_for_lookup(self):
        self.assertEqual(compact_video_code('168BOU-001'), 'BOU001')
        self.assertEqual(compact_video_code('BOU-001'), 'BOU001')

    def test_filename_and_card_parsers_return_standard_code(self):
        self.assertEqual(extract_code_from_filename('168BOU001 title'), 'BOU-001')
        self.assertEqual(extract_code('360MBMH-058 熟年同窓会'), 'MBMH-058')

    def test_javtxt_page_code_extraction_matches_standard_lookup_code(self):
        self.assertEqual(extract_page_code(['番号', 'bou-001 (h_113bou00001)']), 'BOU001')

    def test_javtxt_not_found_detail_page_is_detected(self):
        class _FakePage:
            def title(self):
                return 'Not Found'

        self.assertTrue(is_not_found_detail_page(_FakePage(), ['Not Found']))
        self.assertFalse(is_not_found_detail_page(_FakePage(), ['番号', 'STARS-225']))

    def test_manual_category_tier_classification(self):
        self.assertEqual(classify_manual_category_tier('甲 乙 丙 丁 戊', '甲 乙 丙 丁 戊'), MANUAL_CATEGORY_TIER_FIRST)
        self.assertEqual(classify_manual_category_tier('甲 乙 丙', '甲 乙 丙'), MANUAL_CATEGORY_TIER_SECOND)
        self.assertEqual(classify_manual_category_tier('', '未公开'), MANUAL_CATEGORY_TIER_THIRD)

    def test_detects_collection_category_from_long_duration_tags(self):
        self.assertEqual(detect_video_category('16时间以上作品 独家分发 熟女', ''), VIDEO_CATEGORY_COLLECTION)
        self.assertEqual(detect_video_category('16小时以上作品 精选合集', '甲 乙'), VIDEO_CATEGORY_COLLECTION)

    def test_vrtm_prefix_is_not_misclassified_as_vr_marker(self):
        self.assertTrue(
            is_javtxt_eligible_movie(
                {
                    'code': 'VRTM-518',
                    'title': 'あぶない放課後 新・女教師スペシャル つかもと友希 VRTM-518',
                    'release_date': '2020-09-11',
                }
            )
        )

    def test_detect_video_category_supports_forced_single_or_co_star_classification(self):
        self.assertEqual(detect_video_category('', '婕斿憳A', force_single_or_co_star=True), VIDEO_CATEGORY_SINGLE)
        self.assertEqual(detect_video_category('', '婕斿憳A 婕斿憳B', force_single_or_co_star=True), VIDEO_CATEGORY_CO_STAR)
        self.assertEqual(detect_video_category('', '', force_single_or_co_star=True), VIDEO_CATEGORY_CO_STAR)

    def test_javtxt_summary_separates_success_no_result_and_no_detail(self):
        summary = summarize_javtxt_movies(
            [
                {
                    'code': 'ABP-123',
                    'title': 'ABP-123',
                    'release_date': '2025-02-01',
                    'javtxt_release_date': '2025-02-01',
                    'author': '演员A',
                    'javtxt_actors': '演员A',
                    'javtxt_enrichment_status': ENRICHED_STATUS,
                    'javtxt_movie_id': '123',
                    'javtxt_url': 'https://javtxt.top/v/123',
                },
                {
                    'code': 'ABP-124',
                    'title': 'ABP-124',
                    'release_date': '2025-02-01',
                    'javtxt_release_date': '2025-02-01',
                    'javtxt_enrichment_status': NO_SEARCH_RESULTS_STATUS,
                },
                {
                    'code': 'ABP-125',
                    'title': 'ABP-125',
                    'release_date': '2025-02-01',
                    'javtxt_release_date': '2025-02-01',
                    'javtxt_enrichment_status': NO_VIDEO_DETAIL_STATUS,
                },
                {
                    'code': 'ABP-126',
                    'title': 'ABP-126',
                    'release_date': '2025-02-01',
                    'javtxt_release_date': '2025-02-01',
                    'javtxt_enrichment_status': '补全失败',
                },
            ]
        )

        self.assertEqual(summary['total_count'], 4)
        self.assertEqual(summary['enriched_count'], 3)
        self.assertEqual(summary['completed_count'], 3)
        self.assertEqual(summary['success_count'], 1)
        self.assertEqual(summary['pending_count'], 0)
        self.assertEqual(summary['failed_count'], 1)
        self.assertEqual(summary['no_search_count'], 1)
        self.assertEqual(summary['no_detail_count'], 1)


class _StubDatabase:
    def get_javtxt_actor_cache_by_codes(self, codes):
        return {}

    def save_javtxt_cache_for_video(self, code, info, status=ENRICHED_STATUS, error=''):
        return 0


class _StubCacheDatabase(_StubDatabase):
    def __init__(self, cache_rows):
        self.cache_rows = dict(cache_rows or {})

    def get_javtxt_actor_cache_by_codes(self, codes):
        results = {}
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            row = self.cache_rows.get(normalized_code)
            if row:
                results[normalized_code] = dict(row)
        return results


class _StubScraper:
    @contextmanager
    def session(self):
        yield None

    def fetch_by_code(self, code):
        return {
            'code': code,
            'found': True,
            'title': 'old movie',
            'javtxt_title': 'old movie',
            'author': '演员A',
            'javtxt_actors': '演员A',
            'javtxt_actors_raw': '演员A',
            'release_date': '2018-05-13',
            'javtxt_tags': '人妻',
            'javtxt_movie_id': '272298',
            'javtxt_url': 'https://javtxt.top/v/272298',
        }


class _EligibleStubScraper:
    def __init__(self):
        self.fetch_count = 0

    @contextmanager
    def session(self):
        yield None

    def fetch_by_code(self, code):
        self.fetch_count += 1
        return {
            'code': code,
            'found': True,
            'title': 'new movie',
            'javtxt_title': 'new movie',
            'author': '婕斿憳A',
            'javtxt_actors': '婕斿憳A',
            'javtxt_actors_raw': '婕斿憳A',
            'release_date': '2025-05-13',
            'javtxt_tags': '浜哄',
            'javtxt_movie_id': '502298',
            'javtxt_url': 'https://javtxt.top/v/502298',
        }


class _FailOnFetchScraper:
    @contextmanager
    def session(self):
        yield None

    def fetch_by_code(self, code):
        raise AssertionError(f'fetch_by_code should not be called for {code}')


class MovieAuthorResolverEligibilityTest(unittest.TestCase):
    def test_javtxt_result_with_old_release_date_is_downgraded(self):
        resolver = MovieAuthorResolver(_StubDatabase(), scraper=_StubScraper())
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'NSPS-702',
                    'title': 'legacy movie',
                    'author': '',
                    'release_date': '2020-12-22',
                }
            ]
        )

        entry = result['entries'][0]
        self.assertEqual(entry['release_date'], '2018-05-13')
        self.assertEqual(entry['javtxt_enrichment_status'], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(entry['javtxt_movie_id'], '')
        self.assertEqual(entry['javtxt_url'], '')

    def test_cached_no_result_with_release_date_is_not_retried(self):
        resolver = MovieAuthorResolver(
            _StubCacheDatabase(
                {
                    'ACZD-072': {
                        'code': 'ACZD-072',
                        'javtxt_actors': '',
                        'javtxt_actors_raw': '',
                        'javtxt_movie_id': '',
                        'javtxt_url': '',
                        'javtxt_tags': '',
                        'javtxt_enrichment_status': NO_SEARCH_RESULTS_STATUS,
                        'javtxt_release_date': '',
                        'release_date': '2022-12-09',
                    }
                }
            ),
            scraper=_FailOnFetchScraper(),
        )
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'ACZD072',
                    'title': 'ACZD-072',
                    'author': '',
                    'release_date': '2022-12-09',
                }
            ]
        )

        entry = result['entries'][0]
        self.assertEqual(result['processed_video_count'], 0)
        self.assertEqual(result['pending_video_count'], 0)
        self.assertEqual(entry['code'], 'ACZD072')

    def test_cached_no_detail_with_release_date_is_not_retried(self):
        resolver = MovieAuthorResolver(
            _StubCacheDatabase(
                {
                    'STARS-225': {
                        'code': 'STARS-225',
                        'javtxt_actors': '',
                        'javtxt_actors_raw': '',
                        'javtxt_movie_id': '',
                        'javtxt_url': '',
                        'javtxt_tags': '',
                        'javtxt_enrichment_status': NO_VIDEO_DETAIL_STATUS,
                        'javtxt_release_date': '',
                        'release_date': '2020-04-07',
                    }
                }
            ),
            scraper=_FailOnFetchScraper(),
        )
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'STARS225',
                    'title': 'STARS-225',
                    'author': '',
                    'release_date': '2020-04-07',
                }
            ]
        )

        entry = result['entries'][0]
        self.assertEqual(result['processed_video_count'], 0)
        self.assertEqual(result['pending_video_count'], 0)
        self.assertEqual(entry['code'], 'STARS225')

    def test_same_batch_cached_result_applies_javtxt_detail_fields_to_duplicate_code(self):
        scraper = _EligibleStubScraper()
        resolver = MovieAuthorResolver(_StubDatabase(), scraper=scraper)
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'ABP-123',
                    'title': 'ABP-123',
                    'author': '',
                    'release_date': '2025-05-13',
                },
                {
                    'code': 'ABP-123',
                    'title': 'ABP-123 duplicate',
                    'author': '',
                    'release_date': '2025-05-13',
                },
            ]
        )

        self.assertEqual(scraper.fetch_count, 1)
        self.assertEqual(result['entries'][0]['javtxt_url'], 'https://javtxt.top/v/502298')
        self.assertEqual(result['entries'][1]['javtxt_url'], 'https://javtxt.top/v/502298')
        self.assertEqual(result['entries'][1]['javtxt_movie_id'], '502298')


if __name__ == '__main__':
    unittest.main()
