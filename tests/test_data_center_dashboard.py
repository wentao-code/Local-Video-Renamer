from app.core.data_dashboard import build_data_dashboard


def test_dashboard_aggregates_actor_prefix_video_and_quality_metrics():
    dashboard = build_data_dashboard(
        actor_rows=[
            {
                'name': 'Actor A',
                'age': 20,
                'height': 160,
                'video_count': 0,
                'update_status': 'inactive',
                'complete_profile': True,
            },
            {
                'name': 'Actor B',
                'age': 40,
                'height': 170,
                'video_count': 10,
                'update_status': 'active',
                'complete_profile': False,
            },
            {
                'name': 'Actor C',
                'age': None,
                'height': None,
                'video_count': 5,
                'update_status': 'suspect',
                'complete_profile': False,
            },
        ],
        code_prefix_rows=[
            {'prefix': 'AAA', 'video_count': 0, 'update_status': 'inactive'},
            {'prefix': 'BBB', 'video_count': 20, 'update_status': 'active'},
        ],
        visible_video_rows=[
            {'code': 'AAA-001', 'video_category': '单体作品', 'release_date': '2026-07-01', 'author': 'Actor A'},
            {'code': 'BBB-001', 'video_category': '共演作品', 'release_date': '2025-01-01', 'author': ''},
            {'code': 'BBB-002', 'video_category': '', 'release_date': '', 'author': 'Actor B'},
        ],
        filtered_video_rows=[{'code': 'SKIP-001'}],
        source_coverages={'avfan': (2, 4), 'javtxt': (3, 4)},
        today='2026-07-14',
    )

    metrics = {
        metric['key']: metric
        for section in dashboard['sections']
        for metric in section['metrics']
    }
    assert metrics['actor_total']['value'] == '3'
    assert metrics['actor_average_age']['value'] == '30.0 岁'
    assert metrics['actor_median_height']['value'] == '165.0 cm'
    assert metrics['actor_average_video_count']['value'] == '5.0'
    assert metrics['actor_active']['value'] == '1（33.3%）'
    assert metrics['actor_complete_profile']['value'] == '1'
    assert metrics['actor_zero_video']['value'] == '1'
    assert metrics['code_prefix_average_video_count']['value'] == '10.0'
    assert metrics['video_valid_total']['value'] == '3'
    assert metrics['video_filtered_total']['value'] == '1'
    assert metrics['video_uncategorized']['value'] == '1'
    assert metrics['video_missing_actor']['value'] == '1'
    assert metrics['video_recent_90_days']['value'] == '1'
    assert metrics['avfan_coverage']['value'] == '50.0%'
    assert metrics['javtxt_coverage']['value'] == '75.0%'


def test_backend_client_dashboard_api_paths():
    from app.backend.client import BackendClient

    client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
    calls = []
    client._get = lambda path, timeout=None: calls.append((path, timeout)) or {
        'dashboard': {'sections': []},
        'items': [],
    }

    assert client.get_data_dashboard(force_refresh=True) == {'sections': []}
    assert client.get_data_dashboard_items('actor_active') == []
    assert calls == [
        ('/data-center/dashboard?refresh=1', None),
        ('/data-center/dashboard/items?metric=actor_active', None),
    ]


def test_dashboard_window_renders_sections_and_clickable_metric():
    import os
    from unittest.mock import patch

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtWidgets import QApplication

    from app.gui.backend_task_worker import AsyncTaskHostMixin
    from app.gui.data_dashboard_viewer import DataDashboardWindow

    app = QApplication.instance() or QApplication([])

    class Backend:
        def get_data_dashboard(self, force_refresh=False):
            return {
                'sections': [
                    {
                        'key': 'actors',
                        'title': '演员信息',
                        'metrics': [
                            {
                                'key': 'actor_total',
                                'title': '演员总数',
                                'value': '3',
                                'clickable': True,
                            }
                        ],
                    }
                ],
                'refreshed_at': '2026-07-14 10:00:00',
            }

    def run_sync(self, task, success_handler, error_title=None, **kwargs):
        success_handler(task())
        return True

    with patch.object(AsyncTaskHostMixin, 'start_async_task', run_sync):
        window = DataDashboardWindow(Backend())
        try:
            assert len(window.metric_buttons) == 1
            assert '演员总数' in window.metric_buttons[0].text()
            assert '3' in window.metric_buttons[0].text()
            assert window.metric_buttons[0].isEnabled()
        finally:
            window.close()
