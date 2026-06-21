from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.backend.client import BackendClient
from app.core.actor_data_analysis import ACTOR_ANALYSIS_METRICS
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr


def _build_refresh_client(backend_client, minimum_timeout=90):
    base_url = str(getattr(backend_client, 'base_url', '') or '').strip()
    if not base_url:
        return backend_client
    return BackendClient(
        base_url=base_url,
        timeout=max(int(getattr(backend_client, 'timeout', 30) or 30), minimum_timeout),
    )


def _join_items_by_line(items, items_per_line=10):
    grouped_lines = []
    items_per_line = max(1, int(items_per_line or 1))
    for start in range(0, len(items), items_per_line):
        grouped_lines.append('    '.join(items[start:start + items_per_line]))
    return '\n'.join(grouped_lines)


class ActorDataAnalysisWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.metric_windows = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(tr('data_center.analysis.title'))
        self.resize(720, 240)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        top_label = QLabel(tr('data_center.analysis.hint'))
        top_label.setWordWrap(True)
        layout.addWidget(top_label)

        button_group = QGroupBox(tr('data_center.analysis.metric_group'))
        button_layout = QGridLayout(button_group)
        button_layout.setContentsMargins(12, 12, 12, 12)
        button_layout.setHorizontalSpacing(10)
        button_layout.setVerticalSpacing(10)

        for index, config in enumerate(ACTOR_ANALYSIS_METRICS):
            button = QPushButton(tr(config['label_key']))
            button.setMinimumHeight(36)
            button.clicked.connect(lambda _checked=False, item=dict(config): self.open_metric_window(item))
            button_layout.addWidget(button, index // 3, index % 3)

        layout.addWidget(button_group)
        layout.addStretch()

    def open_metric_window(self, metric_config):
        window = ActorMetricAnalysisWindow(self.backend_client, metric_config, self)
        self.metric_windows.append(window)
        window.finished.connect(lambda _result, current=window: self._forget_metric_window(current))
        window.show()

    def _forget_metric_window(self, window):
        self.metric_windows = [item for item in self.metric_windows if item is not window]


class ActorMetricAnalysisWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, metric_config, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.refresh_client = _build_refresh_client(backend_client)
        self.metric_config = dict(metric_config or {})
        self.metric_key = str(self.metric_config.get('key', '') or '').strip()
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(
            tr(
                'data_center.analysis.metric_title',
                metric_label=tr(self.metric_config.get('label_key', '')),
            )
        )
        self.resize(1380, 760)
        self.setWindowModality(Qt.WindowModal)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        top_layout = QHBoxLayout()
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.last_refreshed_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_refresh)
        root_layout.addLayout(top_layout)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        distribution_group = QGroupBox(tr('data_center.analysis.distribution_group'))
        distribution_layout = QVBoxLayout(distribution_group)
        self.distribution_label = QLabel(tr('common.no_data'))
        self.distribution_label.setWordWrap(True)
        self.distribution_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        distribution_layout.addWidget(self.distribution_label)
        content_layout.addWidget(distribution_group)

        ranking_group = QGroupBox(tr('data_center.analysis.ranking_group'))
        ranking_layout = QVBoxLayout(ranking_group)
        self.ranking_label = QLabel(tr('common.no_data'))
        self.ranking_label.setWordWrap(True)
        self.ranking_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ranking_layout.addWidget(self.ranking_label)
        content_layout.addWidget(ranking_group)
        content_layout.addStretch()

        scroll_area.setWidget(content)
        self.set_async_busy_widgets([self.btn_refresh])

    def load_data(self, force_refresh=False):
        if self.is_async_task_running():
            return
        self.start_async_task(
            lambda: self.refresh_client.get_actor_metric_analysis(self.metric_key, force_refresh=force_refresh) or {},
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        analysis = dict(payload.get('analysis', {}) or {})
        distribution_rows = list(analysis.get('distribution_rows', []) or [])
        ranking_rows = list(analysis.get('ranking_rows', []) or [])
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or tr('common.empty')

        distribution_items = [
            tr('detail.distribution_item', name=row.get('label', tr('common.unknown')), count=row.get('count', 0))
            for row in distribution_rows
        ]
        ranking_items = [
            tr(
                'data_center.analysis.ranking_item',
                rank=index + 1,
                actor_name=row.get('actor_name', ''),
                value=row.get('display_value', ''),
            )
            for index, row in enumerate(ranking_rows)
        ]

        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        self.distribution_label.setText(
            _join_items_by_line(distribution_items, items_per_line=10) if distribution_items else tr('common.no_data')
        )
        self.ranking_label.setText(
            _join_items_by_line(ranking_items, items_per_line=10) if ranking_items else tr('common.no_data')
        )
