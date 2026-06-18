from app.core.filename_rules import DEFAULT_VIDEO_EXTS
from app.services.local_video import LocalVideoImportService, LocalVideoRenameService, LocalVideoScanService


class LocalVideoLibraryService:
    def __init__(self, database, video_exts=DEFAULT_VIDEO_EXTS):
        self.scan_service = LocalVideoScanService(database, video_exts=video_exts)
        self.import_service = LocalVideoImportService(database)
        self.rename_service = LocalVideoRenameService()

    def scan_folder(self, folder_path):
        return self.scan_service.scan_folder(folder_path)

    def import_videos(self, plans_data):
        return self.import_service.import_videos(plans_data)

    def execute_renames(self, plans_data):
        return self.rename_service.execute_renames(plans_data)
