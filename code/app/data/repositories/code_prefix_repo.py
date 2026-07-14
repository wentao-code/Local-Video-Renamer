class CodePrefixRepositoryMixin:
    def is_code_prefix_blacklisted(self, prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            return False
        with self._connect() as conn:
            row = conn.execute(
                'SELECT 1 FROM hidden_code_prefixes WHERE prefix = ? LIMIT 1',
                (normalized_prefix,),
            ).fetchone()
        return row is not None

    def list_hidden_code_prefixes(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT prefix FROM hidden_code_prefixes')
            return {
                str(row[0] or '').strip().upper()
                for row in cursor.fetchall()
                if str(row[0] or '').strip()
            }
