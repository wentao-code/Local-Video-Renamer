import json
import os
import tempfile
from pathlib import Path

from app.core.project_paths import QUERY_HISTORY_FILE
from app.gui.query_context import EntityReference


class QueryHistoryStore:
    def __init__(self, path=QUERY_HISTORY_FILE, max_items=30):
        self.path = Path(path)
        self.max_items = max(1, int(max_items or 30))

    def record_search(self, text):
        value = str(text or '').strip()
        if not value:
            return
        payload = self._load()
        payload['searches'] = self._prepend(value, payload.get('searches', []))
        self._save(payload)

    def record_entity(self, reference):
        if not isinstance(reference, EntityReference):
            return
        payload = self._load()
        entries = self._prepend(reference.as_dict(), payload.get('entities', []))
        payload['entities'] = entries
        self._save(payload)

    def record_query_context(self, context):
        if context is None:
            return
        self.record_search(getattr(context, 'search_text', ''))
        self.record_entity(getattr(context, 'entity', None))

    def recent_searches(self):
        return list(self._load().get('searches', []))

    def recent_entities(self):
        return [dict(item) for item in self._load().get('entities', []) if isinstance(item, dict)]

    def _load(self):
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            payload = {}
        return {
            'searches': list(payload.get('searches', [])) if isinstance(payload, dict) else [],
            'entities': list(payload.get('entities', [])) if isinstance(payload, dict) else [],
        }

    def _save(self, payload):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix=f'{self.path.name}.', suffix='.tmp', dir=str(self.path.parent))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(content)
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _prepend(self, value, items):
        values = [item for item in list(items or []) if item != value]
        return [value, *values[: self.max_items - 1]]
