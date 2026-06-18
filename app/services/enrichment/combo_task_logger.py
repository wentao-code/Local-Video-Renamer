from __future__ import annotations

from app.core.project_paths import COMBO_TASK_LOG_DIR
from app.services.enrichment import TaskTraceLogger


class ComboTaskLogger(TaskTraceLogger):
    def __init__(self, combo_key, combo_label, log_dir=None):
        self.combo_key = str(combo_key or '').strip()
        self.combo_label = str(combo_label or '').strip()
        super().__init__(
            task_kind='combo',
            task_key=self.combo_key,
            task_label=self.combo_label,
            log_dir=log_dir or COMBO_TASK_LOG_DIR,
            keep_count=4,
        )
