from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.project_paths import ERROR_LOG_FILE, HTTP_ACCESS_LOG_FILE, LOG_DIR


DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_MAX_TOTAL_BYTES = 100 * 1024 * 1024
_RUN_ID = ContextVar('app_log_run_id', default='')
_CORRELATION_ID = ContextVar('app_log_correlation_id', default='')
_CONFIG_LOCK = threading.Lock()
_HANDLER_FLAG = '_local_video_renamer_logging_handler'
_MODULE_LOGGERS = {
    'app.backend': 'backend',
    'app.gui': 'gui',
    'app.services.enrichment': 'enrichment',
    'app.task': 'enrichment',
    'app.queen_library': 'queen_library',
    'app.scraper': 'scraper',
    'app.services': 'services',
    'app.data': 'data',
    'app.core': 'core',
    'app.tools': 'tools',
    'app.system': 'app',
}


class _ContextFilter(logging.Filter):
    def filter(self, record):
        record.run_id = str(getattr(record, 'run_id', '') or get_run_id() or '-')
        record.correlation_id = str(
            getattr(record, 'correlation_id', '') or get_correlation_id() or '-'
        )
        return True


def new_correlation_id(prefix='corr'):
    normalized_prefix = str(prefix or 'corr').strip() or 'corr'
    return f'{normalized_prefix}-{uuid.uuid4().hex[:12]}'


def new_run_id(kind='run', key=''):
    normalized_kind = str(kind or 'run').strip() or 'run'
    normalized_key = str(key or '').strip().replace(' ', '_')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    suffix = uuid.uuid4().hex[:6]
    return '_'.join(part for part in (timestamp, normalized_kind, normalized_key, suffix) if part)


def get_run_id():
    return str(_RUN_ID.get() or '')


def get_correlation_id():
    return str(_CORRELATION_ID.get() or '')


def bind_log_context(run_id='', correlation_id=''):
    return (
        _RUN_ID.set(str(run_id or get_run_id() or '')),
        _CORRELATION_ID.set(str(correlation_id or get_correlation_id() or '')),
    )


def reset_log_context(tokens):
    run_token, correlation_token = tokens
    _RUN_ID.reset(run_token)
    _CORRELATION_ID.reset(correlation_token)


@contextmanager
def log_context(run_id='', correlation_id=''):
    tokens = bind_log_context(run_id, correlation_id)
    try:
        yield
    finally:
        reset_log_context(tokens)


def get_logger(name):
    return logging.getLogger(name)


def configure_logging(
    log_dir=None,
    *,
    max_bytes=DEFAULT_MAX_BYTES,
    backup_count=DEFAULT_BACKUP_COUNT,
    max_age_days=DEFAULT_MAX_AGE_DAYS,
    max_total_bytes=DEFAULT_MAX_TOTAL_BYTES,
    force=False,
):
    # Logging failures must never block application work or fill a captured
    # stderr pipe when Windows prevents a multi-process log rollover.
    logging.raiseExceptions = False
    target_dir = Path(log_dir) if log_dir else LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    cleanup_old_logs(target_dir, max_age_days=max_age_days, max_total_bytes=max_total_bytes)

    with _CONFIG_LOCK:
        root_logger = logging.getLogger()
        access_logger = logging.getLogger('app.http_access')
        module_loggers = [logging.getLogger(name) for name in _MODULE_LOGGERS]
        existing_handlers = [
            handler
            for logger in (root_logger, access_logger, *module_loggers)
            for handler in list(logger.handlers)
            if getattr(handler, _HANDLER_FLAG, False)
        ]
        expected_log_dir = target_dir.resolve()
        if existing_handlers and not force:
            handler_dirs = {
                Path(handler.baseFilename).parent.resolve()
                for handler in existing_handlers
                if getattr(handler, 'baseFilename', '')
            }
            if handler_dirs == {expected_log_dir}:
                return target_dir
        for logger in (root_logger, access_logger, *module_loggers):
            for handler in list(logger.handlers):
                if getattr(handler, _HANDLER_FLAG, False):
                    logger.removeHandler(handler)
                    handler.close()

        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s [run_id=%(run_id)s correlation_id=%(correlation_id)s] %(message)s'
        )
        context_filter = _ContextFilter()
        error_handler = _build_rotating_handler(
            target_dir / ERROR_LOG_FILE.name, logging.ERROR, formatter, context_filter, max_bytes, backup_count
        )
        access_handler = _build_rotating_handler(
            target_dir / HTTP_ACCESS_LOG_FILE.name,
            logging.INFO,
            logging.Formatter('%(message)s'),
            None,
            max_bytes,
            backup_count,
        )
        root_logger.setLevel(logging.ERROR)
        root_logger.addHandler(error_handler)
        access_logger.setLevel(logging.INFO)
        access_logger.propagate = False
        access_logger.addHandler(access_handler)
        configured_files = {}
        for logger_name, module_name in _MODULE_LOGGERS.items():
            module_logger = logging.getLogger(logger_name)
            module_logger.setLevel(logging.INFO)
            module_logger.propagate = True
            log_file = configured_files.setdefault(module_name, target_dir / f'{module_name}.log')
            module_logger.addHandler(
                _build_rotating_handler(
                    log_file,
                    logging.INFO,
                    formatter,
                    context_filter,
                    max_bytes,
                    backup_count,
                )
            )
    logging.getLogger('app.system').info('日志系统已初始化')
    return target_dir


def _build_rotating_handler(path, level, formatter, context_filter, max_bytes, backup_count):
    handler = RotatingFileHandler(
        path,
        maxBytes=max(1, int(max_bytes or DEFAULT_MAX_BYTES)),
        backupCount=max(1, int(backup_count or DEFAULT_BACKUP_COUNT)),
        encoding='utf-8',
        delay=True,
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    if context_filter is not None:
        handler.addFilter(context_filter)
    setattr(handler, _HANDLER_FLAG, True)
    return handler


def cleanup_old_logs(log_dir=None, *, max_age_days=DEFAULT_MAX_AGE_DAYS, max_total_bytes=DEFAULT_MAX_TOTAL_BYTES):
    target_dir = Path(log_dir) if log_dir else LOG_DIR
    if not target_dir.exists():
        return
    now = time.time()
    max_age_seconds = max(0, int(max_age_days or 0)) * 24 * 60 * 60
    log_files = [path for path in target_dir.glob('*.log*') if path.is_file()]
    for path in log_files:
        try:
            if max_age_seconds and now - path.stat().st_mtime > max_age_seconds:
                path.unlink()
        except OSError:
            continue

    remaining = []
    for path in target_dir.glob('*.log*'):
        try:
            if path.is_file():
                stat = path.stat()
                remaining.append((path, stat.st_mtime, stat.st_size))
        except OSError:
            continue
    total_size = sum(item[2] for item in remaining)
    for path, _, size in sorted(remaining, key=lambda item: item[1]):
        if total_size <= max(0, int(max_total_bytes or 0)):
            break
        try:
            path.unlink()
            total_size -= size
        except OSError:
            continue


def log_http_access(method, path, status, duration_ms, request_id, **fields):
    payload = {
        'timestamp': datetime.now().isoformat(timespec='milliseconds'),
        'method': str(method or ''),
        'path': str(path or ''),
        'status': int(status or 0),
        'duration_ms': round(float(duration_ms or 0), 3),
        'request_id': str(request_id or ''),
        **{key: value for key, value in fields.items() if value not in (None, '')},
    }
    logging.getLogger('app.http_access').info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def append_jsonl_log(
    path,
    payload,
    *,
    run_id='',
    correlation_id='',
    max_bytes=DEFAULT_MAX_BYTES,
    backup_count=3,
):
    target = Path(path)
    record = {
        **dict(payload or {}),
        'run_id': str(run_id or get_run_id() or new_run_id('runtime')),
        'correlation_id': str(correlation_id or get_correlation_id() or new_correlation_id()),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size >= max(1, int(max_bytes or DEFAULT_MAX_BYTES)):
            for index in range(max(1, int(backup_count or 1)), 0, -1):
                rotated = target.with_suffix(f'{target.suffix}.{index}')
                previous = target if index == 1 else target.with_suffix(f'{target.suffix}.{index - 1}')
                if rotated.exists():
                    rotated.unlink()
                if previous.exists():
                    previous.replace(rotated)
        with target.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    except OSError:
        return record
    return record


def install_global_exception_hooks(component='application'):
    logger = get_logger('app.unhandled')
    original_sys_hook = sys.excepthook
    original_thread_hook = getattr(threading, 'excepthook', None)

    def log_unhandled(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return original_sys_hook(exc_type, exc_value, exc_traceback)
        logger.critical('%s 未捕获异常', component, exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = log_unhandled
    if original_thread_hook is not None:
        def log_thread_exception(args):
            logger.critical(
                '%s 线程未捕获异常 thread=%s',
                component,
                getattr(getattr(args, 'thread', None), 'name', ''),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        threading.excepthook = log_thread_exception


def log_exception(logger, message, **fields):
    field_text = ' | '.join(f'{key}={value}' for key, value in sorted(fields.items()))
    logger.exception('%s%s', message, f' | {field_text}' if field_text else '')
