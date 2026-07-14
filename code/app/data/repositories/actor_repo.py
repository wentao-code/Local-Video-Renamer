from app.services.identity import is_ignored_actor_name


class ActorRepositoryMixin:
    def list_hidden_actors(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM hidden_actors')
            return {
                str(row[0] or '').strip()
                for row in cursor.fetchall()
                if str(row[0] or '').strip()
            }

    def is_actor_blacklisted(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return False
        with self._connect() as conn:
            row = conn.execute(
                'SELECT 1 FROM hidden_actors WHERE name = ?',
                (normalized_name,),
            ).fetchone()
        return row is not None

    def insert_missing_actors(self, actors):
        hidden_actors = self.list_hidden_actors()
        normalized_actors = []
        seen = set()
        for actor in actors or []:
            name = str((actor or {}).get('name', '')).strip()
            if (
                not name
                or is_ignored_actor_name(name)
                or name in seen
                or name in hidden_actors
            ):
                continue
            seen.add(name)
            normalized_actors.append(
                {
                    'name': name,
                    'birthday': str((actor or {}).get('birthday', '') or '').strip(),
                    'age': str((actor or {}).get('age', '') or '').strip(),
                    'matched': 1 if bool((actor or {}).get('matched')) else 0,
                }
            )

        if not normalized_actors:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                INSERT OR IGNORE INTO actors (name, birthday, age, matched)
                VALUES (?, ?, ?, ?)
                ''',
                [
                    (
                        actor['name'],
                        actor['birthday'],
                        actor['age'],
                        actor['matched'],
                    )
                    for actor in normalized_actors
                ],
            )
            conn.commit()
            return int(cursor.rowcount or 0)
