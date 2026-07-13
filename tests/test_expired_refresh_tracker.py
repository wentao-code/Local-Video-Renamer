from datetime import date

from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS
from app.services.video import VIDEO_CATEGORY_SINGLE


def test_actor_tracker_records_growth_only_for_expired_successful_refresh():
    from app.services.enrichment.library_refresh_tracker import LibraryExpiredRefreshTracker

    class FakeDatabase:
        movie_count = 10
        completions = []
        histories = []

        @staticmethod
        def list_expired_actor_enrichment_entities(source_key):
            return {'Actor A'}

        def list_actor_movies(self, actor_name):
            return [{'code': f'ABC-{index:03d}'} for index in range(self.movie_count)]

        def record_actor_enrichment_refresh_completion(self, actor_name, source_key):
            self.completions.append((actor_name, source_key))

        def record_actor_expired_refresh_history(self, actor_name, source_key, before, after):
            self.histories.append((actor_name, source_key, before, after))

    database = FakeDatabase()
    tracker = LibraryExpiredRefreshTracker(database, 'actor', 'avfan')
    tracker.start('Actor A')
    database.movie_count = 13

    metadata = tracker.complete('Actor A', ENRICHED_STATUS)

    assert metadata == {'expired_refresh': True, 'new_video_count': 3}
    assert database.completions == [('Actor A', 'avfan')]
    assert database.histories == [('Actor A', 'avfan', 10, 13)]


def test_tracker_does_not_complete_failed_refresh():
    from app.services.enrichment.library_refresh_tracker import LibraryExpiredRefreshTracker

    class FakeDatabase:
        completions = []

        @staticmethod
        def list_expired_code_prefix_enrichment_entities(source_key):
            return {'ABC'}

        @staticmethod
        def list_code_prefix_movies(prefix):
            return []

        def record_code_prefix_enrichment_refresh_completion(self, prefix, source_key):
            self.completions.append((prefix, source_key))

    database = FakeDatabase()
    tracker = LibraryExpiredRefreshTracker(database, 'code_prefix', 'javtxt')
    tracker.start('ABC')

    assert tracker.complete('ABC', FAILED_STATUS) == {}
    assert database.completions == []


def test_actor_refresh_statuses_are_synchronized_before_expiry_selection():
    from app.services.enrichment.library_refresh_tracker import sync_actor_refresh_update_statuses

    class FakeDatabase:
        updated_statuses = None

        @staticmethod
        def list_actor_enrichment_refresh_times(actor_names=None):
            return {
                ('ActorA', 'avfan'): {
                    'actor_name': 'ActorA',
                    'source_key': 'avfan',
                    'update_status': '',
                },
            }

        @staticmethod
        def list_local_videos_by_actor_names(actor_names, refresh_categories=False):
            assert actor_names == ['ActorA']
            assert refresh_categories is False
            return [
                {
                    'author': 'ActorA',
                    'release_date': date.today().isoformat(),
                    'video_category': VIDEO_CATEGORY_SINGLE,
                },
            ]

        @staticmethod
        def list_latest_actor_movie_release_dates_by_names(actor_names):
            return {}

        def update_actor_enrichment_refresh_statuses(self, statuses):
            self.updated_statuses = statuses

    database = FakeDatabase()

    sync_actor_refresh_update_statuses(database)

    assert database.updated_statuses == {'ActorA': 'active'}


def test_code_prefix_refresh_statuses_are_synchronized_before_expiry_selection():
    from app.services.enrichment.library_refresh_tracker import sync_code_prefix_refresh_update_statuses

    class FakeDatabase:
        @staticmethod
        def list_code_prefix_enrichment_refresh_times(prefixes=None):
            return {('ABC', 'avfan'): {'prefix': 'ABC'}}

        @staticmethod
        def update_code_prefix_enrichment_refresh_statuses(statuses):
            return None

    class FakePrefixLibrary:
        calls = 0

        def list_prefixes(self):
            self.calls += 1
            return []

    prefix_library = FakePrefixLibrary()

    sync_code_prefix_refresh_update_statuses(FakeDatabase(), prefix_library)

    assert prefix_library.calls == 1
