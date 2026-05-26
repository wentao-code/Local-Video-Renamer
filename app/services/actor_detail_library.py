import re
from datetime import datetime

from app.core.enrichment_sources import build_library_enrichment_status_text
from app.core.enrichment_status import ENRICHED_STATUS, UNENRICHED_STATUS
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.services.actor_identifier import split_actor_names
from app.services.code_prefix_library import extract_code_prefix
from app.services.movie_author_resolver import JAVTXT_AUTHOR_MIN_RELEASE_DATE


YEAR_RE = re.compile(r'(19|20)\d{2}')


class ActorDetailLibrary:
    def __init__(self, database):
        self.database = database

    def get_actor_detail(self, actor_name):
        actor_name = str(actor_name or '').strip()
        if not actor_name:
            raise ValueError('缺少演员姓名')

        actor_row = self._find_actor(actor_name)
        local_videos = self._find_local_actor_videos(actor_name)
        web_movies = self.database.list_actor_movies(actor_name)
        eligible_web_movies = self._filter_eligible_movies(web_movies)
        enriched_eligible_count = self._count_enriched_eligible_movies(eligible_web_movies)
        web_record = self.database.get_actor_enrichment_record(actor_name)
        web_earliest, web_latest = self._collect_date_range(web_movies)

        return {
            'name': actor_name,
            'birthday': actor_row.get('birthday', ''),
            'age': actor_row.get('age', ''),
            'matched': bool(actor_row.get('matched')),
            'actor_id': actor_row.get('actor_id', '') or web_record.get('actor_id', ''),
            'local_video_count': len(local_videos),
            'local_prefix_distribution': self._build_prefix_distribution(local_videos),
            'local_year_distribution': self._build_year_distribution(local_videos),
            'web_enrichment_status': self._build_live_web_enrichment_status(web_record, eligible_web_movies),
            'web_total_pages': web_record.get('avfan_total_pages', 0),
            'web_total_videos': web_record.get('avfan_total_videos', 0),
            'eligible_video_count': len(eligible_web_movies),
            'eligible_enriched_video_count': enriched_eligible_count,
            'web_last_enriched_at': web_record.get('last_enriched_at', ''),
            'web_earliest_release_date': web_earliest,
            'web_latest_release_date': web_latest,
            'web_prefix_distribution': self._build_prefix_distribution(eligible_web_movies),
            'web_year_distribution': self._build_year_distribution(eligible_web_movies),
            'local_videos': local_videos,
            'web_movies': web_movies,
            'eligible_web_movies': eligible_web_movies,
        }

    def _find_actor(self, actor_name):
        for row in self.database.list_actors(actor_name):
            if str(row.get('name', '')).strip() == actor_name:
                return row
        return {
            'name': actor_name,
            'birthday': '',
            'age': '',
            'matched': False,
        }

    def _find_local_actor_videos(self, actor_name):
        matched = []
        for row in self.database.list_videos():
            actor_names = split_actor_names(row.get('author', ''))
            if actor_name in actor_names:
                matched.append(row)
        return matched

    def _filter_eligible_movies(self, rows):
        return [row for row in (rows or []) if self._is_eligible_movie(row)]

    def _count_enriched_eligible_movies(self, movies):
        return sum(
            1
            for movie in (movies or [])
            if normalize_second_source_actor_text((movie or {}).get('author', ''))
        )

    def _build_live_web_enrichment_status(self, enrichment, eligible_movies):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '')).strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '')).strip() or UNENRICHED_STATUS

        javtxt_record_status = str((enrichment or {}).get('javtxt_enrichment_status', '')).strip() or UNENRICHED_STATUS
        if eligible_movies and all(self._has_javtxt_author(movie) for movie in eligible_movies):
            javtxt_status = ENRICHED_STATUS
        elif javtxt_record_status == ENRICHED_STATUS:
            javtxt_status = UNENRICHED_STATUS
        else:
            javtxt_status = javtxt_record_status

        return build_library_enrichment_status_text(avfan_status, javtxt_status)

    @staticmethod
    def _has_javtxt_author(movie):
        return bool(normalize_second_source_actor_text((movie or {}).get('author', '')))

    def _build_prefix_distribution(self, rows):
        grouped = {}
        for row in rows:
            prefix = extract_code_prefix(row.get('code', '')) or '未知'
            grouped[prefix] = grouped.get(prefix, 0) + 1

        return [
            {'prefix': prefix, 'video_count': count}
            for prefix, count in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _build_year_distribution(self, rows):
        grouped = {}
        for row in rows:
            year = self._extract_year(row.get('release_date', ''))
            grouped[year] = grouped.get(year, 0) + 1

        known_items = [(year, count) for year, count in grouped.items() if year != '未知']
        unknown_items = [(year, count) for year, count in grouped.items() if year == '未知']
        known_items.sort(key=lambda item: (-int(item[0]), -item[1], item[0]))
        ordered = known_items + unknown_items
        return [{'year': year, 'video_count': count} for year, count in ordered]

    def _collect_date_range(self, rows):
        dates = sorted(
            str(row.get('release_date', '')).strip()
            for row in rows
            if str(row.get('release_date', '')).strip()
        )
        if not dates:
            return '', ''
        return dates[0], dates[-1]

    @staticmethod
    def _extract_year(release_date_text):
        text = str(release_date_text or '').strip()
        match = YEAR_RE.search(text)
        if not match:
            return '未知'
        return match.group(0)

    @staticmethod
    def _is_eligible_movie(movie):
        release_date_text = str((movie or {}).get('release_date', '') or '').strip()
        if not release_date_text:
            return False
        try:
            release_date = datetime.strptime(release_date_text, '%Y-%m-%d').date()
        except ValueError:
            return False
        return release_date >= JAVTXT_AUTHOR_MIN_RELEASE_DATE
