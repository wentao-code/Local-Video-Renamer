from app.services.actor_identifier import split_actor_names


class CodePrefixDetailLibrary:
    def __init__(self, database):
        self.database = database

    def get_prefix_detail(self, prefix):
        prefix = str(prefix or '').strip().upper()
        if not prefix:
            raise ValueError('缺少番号前缀')

        enrichment = self.database.get_code_prefix_enrichment_record(prefix)
        movies = self.database.list_code_prefix_movies(prefix)
        earliest_release_date, latest_release_date = self._collect_date_range(movies)

        return {
            'prefix': prefix,
            'video_count': len(movies),
            'enrichment_status': enrichment.get('enrichment_status', ''),
            'avfan_total_pages': enrichment.get('avfan_total_pages', 0),
            'avfan_total_videos': enrichment.get('avfan_total_videos', 0),
            'last_enriched_at': enrichment.get('last_enriched_at', ''),
            'earliest_release_date': earliest_release_date,
            'latest_release_date': latest_release_date,
            'year_distribution': self._build_year_distribution(movies),
            'top_actors': self._build_top_actors(movies),
            'movies': movies,
        }

    def _collect_date_range(self, movies):
        dates = sorted(
            movie.get('release_date', '').strip()
            for movie in movies
            if str(movie.get('release_date', '')).strip()
        )
        if not dates:
            return '', ''
        return dates[0], dates[-1]

    def _build_year_distribution(self, movies):
        grouped = {}
        for movie in movies:
            release_date = str(movie.get('release_date', '')).strip()
            year = release_date[:4] if len(release_date) >= 4 and release_date[:4].isdigit() else '未知'
            grouped[year] = grouped.get(year, 0) + 1

        ordered = sorted(
            grouped.items(),
            key=lambda item: ('0000' if item[0] == '未知' else item[0], item[1]),
            reverse=True,
        )
        return [{'year': year, 'video_count': count} for year, count in ordered]

    def _build_top_actors(self, movies):
        grouped = {}
        for movie in movies:
            author = str(movie.get('author', '')).strip()
            if not author:
                continue
            actor_names = split_actor_names(author) or [author]
            for actor_name in actor_names:
                normalized = str(actor_name or '').strip()
                if not normalized:
                    continue
                grouped[normalized] = grouped.get(normalized, 0) + 1

        ordered = sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
        return [{'name': name, 'video_count': count} for name, count in ordered[:10]]
