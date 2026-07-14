from app.services.identity import is_ignored_actor_name, split_actor_names
from app.services.library.code_prefix_library import extract_code_prefix


class CandidateLibraryService:
    def __init__(self, database):
        self.database = database

    def refresh_candidates(self):
        actor_candidates = self._build_actor_candidates()
        code_prefix_candidates = self._build_code_prefix_candidates()
        self.database.replace_candidate_actor_records(actor_candidates)
        self.database.replace_candidate_code_prefix_records(code_prefix_candidates)
        return {
            'actor_candidates': actor_candidates,
            'code_prefix_candidates': code_prefix_candidates,
        }

    def list_actor_candidates(self, limit=50):
        self.refresh_candidates()
        return self.database.list_candidate_actor_records(limit=limit)

    def list_code_prefix_candidates(self, limit=50):
        self.refresh_candidates()
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
