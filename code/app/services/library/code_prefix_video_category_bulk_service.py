from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.core.video_code import standardize_video_code
from app.services.video import VIDEO_CATEGORY_OPTIONS, normalize_video_category


class CodePrefixVideoCategoryBulkService:
    def __init__(self, database):
        self.database = database

    def update_uncategorized_videos(self, prefix, category):
        normalized_prefix = str(prefix or '').strip().upper()
        normalized_category = normalize_video_category(category)
        if not normalized_prefix:
            raise ValueError('缺少番号前缀')
        if normalized_category not in VIDEO_CATEGORY_OPTIONS:
            raise ValueError('视频分类无效')

        target_codes = self._collect_target_codes(normalized_prefix)
        update_result = self.database.update_video_categories(
            target_codes,
            normalized_category,
            clear_staged=True,
        )
        return {
            'prefix': normalized_prefix,
            'category': normalized_category,
            'matched_count': len(target_codes),
            **update_result,
        }

    def _collect_target_codes(self, prefix):
        staged_codes = self.database.list_staged_video_category_codes()
        seen = set()
        matched_codes = []
        for row in self.database.list_code_prefix_movies(prefix):
            normalized_code = standardize_video_code((row or {}).get('code', ''))
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            if normalized_code not in staged_codes:
                continue
            if normalize_video_category((row or {}).get('video_category', '')):
                continue
            if not is_javtxt_eligible_movie(row):
                continue
            matched_codes.append(normalized_code)
        return matched_codes
