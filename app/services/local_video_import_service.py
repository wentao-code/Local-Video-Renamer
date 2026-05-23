class LocalVideoImportService:
    def __init__(self, database):
        self.database = database

    def import_videos(self, plans_data):
        records = []
        for plan in plans_data or []:
            metadata = plan.get('metadata') or {}
            code = (metadata.get('code') or plan.get('code') or '').strip().upper()
            if not code:
                continue

            records.append(
                {
                    'code': code,
                    'storage_location': plan.get('storage_location', ''),
                    'size': metadata.get('size') or plan.get('size_on_disk', ''),
                }
            )

        return self.database.import_local_videos(records)
