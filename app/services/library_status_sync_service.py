from app.services.library_status_sync_merger import (
    build_merged_movie_snapshot,
    clear_movie_javtxt_state,
    has_movie_row_changes,
    is_sync_eligible_movie,
    merge_movie_row,
)


class LibraryStatusSyncService:
    def __init__(self, database):
        self.database = database

    def sync(self):
        code_prefix_rows = self.database.list_all_code_prefix_movies()
        actor_rows = self.database.list_all_actor_movies()
        prefix_rows_by_code = self._group_rows_by_code(code_prefix_rows)
        actor_rows_by_code = self._group_rows_by_code(actor_rows)

        candidate_codes = sorted(set(prefix_rows_by_code) | set(actor_rows_by_code))
        shared_codes = sorted(set(prefix_rows_by_code) & set(actor_rows_by_code))
        if not candidate_codes:
            return {
                "candidate_code_count": 0,
                "shared_code_count": 0,
                "synced_code_count": 0,
                "updated_code_prefix_movie_count": 0,
                "updated_actor_movie_count": 0,
                "updated_prefix_count": 0,
                "updated_actor_count": 0,
                "message": "当前没有可同步的库内视频状态。",
            }

        processed_rows = self.database.get_videos_by_codes(candidate_codes)
        cache_rows = self.database.get_javtxt_actor_cache_by_codes(candidate_codes)

        code_prefix_updates = []
        actor_updates = []
        affected_prefixes = set()
        affected_actors = set()
        synced_codes = set()

        for code in candidate_codes:
            merged_snapshot = build_merged_movie_snapshot(
                code,
                prefix_rows_by_code.get(code, []) + actor_rows_by_code.get(code, []),
                processed_row=processed_rows.get(code, {}),
                cache_row=cache_rows.get(code, {}),
            )
            if not merged_snapshot:
                continue

            is_eligible = is_sync_eligible_movie(merged_snapshot)

            code_changed = False
            for row in prefix_rows_by_code.get(code, []):
                merged_row = merge_movie_row(row, merged_snapshot) if is_eligible else clear_movie_javtxt_state(row)
                if has_movie_row_changes(row, merged_row):
                    code_prefix_updates.append(merged_row)
                    affected_prefixes.add(str(merged_row.get("prefix", "") or "").strip().upper())
                    code_changed = True

            for row in actor_rows_by_code.get(code, []):
                merged_row = merge_movie_row(row, merged_snapshot) if is_eligible else clear_movie_javtxt_state(row)
                if has_movie_row_changes(row, merged_row):
                    actor_updates.append(merged_row)
                    affected_actors.add(str(merged_row.get("actor_name", "") or "").strip())
                    code_changed = True

            if code_changed:
                synced_codes.add(code)

        updated_code_prefix_movie_count = self.database.bulk_update_code_prefix_movies(code_prefix_updates)
        updated_actor_movie_count = self.database.bulk_update_actor_movies(actor_updates)
        updated_prefix_count = self.database.refresh_code_prefix_javtxt_statuses(sorted(affected_prefixes))
        updated_actor_count = self.database.refresh_actor_javtxt_statuses(sorted(affected_actors))

        return {
            "candidate_code_count": len(candidate_codes),
            "shared_code_count": len(shared_codes),
            "synced_code_count": len(synced_codes),
            "updated_code_prefix_movie_count": updated_code_prefix_movie_count,
            "updated_actor_movie_count": updated_actor_movie_count,
            "updated_prefix_count": updated_prefix_count,
            "updated_actor_count": updated_actor_count,
            "message": "状态同步已完成。",
        }

    @staticmethod
    def _group_rows_by_code(rows):
        grouped = {}
        for row in rows or []:
            code = str((row or {}).get("code", "") or "").strip().upper()
            if not code:
                continue
            grouped.setdefault(code, []).append(dict(row or {}))
        return grouped
