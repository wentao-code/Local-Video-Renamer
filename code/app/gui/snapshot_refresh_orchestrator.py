"""Independent, resumable orchestration for full snapshot refreshes."""

import json
from datetime import datetime
from pathlib import Path


def _now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


class SnapshotRefreshOrchestrator:
    def __init__(self, state_path, max_attempts=3):
        self.state_path = Path(state_path)
        self.max_attempts = max(1, int(max_attempts or 1))

    def run(self, steps):
        normalized_steps = [
            dict(step or {})
            for step in steps or []
            if str((step or {}).get('key', '') or '').strip()
            and callable((step or {}).get('runner'))
        ]
        state = self._load_state()
        if state.get('status') == 'completed':
            state = self._new_state()

        state['status'] = 'running'
        state['updated_at'] = _now_text()
        state['step_order'] = [str(step['key']).strip() for step in normalized_steps]
        state.setdefault('steps', {})
        self._save_state(state)

        completed = []
        skipped = []
        failed = []
        for step in normalized_steps:
            key = str(step['key']).strip()
            entry = dict(state['steps'].get(key) or {})
            if entry.get('status') == 'completed':
                skipped.append(key)
                continue

            entry.update({'key': key, 'status': 'running', 'attempts': 0})
            state['steps'][key] = entry
            self._save_state(state)
            error_text = ''
            while entry['attempts'] < self.max_attempts:
                entry['attempts'] += 1
                entry['started_at'] = _now_text()
                state['updated_at'] = entry['started_at']
                self._save_state(state)
                try:
                    step_result = step['runner']()
                except Exception as exc:
                    error_text = str(exc or '快照刷新失败')
                    entry.update({'status': 'failed', 'last_error': error_text})
                    self._save_state(state)
                    continue
                entry.update(
                    {
                        'status': 'completed',
                        'completed_at': _now_text(),
                        'last_error': '',
                    }
                )
                if isinstance(step_result, dict):
                    entry['result'] = dict(step_result)
                state['updated_at'] = entry['completed_at']
                self._save_state(state)
                completed.append(key)
                break
            else:
                entry.update({'status': 'failed', 'last_error': error_text})
                failed.append(
                    {
                        'key': key,
                        'error': error_text,
                        'attempts': int(entry.get('attempts', 0) or 0),
                    }
                )
                self._save_state(state)

        state['status'] = 'partial' if failed else 'completed'
        state['updated_at'] = _now_text()
        self._save_state(state)
        return {
            'status': state['status'],
            'completed': completed,
            'skipped': skipped,
            'failed': failed,
            'steps': dict(state.get('steps') or {}),
        }

    def _new_state(self):
        return {'version': 1, 'status': 'new', 'step_order': [], 'steps': {}}

    def _load_state(self):
        try:
            payload = json.loads(self.state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return self._new_state()
        if not isinstance(payload, dict) or not isinstance(payload.get('steps'), dict):
            return self._new_state()
        return payload

    def _save_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix(self.state_path.suffix + '.tmp')
        temporary_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        temporary_path.replace(self.state_path)
