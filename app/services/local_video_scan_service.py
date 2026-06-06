from pathlib import Path

from app.core.filename_rules import DEFAULT_VIDEO_EXTS, build_normalized_filename, extract_code_from_filename
from app.core.local_video_labels import build_preview_name, build_row_status
from app.core.video_models import RenamePlan, VideoMetadata, plan_to_dict
from app.services.local_video_media_info import read_local_video_media_info
from app.services.path_library import get_storage_location_name


class LocalVideoScanService:
    def __init__(self, database, video_exts=DEFAULT_VIDEO_EXTS):
        self.database = database
        self.video_exts = tuple(ext.lower() for ext in video_exts)

    def scan_folder(self, folder_path):
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f'文件夹不存在: {folder}')

        scanned_files = self._collect_video_files(folder)
        existing_records = self.database.get_videos_by_codes([entry['code'] for entry in scanned_files])
        storage_location = get_storage_location_name(folder)

        plans = []
        import_count = 0
        rename_count = 0

        for entry in scanned_files:
            db_record = existing_records.get(entry['code'], {})
            plan_data = self._build_plan_data(entry, db_record, storage_location)
            plans.append(plan_data)

            if plan_data['import_required']:
                import_count += 1
            if plan_data['can_rename'] and plan_data['needs_rename']:
                rename_count += 1

        return {
            'plans': plans,
            'count': len(plans),
            'rename_count': rename_count,
            'import_count': import_count,
        }

    def _collect_video_files(self, folder):
        scanned_files = []
        for file_path in folder.rglob('*'):
            if not file_path.is_file() or file_path.suffix.lower() not in self.video_exts:
                continue

            code = extract_code_from_filename(file_path.stem)
            if not code:
                continue

            media_info = read_local_video_media_info(file_path)
            scanned_files.append(
                {
                    'file_path': file_path,
                    'code': code,
                    'duration': media_info.duration,
                    'size_on_disk': media_info.size_gb,
                }
            )
        return scanned_files

    def _build_plan_data(self, entry, db_record, storage_location):
        exists_in_db = bool(db_record)
        can_rename = bool(str(db_record.get('title', '')).strip())
        metadata = VideoMetadata(
            code=entry['code'],
            title=str(db_record.get('title', '')).strip(),
            author=str(db_record.get('author', '')).strip(),
            duration=str(entry.get('duration', '')).strip() or str(db_record.get('duration', '')).strip(),
            size=str(entry.get('size_on_disk', '')).strip() or str(db_record.get('size', '')).strip(),
        )
        new_path = entry['file_path']
        if can_rename:
            new_path = entry['file_path'].parent / build_normalized_filename(metadata, entry['file_path'].suffix)

        plan = RenamePlan(entry['file_path'], new_path, metadata, storage_location)
        plan_data = plan_to_dict(plan)
        plan_data.update(
            {
                'code': entry['code'],
                'exists_in_db': exists_in_db,
                'import_required': not exists_in_db,
                'can_rename': can_rename,
                'preview_name': build_preview_name(plan.new_name, exists_in_db, can_rename),
                'row_status': build_row_status(plan.needs_rename, exists_in_db, can_rename),
                'size_on_disk': entry['size_on_disk'],
            }
        )
        return plan_data
