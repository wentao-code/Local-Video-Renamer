"""Run one due Quark backup from Windows Task Scheduler."""

from __future__ import annotations

import sys
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from app.core.app_logging import configure_logging
from app.core.project_paths import ensure_storage_layout
from app.services.system.quark_backup_service import QuarkBackupService


def main():
    ensure_storage_layout()
    configure_logging()
    result = QuarkBackupService().run_if_due()
    status = str(result.get('status', '') or '')
    if status == 'login_required':
        return 2
    return 1 if status == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
