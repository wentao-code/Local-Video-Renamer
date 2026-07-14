import json
import logging
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from app.backend.server import make_handler
from app.backend.service import BackendService
from app.core.app_logging import cleanup_old_logs, configure_logging, log_context
from app.core.project_paths import LOG_DIR
from app.queen_library.service import QueenLibraryService
from app.services.enrichment.enrichment_progress_service import EnrichmentProgressService
from app.services.enrichment.task_trace_logger import TaskTraceLogger


class _HealthService:
    def health(self):
        return {'ok': True}


class AppLoggingTest(unittest.TestCase):
    def test_configure_logging_routes_each_functional_module_to_its_own_log_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            configure_logging(log_dir=log_dir, force=True, max_bytes=1024, backup_count=2)

            logging.getLogger('app.backend.test').info('backend event')
            logging.getLogger('app.gui.test').info('gui event')
            logging.getLogger('app.services.enrichment.test').info('enrichment event')
            logging.getLogger('app.queen_library.test').info('queen event')
            logging.getLogger('app.backend.test').error('backend error')
            logging.getLogger('app.http_access').info('{"path":"/health"}')
            logging.shutdown()

            self.assertIn('backend event', (log_dir / 'backend.log').read_text(encoding='utf-8'))
            self.assertIn('gui event', (log_dir / 'gui.log').read_text(encoding='utf-8'))
            self.assertIn('enrichment event', (log_dir / 'enrichment.log').read_text(encoding='utf-8'))
            self.assertIn('queen event', (log_dir / 'queen_library.log').read_text(encoding='utf-8'))
            self.assertIn('backend error', (log_dir / 'error.log').read_text(encoding='utf-8'))
            self.assertNotIn('gui event', (log_dir / 'backend.log').read_text(encoding='utf-8'))
            self.assertIn('"path":"/health"', (log_dir / 'http_access.log').read_text(encoding='utf-8'))

    def test_cleanup_old_logs_removes_expired_files_and_enforces_size_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            expired_log = log_dir / 'expired.log'
            expired_log.write_text('expired', encoding='utf-8')
            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            expired_log.touch()
            import os

            os.utime(expired_log, (old_time, old_time))

            first_log = log_dir / 'first.log'
            second_log = log_dir / 'second.log'
            first_log.write_text('a' * 32, encoding='utf-8')
            time.sleep(0.02)
            second_log.write_text('b' * 32, encoding='utf-8')

            cleanup_old_logs(log_dir=log_dir, max_age_days=30, max_total_bytes=40)

            self.assertFalse(expired_log.exists())
            self.assertFalse(first_log.exists())
            self.assertTrue(second_log.exists())

    def test_task_trace_and_progress_snapshot_share_run_and_correlation_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace = TaskTraceLogger('single', 'abc-001', '测试任务', log_dir=Path(temp_dir))
            trace.log('INFO', 'processing')
            trace_contents = trace.log_path.read_text(encoding='utf-8')

            progress = EnrichmentProgressService()
            progress.start(
                '测试任务',
                1,
                run_id=trace.run_id,
                correlation_id=trace.correlation_id,
            )

            self.assertTrue(trace.run_id)
            self.assertTrue(trace.correlation_id)
            self.assertIn(f'run_id={trace.run_id}', trace_contents)
            self.assertIn(f'correlation_id={trace.correlation_id}', trace_contents)
            self.assertEqual(progress.snapshot()['run_id'], trace.run_id)
            self.assertEqual(progress.snapshot()['correlation_id'], trace.correlation_id)

    def test_task_trace_reconfigures_handlers_after_a_temporary_log_directory_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configure_logging(log_dir=Path(temp_dir), force=True)
            logging.shutdown()

        TaskTraceLogger('single', 'abc-002', '重配置测试')
        managed_handlers = [
            handler
            for handler in logging.getLogger().handlers
            if getattr(handler, '_local_video_renamer_logging_handler', False)
        ]
        self.assertTrue(managed_handlers)
        self.assertTrue(all(Path(handler.baseFilename).parent == LOG_DIR for handler in managed_handlers))

    def test_backend_access_log_records_request_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            configure_logging(log_dir=log_dir, force=True)
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(_HealthService()))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f'http://127.0.0.1:{server.server_port}/health', timeout=3) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

            logging.shutdown()
            entries = [
                json.loads(line)
                for line in (log_dir / 'http_access.log').read_text(encoding='utf-8').splitlines()
                if line.strip()
            ]
            entry = entries[-1]
            self.assertEqual(entry['method'], 'GET')
            self.assertEqual(entry['path'], '/health')
            self.assertEqual(entry['status'], 200)
            self.assertIn('duration_ms', entry)
            self.assertTrue(entry['request_id'])

    def test_snapshot_and_crawl_logs_keep_the_current_correlation_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            snapshot_service = BackendService.__new__(BackendService)
            snapshot_service._snapshot_refresh_log_file = temp_path / 'snapshot_refresh.log'
            queen_service = QueenLibraryService.__new__(QueenLibraryService)
            queen_service.crawl_log_path = temp_path / 'queen_crawl.log'

            with log_context(run_id='run-123', correlation_id='corr-456'):
                snapshot_service._append_snapshot_refresh_log(
                    snapshot_key='actors',
                    refreshed_at='2026-07-14 17:00:00',
                    refresh_duration_ms=12,
                )
                queen_service._append_crawl_log({'event': 'refresh_completed'})

            snapshot_entry = json.loads(snapshot_service._snapshot_refresh_log_file.read_text(encoding='utf-8'))
            crawl_entry = json.loads(queen_service.crawl_log_path.read_text(encoding='utf-8'))
            self.assertEqual(snapshot_entry['run_id'], 'run-123')
            self.assertEqual(snapshot_entry['correlation_id'], 'corr-456')
            self.assertEqual(crawl_entry['run_id'], 'run-123')
            self.assertEqual(crawl_entry['correlation_id'], 'corr-456')


if __name__ == '__main__':
    unittest.main()
