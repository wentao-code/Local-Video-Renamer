from threading import Condition
from time import perf_counter

from app.core.app_logging import get_logger
from app.services.identity import is_ignored_actor_name, split_actor_names
from app.services.library.code_prefix_library import extract_code_prefix


LOGGER = get_logger(__name__)


class CandidateLibraryService:
    def __init__(self, database):
        self.database = database
        self._refresh_condition = Condition()
        self._refresh_running = False
        self._last_refresh_result = None
        self._last_refresh_error = ''

    def refresh_candidates(self):
        started_at = perf_counter()
        with self._refresh_condition:
            if self._refresh_running:
                LOGGER.info('候选库刷新复用进行中的任务')
                self._refresh_condition.wait_for(lambda: not self._refresh_running)
                if self._last_refresh_result is None:
                    raise RuntimeError(self._last_refresh_error or '候选库刷新未完成')
                result = {
                    **dict(self._last_refresh_result),
                    'refresh_reused': True,
                    'lock_wait_ms': round((perf_counter() - started_at) * 1000, 3),
                }
                LOGGER.info(
                    '候选库刷新复用完成 duration_ms=%s lock_wait_ms=%s',
                    result['duration_ms'],
                    result['lock_wait_ms'],
                )
                return result
            self._refresh_running = True

        LOGGER.info('候选库刷新开始')
        try:
            actor_candidates = self._build_actor_candidates()
            code_prefix_candidates = self._build_code_prefix_candidates()
            self.database.replace_candidate_actor_records(actor_candidates)
            self.database.replace_candidate_code_prefix_records(code_prefix_candidates)
            result = {
                'actor_candidates': actor_candidates,
                'code_prefix_candidates': code_prefix_candidates,
                'actor_count': len(actor_candidates),
                'code_prefix_count': len(code_prefix_candidates),
                'refresh_reused': False,
                'lock_wait_ms': 0,
                'duration_ms': round((perf_counter() - started_at) * 1000, 3),
            }
            with self._refresh_condition:
                self._last_refresh_result = dict(result)
                self._last_refresh_error = ''
            LOGGER.info(
                '候选库刷新完成 actor_count=%s code_prefix_count=%s duration_ms=%s lock_wait_ms=%s',
                result['actor_count'],
                result['code_prefix_count'],
                result['duration_ms'],
                result['lock_wait_ms'],
            )
            return result
        except Exception as exc:
            with self._refresh_condition:
                self._last_refresh_result = None
                self._last_refresh_error = str(exc)
            LOGGER.exception('候选库刷新失败')
            raise
        finally:
            with self._refresh_condition:
                self._refresh_running = False
                self._refresh_condition.notify_all()

    def list_actor_candidates(self, limit=50):
        return self.database.list_candidate_actor_records(limit=limit)

    def list_code_prefix_candidates(self, limit=50):
        return self.database.list_candidate_code_prefix_records(limit=limit)

    def _build_actor_candidates(self):
        actor_library_names = {
            str((row or {}).get('name', '') or '').strip()
            for row in self.database.list_actors()
            if str((row or {}).get('name', '') or '').strip()
        }
        hidden_actor_names = {
            str(name or '').strip()
            for name in self.database.list_hidden_actors()
            if str(name or '').strip()
        }
        codes_by_actor = {}
        for index, row in enumerate(self.database.list_all_code_prefix_movies()):
            code_key = str((row or {}).get('code', '') or '').strip().upper() or f'row:{index}'
            for actor_name in split_actor_names((row or {}).get('author', '')):
                if (
                    not actor_name
                    or is_ignored_actor_name(actor_name)
                    or actor_name in actor_library_names
                    or actor_name in hidden_actor_names
                ):
                    continue
                codes_by_actor.setdefault(actor_name, set()).add(code_key)
        return self._sort_actor_candidates(codes_by_actor)

    def _build_code_prefix_candidates(self):
        existing_prefixes = {
            str((row or {}).get('prefix', '') or '').strip().upper()
            for row in self.database.list_code_prefix_summaries()
            if str((row or {}).get('prefix', '') or '').strip()
        }
        hidden_prefixes = {
            str(prefix or '').strip().upper()
            for prefix in self.database.list_hidden_code_prefixes()
            if str(prefix or '').strip()
        }
        codes_by_prefix = {}
        for index, row in enumerate(self.database.list_all_actor_movies()):
            code = str((row or {}).get('code', '') or '').strip()
            prefix = extract_code_prefix(code)
            if not prefix or prefix in existing_prefixes or prefix in hidden_prefixes:
                continue
            code_key = code.upper() or f'row:{index}'
            codes_by_prefix.setdefault(prefix, set()).add(code_key)
        return self._sort_code_prefix_candidates(codes_by_prefix)

    @staticmethod
    def _sort_actor_candidates(codes_by_actor):
        rows = [
            {'actor_name': actor_name, 'video_count': len(codes)}
            for actor_name, codes in codes_by_actor.items()
            if actor_name and codes
        ]
        return sorted(rows, key=lambda row: (-row['video_count'], row['actor_name'].casefold()))

    @staticmethod
    def _sort_code_prefix_candidates(codes_by_prefix):
        rows = [
            {'prefix': prefix, 'video_count': len(codes)}
            for prefix, codes in codes_by_prefix.items()
            if prefix and codes
        ]
        return sorted(rows, key=lambda row: (-row['video_count'], row['prefix']))
