from pathlib import Path

from database_handler import VideoDatabase
from video_models import plan_from_dict, plan_to_dict, result_to_dict
from video_renamer_api import VideoRenamerAPI


class BackendService:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent)
        self.csv_path = self.base_dir / '目录统计 - 详细介绍.csv'
        self.db = VideoDatabase(self.base_dir / 'video_database.db')
        self.renamer = VideoRenamerAPI(self.csv_path)
        self.database_loaded = False

    def load_database(self):
        video_db = self.renamer.load_database()
        self.database_loaded = True
        return {'count': len(video_db), 'csv_path': str(self.csv_path)}

    def ensure_database_loaded(self):
        if not self.database_loaded:
            self.load_database()

    def health(self):
        return {
            'ok': True,
            'database_loaded': self.database_loaded,
            'csv_exists': self.csv_path.exists(),
            'csv_path': str(self.csv_path),
            'db_path': str(self.db.db_path),
        }

    def scan(self, folder_path):
        self.ensure_database_loaded()
        plans = self.renamer.scan_folder(folder_path)
        return {
            'plans': [plan_to_dict(plan) for plan in plans],
            'count': len(plans),
            'rename_count': sum(1 for plan in plans if plan.needs_rename),
        }

    def rename(self, plans_data):
        plans = [plan_from_dict(plan) for plan in plans_data]
        results = self.renamer.execute_renames(plans)
        return {
            'results': [result_to_dict(result) for result in results],
            'success_count': sum(1 for result in results if result.success and result.message == '完成'),
        }

    def save_plans(self, plans_data):
        plans = [plan_from_dict(plan) for plan in plans_data]
        return {'success_count': self.db.save_plans(plans)}

    def list_videos(self, search_text=''):
        return {'videos': self.db.list_videos(search_text)}
