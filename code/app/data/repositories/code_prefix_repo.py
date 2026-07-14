class CodePrefixRepositoryMixin:
    def list_hidden_code_prefixes(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT prefix FROM hidden_code_prefixes')
            return {
                str(row[0] or '').strip().upper()
                for row in cursor.fetchall()
                if str(row[0] or '').strip()
            }
