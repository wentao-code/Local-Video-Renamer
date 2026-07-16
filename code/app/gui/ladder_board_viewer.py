from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_BOARD_CODE_PREFIX,
    LADDER_ENTITY_ACTOR,
    LADDER_VIEW_CANDIDATES,
    LADDER_VISIBLE_TIERS,
)
from app.gui.actor_detail_viewer import ActorDetailViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow
from app.gui.i18n import tr
from app.gui.ladder_candidate_panel import LadderCandidatePanel
from app.gui.ladder_selected_panel import LadderSelectedPanel
from app.gui.query_context import EntityReference, EntityType, QueryContext


class LadderBoardWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None, coordinator=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.coordinator = coordinator
        self.current_board_key = LADDER_BOARD_ACTOR
        self.current_view_key = LADDER_VIEW_CANDIDATES
        self.current_board_data = {}
        self.global_medals = []
        self._init_async_task_host()
        self.init_ui()
        self.load_board()

    def init_ui(self):
        self.setWindowTitle(tr('ladder.title'))
        self.resize(1180, 720)
        self.setWindowModality(Qt.NonModal)

        layout = QVBoxLayout(self)

        board_toggle_layout = QHBoxLayout()
        self.btn_actor_board = QPushButton(tr('ladder.board_actor'))
        self.btn_actor_board.setCheckable(True)
        self.btn_actor_board.clicked.connect(lambda: self.switch_board(LADDER_BOARD_ACTOR))
        self.btn_code_prefix_board = QPushButton(tr('ladder.board_code_prefix'))
        self.btn_code_prefix_board.setCheckable(True)
        self.btn_code_prefix_board.clicked.connect(lambda: self.switch_board(LADDER_BOARD_CODE_PREFIX))
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_board(force_refresh=True))
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        board_toggle_layout.addWidget(self.btn_actor_board)
        board_toggle_layout.addWidget(self.btn_code_prefix_board)
        board_toggle_layout.addStretch()
        board_toggle_layout.addWidget(self.last_refreshed_label)
        board_toggle_layout.addWidget(self.btn_refresh)

        view_toggle_layout = QHBoxLayout()
        self.btn_candidates = QPushButton(tr('ladder.view_candidates'))
        self.btn_candidates.setCheckable(True)
        self.btn_candidates.clicked.connect(lambda: self.switch_view(LADDER_VIEW_CANDIDATES))
        self.tier_buttons = {}
        for tier in LADDER_VISIBLE_TIERS:
            button = QPushButton(tr('ladder.view_tier', tier=tier))
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=tier: self.switch_view(value))
            self.tier_buttons[tier] = button
        self.summary_label = QLabel('')
        view_toggle_layout.addWidget(self.btn_candidates)
        for tier in LADDER_VISIBLE_TIERS:
            view_toggle_layout.addWidget(self.tier_buttons[tier])
        view_toggle_layout.addStretch()
        view_toggle_layout.addWidget(self.summary_label)

        self.stacked_widget = QStackedWidget()
        self.candidate_panel = LadderCandidatePanel(self)
        self.selected_panel = LadderSelectedPanel(self)
        self.candidate_panel.admit_requested.connect(self.admit_entry)
        self.candidate_panel.detail_requested.connect(self.show_detail)
        self.selected_panel.medal_save_requested.connect(self.save_medal)
        self.selected_panel.detail_requested.connect(self.show_detail)
        self.stacked_widget.addWidget(self.candidate_panel)
        self.stacked_widget.addWidget(self.selected_panel)

        layout.addLayout(board_toggle_layout)
        layout.addLayout(view_toggle_layout)
        layout.addWidget(self.stacked_widget)

        self.set_async_busy_widgets(
            [
                self.btn_actor_board,
                self.btn_code_prefix_board,
                self.btn_candidates,
                *self.tier_buttons.values(),
                self.btn_refresh,
            ]
        )
        self._refresh_toggle_states()

    def switch_board(self, board_key):
        if self.is_async_task_running() or board_key == self.current_board_key:
            self._refresh_toggle_states()
            return
        self.current_board_key = board_key
        self._refresh_toggle_states()
        self.load_board()

    def switch_view(self, view_key):
        if view_key != LADDER_VIEW_CANDIDATES and view_key not in LADDER_VISIBLE_TIERS:
            self._refresh_toggle_states()
            return
        self.current_view_key = view_key
        self._refresh_toggle_states()
        self._apply_view()

    def load_board(self, force_refresh=False):
        board_key = self.current_board_key
        self.start_async_task(
            lambda: self._build_board_payload(board_key, force_refresh=force_refresh),
            self._on_board_loaded,
            tr('common.read_failed'),
        )

    def admit_entry(self, entity_name, tier):
        board_key = self.current_board_key
        self.start_async_task(
            lambda: self._reload_board_after(lambda: self.backend_client.admit_ladder_entry(board_key, entity_name, tier)),
            lambda payload: self._on_admit_completed(payload, tier),
            tr('common.save_failed'),
        )

    def _on_admit_completed(self, payload, tier):
        normalized_tier = str(tier or '').strip().upper()
        self.current_view_key = (
            normalized_tier if normalized_tier in LADDER_VISIBLE_TIERS else LADDER_VIEW_CANDIDATES
        )
        self._on_board_loaded(payload)

    def save_medal(self, entity_name, medal):
        board_key = self.current_board_key
        self.start_async_task(
            lambda: self._reload_board_after(
                lambda: self.backend_client.update_ladder_entry_medal(board_key, entity_name, medal)
            ),
            self._on_board_loaded,
            tr('common.save_failed'),
        )

    def _reload_board_after(self, operation):
        board_payload = operation()
        normalized_payload = dict(board_payload or {})
        if 'board' not in normalized_payload:
            normalized_payload = {
                'board': normalized_payload,
                'refreshed_at': '',
            }
        return {
            'board_payload': normalized_payload,
            'global_medals': list(self.global_medals),
        }

    def _build_board_payload(self, board_key, force_refresh=False, include_medals=None):
        if include_medals is None:
            include_medals = force_refresh or not self.global_medals
        payload = {
            'board_payload': self.backend_client.get_ladder_board_snapshot(board_key, force_refresh=force_refresh),
        }
        if include_medals:
            try:
                payload['global_medals'] = self.backend_client.list_global_medals(
                    force_refresh=False
                )
            except TypeError as exc:
                if 'force_refresh' not in str(exc):
                    raise
                payload['global_medals'] = self.backend_client.list_global_medals()
        else:
            payload['global_medals'] = list(self.global_medals)
        return payload

    def show_detail(self, entity_name):
        if not entity_name:
            return
        entity_type = str((self.current_board_data or {}).get('entity_type', '') or '').strip()
        if self.coordinator is not None:
            target_type = EntityType.ACTOR if entity_type == LADDER_ENTITY_ACTOR else EntityType.CODE_PREFIX
            reference = EntityReference(target_type, entity_name, display_name=entity_name)
            self.coordinator.open_entity(
                reference,
                QueryContext(source='ladder', entity=reference),
            )
            return
        if entity_type == LADDER_ENTITY_ACTOR:
            viewer = ActorDetailViewerWindow(self.backend_client, entity_name, self)
        else:
            viewer = CodePrefixDetailViewerWindow(self.backend_client, entity_name, self)
        viewer.exec_()

    def _on_board_loaded(self, payload):
        payload = dict(payload or {})
        board_payload = dict(payload.get('board_payload', payload) or {})
        refreshed_at = str(board_payload.get('refreshed_at', '') or '').strip() or tr('common.empty')
        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        board = dict(board_payload.get('board', board_payload) or {})
        self.current_board_data = board
        self.global_medals = [dict(row or {}) for row in (payload.get('global_medals', []) or [])]
        self.candidate_panel.set_rows(board.get('candidates', []) or [])
        self.selected_panel.set_global_medals(self.global_medals)
        self._update_summary()
        self._apply_view()
        self._refresh_toggle_states()

    def _apply_view(self):
        if self.current_view_key == LADDER_VIEW_CANDIDATES:
            self.selected_panel.set_rows(self._selected_rows_for_tier(LADDER_VISIBLE_TIERS[0]))
            self.stacked_widget.setCurrentIndex(0)
            return
        self.selected_panel.set_rows(self._selected_rows_for_tier(self.current_view_key))
        self.stacked_widget.setCurrentIndex(1)

    def _selected_rows_for_tier(self, tier):
        normalized_tier = str(tier or '').strip().upper()
        if normalized_tier not in LADDER_VISIBLE_TIERS:
            return []
        return [
            row
            for row in self._visible_selected_rows()
            if str((row or {}).get('tier', '') or '').strip().upper() == normalized_tier
        ]

    def _visible_selected_rows(self):
        return [
            dict(row or {})
            for row in ((self.current_board_data or {}).get('selected', []) or [])
            if str((row or {}).get('tier', '') or '').strip().upper() in LADDER_VISIBLE_TIERS
        ]

    def _update_summary(self):
        board_key = str((self.current_board_data or {}).get('board_key', self.current_board_key) or self.current_board_key)
        board_label = tr('ladder.board_actor') if board_key == LADDER_BOARD_ACTOR else tr('ladder.board_code_prefix')
        candidate_count = len((self.current_board_data or {}).get('candidates', []) or [])
        selected_count = len(self._visible_selected_rows())
        self.summary_label.setText(
            tr(
                'ladder.summary',
                board_label=board_label,
                candidate_count=candidate_count,
                selected_count=selected_count,
            )
        )

    def _refresh_toggle_states(self):
        self.btn_actor_board.setChecked(self.current_board_key == LADDER_BOARD_ACTOR)
        self.btn_code_prefix_board.setChecked(self.current_board_key == LADDER_BOARD_CODE_PREFIX)
        self.btn_candidates.setChecked(self.current_view_key == LADDER_VIEW_CANDIDATES)
        for tier, button in self.tier_buttons.items():
            button.setChecked(self.current_view_key == tier)

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        super().closeEvent(event)
