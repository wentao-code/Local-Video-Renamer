from datetime import datetime

from app.core.runtime_config import get_avfan_profile_dir
from app.core.app_config import get_setting


class AccountRepositoryMixin:
    def _ensure_account_tables(self, cursor):
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS scraper_accounts (
                account_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_name TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL DEFAULT '',
                password TEXT NOT NULL DEFAULT '',
                profile_dir TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                login_status TEXT NOT NULL DEFAULT '未检测',
                last_checked_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cursor.execute(
            '''INSERT INTO scraper_accounts (account_name, profile_dir)
               SELECT '默认账号', ?
               WHERE NOT EXISTS (SELECT 1 FROM scraper_accounts)''',
            (str(get_avfan_profile_dir()),),
        )
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS scraper_account_check_logs (
                check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                current_url TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES scraper_accounts(account_id) ON DELETE CASCADE
            )'''
        )
        cursor.execute(
            '''CREATE INDEX IF NOT EXISTS idx_scraper_account_check_logs_account_time
            ON scraper_account_check_logs(account_id, finished_at DESC)'''
        )
        self._ensure_column(cursor, 'scraper_accounts', 'manual_verification_until', 'REAL NOT NULL DEFAULT 0')
        self._ensure_column(cursor, 'scraper_accounts', 'username', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(cursor, 'scraper_accounts', 'password', "TEXT NOT NULL DEFAULT ''")
        cursor.execute(
            '''UPDATE scraper_accounts
               SET username = ?, password = ?
               WHERE account_name = '默认账号' AND username = '' AND password = '' ''',
            (
                str(get_setting('SCRAPER_USERNAME', default='') or '').strip(),
                str(get_setting('SCRAPER_PASSWORD', default='') or '').strip(),
            ),
        )

    def create_scraper_account(self, account_name, profile_dir, username='', password=''):
        name = str(account_name or '').strip()
        profile = str(profile_dir or '').strip()
        if not name or not profile:
            raise ValueError('账号名称和浏览器 profile 不能为空')
        with self._connect() as conn:
            cursor = conn.execute(
                '''INSERT INTO scraper_accounts (account_name, username, password, profile_dir)
                   VALUES (?, ?, ?, ?)''',
                (name, str(username or '').strip(), str(password or ''), profile),
            )
            conn.commit()
            return self.get_scraper_account(cursor.lastrowid)

    def list_scraper_accounts(self, enabled_only=False):
        where = 'WHERE enabled = 1' if enabled_only else ''
        with self._connect() as conn:
            rows = conn.execute(
                f'SELECT * FROM scraper_accounts {where} ORDER BY account_id'
            ).fetchall()
            columns = [item[0] for item in conn.execute('SELECT * FROM scraper_accounts LIMIT 0').description]
        return [dict(zip(columns, row)) for row in rows]

    def get_scraper_account(self, account_id):
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM scraper_accounts WHERE account_id = ?',
                (int(account_id),),
            ).fetchone()
            if row is None:
                return None
            columns = [item[0] for item in conn.execute('SELECT * FROM scraper_accounts LIMIT 0').description]
        return dict(zip(columns, row))

    def update_scraper_account(self, account_id, **changes):
        allowed = {
            'account_name', 'username', 'password', 'profile_dir', 'enabled', 'login_status', 'last_checked_at', 'last_error',
            'manual_verification_until',
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            return self.get_scraper_account(account_id)
        assignments = ', '.join(f'{key} = ?' for key in values)
        with self._connect() as conn:
            conn.execute(
                f'UPDATE scraper_accounts SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE account_id = ?',
                [*values.values(), int(account_id)],
            )
            conn.commit()
        return self.get_scraper_account(account_id)

    def set_scraper_account_status(self, account_id, status, error=''):
        return self.update_scraper_account(
            account_id,
            login_status=str(status or '').strip() or '未检测',
            last_checked_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            last_error=str(error or '').strip(),
        )

    def set_scraper_account_manual_verification_cooldown(self, account_id, cooldown_until):
        return self.update_scraper_account(
            account_id,
            manual_verification_until=float(cooldown_until or 0),
        )

    def record_scraper_account_check(
        self,
        account_id,
        status,
        message='',
        current_url='',
        started_at=None,
        finished_at=None,
    ):
        checked_at = finished_at or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        started = started_at or checked_at
        normalized_status = str(status or '').strip() or '检测失败'
        normalized_message = str(message or '').strip()
        last_error = normalized_message if normalized_status != '已登录' else ''
        with self._connect() as conn:
            conn.execute(
                '''UPDATE scraper_accounts
                   SET login_status = ?, last_checked_at = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE account_id = ?''',
                (normalized_status, checked_at, last_error, int(account_id)),
            )
            conn.execute(
                '''INSERT INTO scraper_account_check_logs
                   (account_id, status, message, current_url, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (int(account_id), normalized_status, normalized_message, str(current_url or ''), started, checked_at),
            )
            conn.commit()
        return self.get_scraper_account(account_id)

    def list_scraper_account_check_history(self, account_id=None, limit=50):
        params = []
        where = ''
        if account_id:
            where = 'WHERE account_id = ?'
            params.append(int(account_id))
        safe_limit = max(1, min(int(limit or 50), 500))
        params.append(safe_limit)
        with self._connect() as conn:
            rows = conn.execute(
                f'''SELECT check_id, account_id, status, message, current_url,
                           started_at, finished_at
                    FROM scraper_account_check_logs
                    {where}
                    ORDER BY finished_at DESC, check_id DESC
                    LIMIT ?''',
                params,
            ).fetchall()
            columns = [item[0] for item in conn.execute(
                'SELECT check_id, account_id, status, message, current_url, started_at, finished_at '
                'FROM scraper_account_check_logs LIMIT 0'
            ).description]
        return [dict(zip(columns, row)) for row in rows]
