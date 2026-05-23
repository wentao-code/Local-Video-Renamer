from pathlib import Path

from app.core.local_video_labels import (
    ALREADY_NORMALIZED_MESSAGE,
    RENAME_COMPLETED_MESSAGE,
    RENAME_SKIPPED_MESSAGE,
    TARGET_EXISTS_MESSAGE,
)
from app.core.video_models import RenamePlan, RenameResult, VideoMetadata, plan_to_dict, result_to_dict


class LocalVideoRenameService:
    def execute_renames(self, plans_data):
        results = []
        success_count = 0

        for plan_data in plans_data or []:
            plan = self._build_plan(plan_data)
            if not bool(plan_data.get('can_rename')):
                results.append(
                    {
                        'plan': plan_to_dict(plan),
                        'success': False,
                        'message': RENAME_SKIPPED_MESSAGE,
                        'error': '',
                    }
                )
                continue

            try:
                if not plan.needs_rename:
                    results.append(result_to_dict(RenameResult(plan, True, ALREADY_NORMALIZED_MESSAGE)))
                    continue

                if plan.new_path.exists():
                    results.append(result_to_dict(RenameResult(plan, False, TARGET_EXISTS_MESSAGE)))
                    continue

                plan.old_path.rename(plan.new_path)
                results.append(result_to_dict(RenameResult(plan, True, RENAME_COMPLETED_MESSAGE)))
                success_count += 1
            except Exception as exc:
                results.append(result_to_dict(RenameResult(plan, False, '错误', str(exc))))

        return {
            'results': results,
            'success_count': success_count,
        }

    @staticmethod
    def _build_plan(plan_data):
        metadata = plan_data.get('metadata') or {}
        return RenamePlan(
            old_path=Path(plan_data['old_path']),
            new_path=Path(plan_data['new_path']),
            metadata=VideoMetadata(
                code=metadata.get('code', ''),
                title=metadata.get('title', ''),
                author=metadata.get('author', ''),
                duration=metadata.get('duration', ''),
                size=metadata.get('size', ''),
            ),
            storage_location=plan_data.get('storage_location', ''),
        )
