import argparse
import json
from time import perf_counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.backend.service import BackendService
from app.core.runtime_config import get_backend_host, get_backend_port
from app.core.app_logging import (
    configure_logging,
    get_logger,
    install_global_exception_hooks,
    log_context,
    log_http_access,
    new_correlation_id,
)


def make_handler(service):
    def _is_truthy_query_value(query, key):
        return str((query.get(key, [''])[0] or '')).strip().lower() in ('1', 'true', 'yes', 'on')

    def _is_falsey_query_value(query, key):
        return str((query.get(key, [''])[0] or '')).strip().lower() in ('0', 'false', 'no', 'off')

    def _int_query_value(query, key, default=None):
        raw_value = str((query.get(key, [''])[0] or '')).strip()
        if not raw_value:
            return default
        return int(raw_value)

    class VideoBackendHandler(BaseHTTPRequestHandler):
        server_version = 'LocalVideoRenamerBackend/1.0'

        def log_message(self, format, *args):
            return

        def do_GET(self):
            self._handle_request('GET')

        def do_POST(self):
            self._handle_request('POST')

        def _handle_request(self, method):
            request_id = new_correlation_id('req')
            started_at = perf_counter()
            parsed_url = urlparse(self.path)
            status = HTTPStatus.OK
            with log_context(correlation_id=request_id):
                try:
                    body = self._read_json_body()
                    response = self._route(method, parsed_url, body)
                    self._send_json(response, status)
                except FileNotFoundError as exc:
                    status = HTTPStatus.NOT_FOUND
                    get_logger(__name__).warning('后端请求资源不存在: %s', exc)
                    self._send_json({'error': str(exc), 'request_id': request_id}, status)
                except ValueError as exc:
                    status = HTTPStatus.BAD_REQUEST
                    get_logger(__name__).warning('后端请求参数无效: %s', exc)
                    self._send_json({'error': str(exc), 'request_id': request_id}, status)
                except Exception as exc:
                    status = HTTPStatus.INTERNAL_SERVER_ERROR
                    get_logger(__name__).exception('后端请求异常')
                    self._send_json({'error': str(exc), 'request_id': request_id}, status)
                finally:
                    log_http_access(
                        method,
                        parsed_url.path or '/',
                        int(status),
                        (perf_counter() - started_at) * 1000,
                        request_id,
                        client_address=self.client_address[0] if self.client_address else '',
                    )

        def _route(self, method, parsed_url, body):
            path = parsed_url.path.rstrip('/') or '/'
            query = parse_qs(parsed_url.query)

            if method == 'GET' and path == '/health':
                return service.health()
            if method == 'POST' and path == '/database/reload':
                return service.load_database()
            if method == 'POST' and path == '/scan':
                folder_path = body.get('folder_path')
                if not folder_path:
                    raise ValueError('缺少 folder_path')
                return service.scan(folder_path)
            if method == 'POST' and path == '/rename':
                return service.rename(body.get('plans', []))
            if method == 'POST' and path == '/database/videos/import':
                return service.import_videos(body.get('plans', []))
            if method == 'GET' and path == '/database/videos':
                search_text = query.get('q', [''])[0]
                return service.list_videos(
                    search_text,
                    sort_field=query.get('sort_field', [''])[0],
                    sort_order=query.get('sort_order', [''])[0],
                    limit=_int_query_value(query, 'limit', default=None),
                    offset=_int_query_value(query, 'offset', default=0),
                )
            if method == 'GET' and path == '/search/unified':
                return service.search_unified(
                    query.get('q', [''])[0],
                    limit=_int_query_value(query, 'limit', default=20),
                )
            if method == 'GET' and path == '/database/videos/summary':
                return service.get_video_enrichment_summary()
            if method == 'GET' and path == '/masterpiece/entries':
                return service.list_masterpiece_entries()
            if method == 'POST' and path == '/masterpiece/actors/refresh':
                return service.refresh_masterpiece_actors()
            if method == 'POST' and path == '/masterpiece/entries/add':
                return service.add_masterpiece_entry(body.get('code'))
            if method == 'POST' and path == '/masterpiece/entries/medal':
                return service.update_masterpiece_entry_medal(body.get('code'), body.get('medal'))
            if method == 'GET' and path == '/masterpiece/detail':
                return service.get_masterpiece_detail_snapshot(
                    query.get('code', [''])[0],
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'POST' and path == '/masterpiece/detail/enrich':
                return service.enrich_masterpiece_detail(body.get('code'))
            if method == 'GET' and path == '/medals':
                return service.list_global_medals()
            if method == 'POST' and path == '/medals/add':
                return service.add_global_medal(
                    body.get('name'),
                    body.get('description', ''),
                    body.get('medal_type', 'special'),
                )
            if method == 'POST' and path == '/medals/update':
                return service.update_global_medal(
                    body.get('name'),
                    body.get('description', ''),
                    body.get('medal_type'),
                )
            if method == 'POST' and path == '/medals/delete':
                return service.delete_global_medal(body.get('name'))
            if method == 'GET' and path == '/database/videos/detail':
                return service.get_video_detail(query.get('code', [''])[0])
            if method == 'GET' and path == '/data-center/summary':
                return service.get_data_center_summary(force_refresh=_is_truthy_query_value(query, 'refresh'))
            if method == 'GET' and path == '/data-center/dashboard':
                return service.get_data_dashboard(force_refresh=_is_truthy_query_value(query, 'refresh'))
            if method == 'GET' and path == '/data-center/dashboard/items':
                return service.get_data_dashboard_items(query.get('metric', [''])[0])
            if method == 'GET' and path == '/settings/timeouts':
                return service.list_operation_timeouts()
            if method == 'POST' and path == '/settings/timeouts':
                return service.update_operation_timeouts(body.get('values', {}))
            if method == 'POST' and path == '/settings/timeouts/reset':
                return service.reset_operation_timeouts(body.get('setting_keys'))
            if method == 'POST' and path == '/snapshots/details/rebuild':
                return service.rebuild_detail_snapshots()
            if method == 'GET' and path == '/snapshots/details/rebuild/status':
                return service.get_detail_snapshot_rebuild_status()
            if method == 'GET' and path == '/data-center/analysis':
                return service.get_metric_analysis(
                    query.get('analysis_type', ['actor'])[0],
                    query.get('metric', [''])[0],
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'GET' and path == '/data-center/analysis/actors':
                return service.get_actor_metric_bucket(
                    query.get('metric', [''])[0],
                    query.get('value', [''])[0],
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'GET' and path == '/data-center/analysis/code-prefixes':
                return service.get_code_prefix_metric_bucket(
                    query.get('metric', [''])[0],
                    query.get('value', [''])[0],
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'POST' and path == '/database/videos/reset':
                return service.reset_video_enrichments(body.get('codes', []), body.get('source_key'))
            if method == 'GET' and path == '/database/videos/manual-category':
                return service.list_videos_requiring_manual_category_snapshot(
                    force_refresh=_is_truthy_query_value(query, 'refresh')
                )
            if method == 'POST' and path == '/database/videos/manual-category/stage':
                return service.stage_video_category(body.get('code'), body.get('category'))
            if method == 'POST' and path == '/database/videos/manual-category/stage/batch':
                return service.stage_video_categories(body.get('entries', []))
            if method == 'POST' and path == '/database/videos/manual-category/sync':
                return service.sync_staged_video_categories()
            if method == 'POST' and path == '/database/videos/category':
                return service.update_video_category(body.get('code'), body.get('category'))
            if method == 'GET' and path == '/database/actors':
                search_text = query.get('q', [''])[0]
                return service.list_actors_snapshot(
                    search_text,
                    sort_field=query.get('sort_field', [''])[0],
                    sort_order=query.get('sort_order', [''])[0],
                    limit=_int_query_value(query, 'limit', default=None),
                    offset=_int_query_value(query, 'offset', default=0),
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                    include_update_status=not _is_falsey_query_value(query, 'update_status'),
                )
            if method == 'GET' and path == '/database/actors/detail':
                actor_name = query.get('name', [''])[0]
                return service.get_actor_detail_snapshot(
                    actor_name,
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'POST' and path == '/database/actors/add':
                return service.add_actor(
                    body.get('actor_name'),
                    body.get('birthday', ''),
                    body.get('age', ''),
                )
            if method == 'POST' and path == '/candidate-library/refresh':
                return service.refresh_candidate_library()
            if method == 'GET' and path == '/candidate-library/actors':
                return service.list_candidate_actors()
            if method == 'POST' and path == '/candidate-library/actors/admit':
                return service.admit_candidate_actor(body.get('actor_name'))
            if method == 'GET' and path == '/canglangge/candidates':
                return service.list_canglangge_candidates(force_refresh=_is_truthy_query_value(query, 'refresh'))
            if method == 'POST' and path == '/canglangge/admit':
                return service.admit_canglangge_candidates(body.get('actor_names', []))
            if method == 'POST' and path == '/canglangge/delete':
                return service.delete_canglangge_candidates(body.get('actor_names', []))
            if method == 'POST' and path == '/database/actors/reset':
                return service.reset_actor_enrichments(body.get('actor_names', []), body.get('source_key'))
            if method == 'POST' and path == '/database/actors/rename':
                return service.rename_actor(
                    body.get('old_name'),
                    body.get('new_name'),
                    body.get('birthday', ''),
                    body.get('age', ''),
                )
            if method == 'POST' and path == '/database/actors/delete':
                return service.delete_actor(body.get('actor_name'))
            if method == 'GET' and path == '/database/code-prefixes':
                search_text = query.get('q', [''])[0]
                return service.list_code_prefixes_snapshot(
                    search_text,
                    sort_field=query.get('sort_field', [''])[0],
                    sort_order=query.get('sort_order', [''])[0],
                    limit=_int_query_value(query, 'limit', default=None),
                    offset=_int_query_value(query, 'offset', default=0),
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'GET' and path == '/database/code-prefixes/detail':
                prefix = query.get('prefix', [''])[0]
                return service.get_code_prefix_detail_snapshot(
                    prefix,
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'POST' and path == '/database/code-prefixes/add':
                return service.add_code_prefix(body.get('prefix'))
            if method == 'GET' and path == '/candidate-library/code-prefixes':
                return service.list_candidate_code_prefixes()
            if method == 'POST' and path == '/candidate-library/code-prefixes/admit':
                return service.admit_candidate_code_prefix(body.get('prefix'))
            if method == 'POST' and path == '/database/code-prefixes/detail/category':
                return service.update_code_prefix_uncategorized_video_category(body.get('prefix'), body.get('category'))
            if method == 'POST' and path == '/database/code-prefixes/reset':
                return service.reset_code_prefix_enrichments(body.get('prefixes', []), body.get('source_key'))
            if method == 'POST' and path == '/database/code-prefixes/rename':
                return service.rename_code_prefix(body.get('old_prefix'), body.get('new_prefix'))
            if method == 'POST' and path == '/database/code-prefixes/delete':
                return service.delete_code_prefix(body.get('prefix'))
            if method == 'POST' and path == '/database/code-prefixes/filter-blacklist':
                return service.sync_code_prefix_filter_blacklist(body.get('prefixes', []))
            if method == 'GET' and path == '/ladder/board':
                return service.get_ladder_board(
                    query.get('board_key', [''])[0],
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'POST' and path == '/ladder/entries/select':
                return service.admit_ladder_entry(body.get('board_key'), body.get('entity_name'), body.get('tier'))
            if method == 'POST' and path == '/ladder/entries/medal':
                return service.update_ladder_entry_medal(body.get('board_key'), body.get('entity_name'), body.get('medal'))
            if method == 'GET' and path == '/paths':
                return service.list_paths(force_refresh=_is_truthy_query_value(query, 'refresh'))
            if method == 'POST' and path == '/paths/add':
                folder_path = body.get('folder_path')
                if not folder_path:
                    raise ValueError('缺少 folder_path')
                return service.add_path(folder_path)
            if method == 'POST' and path == '/paths/delete':
                return service.delete_path(body.get('path_id'))
            if method == 'GET' and path == '/queen-library/queens':
                return service.list_queen_library_snapshot(force_refresh=_is_truthy_query_value(query, 'refresh'))
            if method == 'GET' and path == '/queen-library/keywords':
                return service.list_queen_keywords_snapshot(force_refresh=_is_truthy_query_value(query, 'refresh'))
            if method == 'GET' and path == '/queen-library/stats':
                return service.get_queen_library_stats()
            if method == 'POST' and path == '/queen-library/search':
                return service.search_queen_keyword(
                    body.get('keyword'),
                    show_browser=bool(body.get('show_browser', True)),
                )
            if method == 'POST' and path == '/queen-library/refresh':
                return service.refresh_queen_library(show_browser=bool(body.get('show_browser', True)))
            if method == 'POST' and path == '/queen-library/refresh/cancel':
                return service.cancel_queen_library_refresh()
            if method == 'GET' and path == '/queen-library/refresh/progress':
                return service.get_queen_library_refresh_progress()
            if method == 'GET' and path == '/queen-library/detail':
                return service.get_queen_detail_snapshot(
                    query.get('name', [''])[0],
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'POST' and path == '/queen-library/profile':
                return service.update_queen_profile(body.get('queen_name'), body.get('profile', {}))
            if method == 'POST' and path == '/queen-library/queens/rename':
                return service.rename_queen(
                    body.get('queen_name'),
                    body.get('new_queen_name'),
                    body.get('profile', {}),
                )
            if method == 'POST' and path == '/queen-library/videos/metadata':
                return service.update_queen_video_metadata(
                    body.get('record_id'),
                    body.get('content_type', ''),
                    body.get('content_level', ''),
                )
            if method == 'POST' and path == '/queen-library/videos/delete':
                return service.delete_queen_video(body.get('record_id'))
            if method == 'POST' and path == '/queen-library/queens/delete':
                return service.delete_queen(body.get('queen_name'))
            if method == 'POST' and path == '/queen-library/keywords/delete':
                return service.delete_queen_keyword(body.get('keyword'))
            if method == 'POST' and path == '/database/enrich':
                return service.enrich_videos(
                    body.get('limit', 1),
                    show_browser=bool(body.get('show_browser')),
                    cooldown_before_search=bool(body.get('cooldown_before_search')),
                    target_type=body.get('target_type'),
                    source_key=body.get('source_key'),
                    batch_mode=bool(body.get('batch_mode')),
                    plan_id=body.get('plan_id', ''),
                    plan_task_kind=body.get('plan_task_kind', ''),
                )
            if method == 'POST' and path == '/database/enrich/batch-plan':
                return service.create_enrichment_batch_plan(body)
            if method == 'POST' and path == '/database/enrich/combo':
                return service.enrich_combo(
                    body.get('combo_key'),
                    body.get('limit', 1),
                    show_browser=bool(body.get('show_browser')),
                    cooldown_before_search=bool(body.get('cooldown_before_search')),
                    combo_task_settings=body.get('combo_task_settings', {}),
                    batch_mode=bool(body.get('batch_mode')),
                )
            if method == 'GET' and path == '/database/enrich/progress':
                return service.get_enrichment_progress()
            if method == 'GET' and path == '/database/enrich/plans':
                return service.list_enrichment_plans(
                    resumable_only=_is_truthy_query_value(query, 'resumable'),
                )
            if method == 'GET' and path == '/database/enrich/plan-progress':
                return service.get_enrichment_plan_progress(
                    query.get('plan_id', [''])[0],
                    query.get('task_kind', [''])[0],
                )
            if method == 'POST' and path == '/database/enrich/recover':
                return service.recover_enrichment_plans(body.get('reason', '程序启动恢复'))
            if method == 'POST' and path == '/database/enrich/plan/pause':
                return service.pause_enrichment_plan(
                    body.get('plan_id', ''),
                    body.get('task_kind', ''),
                    body.get('reason', '补全任务异常暂停'),
                )
            if method == 'POST' and path == '/database/enrich/cancel':
                return service.cancel_enrichment()
            if method == 'POST' and path == '/login/auto':
                return service.auto_login()
            if method == 'POST' and path == '/browser-profile/reset':
                return service.reset_browser_profile()
            if method == 'POST' and path == '/database/library-status/sync':
                return service.sync_library_statuses()

            raise ValueError(f'未知接口: {method} {path}')

        def _read_json_body(self):
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                return {}

            raw_body = self.rfile.read(content_length).decode('utf-8')
            if not raw_body.strip():
                return {}

            return json.loads(raw_body)

        def _send_json(self, data, status=HTTPStatus.OK):
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except OSError:
                get_logger(__name__).info('客户端已断开，忽略后端响应回写')
            except ValueError:
                if not bool(getattr(self.wfile, 'closed', False)):
                    raise
                get_logger(__name__).info('客户端响应流已关闭，忽略后端响应回写')

    return VideoBackendHandler


def run_server(host=None, port=None, instance_token=''):
    from app.core.project_paths import ensure_storage_layout

    ensure_storage_layout()
    configure_logging()
    install_global_exception_hooks('backend')
    host = str(host or get_backend_host()).strip() or get_backend_host()
    port = int(port or get_backend_port())
    service = BackendService(instance_token=instance_token)
    server = ThreadingHTTPServer((host, port), make_handler(service))
    try:
        try:
            service.start_background_video_category_snapshot_filter()
        except Exception:
            get_logger(__name__).exception('视频分类快照后台过滤调度失败，后端继续运行')
        print(f'Local Video Renamer backend listening on http://{host}:{port}')
        server.serve_forever()
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=get_backend_host())
    parser.add_argument('--port', type=int, default=get_backend_port())
    parser.add_argument('--instance-token', default='')
    args = parser.parse_args()
    run_server(args.host, args.port, instance_token=args.instance_token)


if __name__ == '__main__':
    main()
