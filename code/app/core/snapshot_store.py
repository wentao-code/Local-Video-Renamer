import json
from pathlib import Path, PurePosixPath

try:
    import msgpack as _msgpack
except ImportError:  # JSON compatibility must keep the backend startable.
    _msgpack = None


class SnapshotStore:
    """Persist page snapshots in separate MessagePack and JSON trees."""

    def __init__(self, root_dir, messagepack_available=None):
        self.root_dir = Path(root_dir)
        self.messagepack_dir = self.root_dir / 'messagepack'
        self.json_dir = self.root_dir / 'json'
        if messagepack_available is False:
            self._msgpack = None
        else:
            self._msgpack = _msgpack

    @property
    def messagepack_available(self):
        return self._msgpack is not None

    def messagepack_path(self, key):
        return self.messagepack_dir.joinpath(*self._key_parts(key)).with_suffix('.msgpack')

    def json_path(self, key):
        return self.json_dir.joinpath(*self._key_parts(key)).with_suffix('.json')

    def read(self, key, legacy_paths=()):
        messagepack_path = self.messagepack_path(key)
        if self.messagepack_available and messagepack_path.exists():
            try:
                return self._msgpack.unpackb(
                    messagepack_path.read_bytes(),
                    raw=False,
                    strict_map_key=False,
                )
            except Exception:
                pass

        json_path = self.json_path(key)
        if json_path.exists():
            try:
                payload = json.loads(json_path.read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError):
                payload = None
            if payload is not None:
                if self.messagepack_available:
                    self._write_messagepack(messagepack_path, payload)
                return payload

        for legacy_path in legacy_paths or ():
            payload = self._read_legacy(Path(legacy_path))
            if payload is None:
                continue
            self.write(key, payload)
            return payload
        return None

    def write(self, key, payload):
        messagepack_path = self.messagepack_path(key)
        json_path = self.json_path(key)
        if self.messagepack_available:
            self._write_messagepack(messagepack_path, payload)
        self._atomic_write(
            json_path,
            json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
        )

    def delete(self, key):
        for path in (self.messagepack_path(key), self.json_path(key)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue

    def delete_prefix(self, prefix):
        parts = self._key_parts(prefix)
        for root in (self.messagepack_dir, self.json_dir):
            target = root.joinpath(*parts)
            if target.is_file():
                try:
                    target.unlink()
                except OSError:
                    pass
                continue
            if not target.is_dir():
                continue
            try:
                paths = sorted(target.rglob('*'), key=lambda path: len(path.parts), reverse=True)
            except OSError:
                continue
            for path in paths:
                try:
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                except OSError:
                    continue
            try:
                target.rmdir()
            except OSError:
                pass

    def iter_keys(self, prefix):
        parts = self._key_parts(prefix)
        normalized_prefix = '/'.join(parts)
        keys = set()
        for root, suffix in (
            (self.messagepack_dir, '.msgpack'),
            (self.json_dir, '.json'),
        ):
            target = root.joinpath(*parts)
            if not target.is_dir():
                continue
            try:
                paths = target.rglob(f'*{suffix}')
                for path in paths:
                    relative = path.relative_to(root).with_suffix('')
                    keys.add(relative.as_posix())
            except OSError:
                continue
        return sorted(key for key in keys if key == normalized_prefix or key.startswith(normalized_prefix + '/'))

    def _write_messagepack(self, path, payload):
        try:
            packed = self._msgpack.packb(payload, use_bin_type=True)
            self._atomic_write(path, packed)
        except (OSError, TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _atomic_write(path, content):
        path = Path(path)
        temp_path = path.with_suffix(path.suffix + '.tmp')
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content)
        temp_path.replace(path)

    def _read_legacy(self, path):
        try:
            if not path.exists():
                return None
            if path.suffix.lower() in {'.msgpack', '.mpk'} and self.messagepack_available:
                return self._msgpack.unpackb(path.read_bytes(), raw=False, strict_map_key=False)
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            return None

    @staticmethod
    def _key_parts(key):
        normalized = str(key or '').strip().replace('\\', '/')
        pure_path = PurePosixPath(normalized)
        parts = pure_path.parts
        if (
            not normalized
            or pure_path.is_absolute()
            or not parts
            or any(part in {'', '.', '..'} for part in parts)
            or ':' in parts[0]
        ):
            raise ValueError(f'Unsafe snapshot key: {key!r}')
        return parts
