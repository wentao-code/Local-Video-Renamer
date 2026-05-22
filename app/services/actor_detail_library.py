import re

from app.services.code_prefix_library import extract_code_prefix


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
        web_record = self.database.get_actor_enrichment_record(actor_name)
        web_earliest, web_latest = self._collect_date_range(web_movies)

        return {
            'name': actor_name,
            'birthday': actor_row.get('birthday', ''),
            'age': actor_row.get('age', ''),
            'matched': bool(actor_row.get('matched')),
            'local_video_count': len(local_videos),
            'local_prefix_distribution': self._build_prefix_distribution(local_videos),
            'local_year_distribution': self._build_year_distribution(local_videos),
            'web_enrichment_status': web_record.get('enrichment_status', ''),
            'web_total_pages': web_record.get('avfan_total_pages', 0),
            'web_total_videos': web_record.get('avfan_total_videos', 0),
            'web_last_enriched_at': web_record.get('last_enriched_at', ''),
            'web_earliest_release_date': web_earliest,
            'web_latest_release_date': web_latest,
            'web_prefix_distribution': self._build_prefix_distribution(web_movies),
            'web_year_distribution': self._build_year_distribution(web_movies),
            'web_movies': web_movies,
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

        ordered = sorted(
            grouped.items(),
            key=lambda item: ('0000' if item[0] == '未知' else item[0], item[1]),
            reverse=True,
        )
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
