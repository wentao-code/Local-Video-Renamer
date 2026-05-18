import sqlite3
from pathlib import Path


class VideoDatabase:
    def __init__(self, db_path='video_database.db'):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """初始化表结构（以 code 为主键实现绝对去重）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_videos (
                    code TEXT PRIMARY KEY,
                    title TEXT,
                    author TEXT,
                    duration TEXT,
                    size TEXT
                )
            ''')
            conn.commit()

    def save_plans(self, plans):
        """将扫描到的计划列表批量写入/更新到数据库"""
        if not plans:
            return 0

        success_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for plan in plans:
                cursor.execute('''
                    REPLACE INTO processed_videos (code, title, author, duration, size)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    plan.metadata.code,
                    plan.metadata.title,
                    plan.metadata.author,
                    plan.metadata.duration,
                    plan.metadata.size
                ))
                success_count += 1
            conn.commit()

        return success_count