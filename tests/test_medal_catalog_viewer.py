import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QCheckBox

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.medal_catalog_viewer import GlobalMedalPickerDialog, MedalCatalogWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(
    self,
    task,
    success_handler,
    error_title=None,
    block_ui=True,
    allow_deferred_close=False,
):
    success_handler(task())
    return True


class MedalCatalogBackendStub:
    def __init__(self):
        self.rows = [
            {'name': 'Rookie', 'description': 'For debut-level standouts'},
            {'name': 'Evergreen', 'description': 'For long-running elite entries'},
        ]
        self.add_calls = []
        self.update_calls = []
        self.delete_calls = []

    def list_global_medals(self):
        return [dict(row) for row in self.rows]

    def add_global_medal(self, name, description):
        self.add_calls.append((name, description))
        row = {'name': name, 'description': description}
        self.rows.append(row)
        return dict(row)

    def update_global_medal_description(self, name, description):
        self.update_calls.append((name, description))
        for row in self.rows:
            if row['name'] == name:
                row['description'] = description
                return dict(row)
        raise AssertionError('missing medal')

    def delete_global_medal(self, name):
        self.delete_calls.append(name)
        self.rows = [row for row in self.rows if row['name'] != name]
        return {'deleted': True}


class MedalCatalogViewerTest(unittest.TestCase):
    def test_catalog_window_loads_adds_updates_and_deletes_medals(self):
        backend = MedalCatalogBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MedalCatalogWindow(backend)
            try:
                self.assertEqual(window.table.rowCount(), 2)
                self.assertEqual(window.table.item(0, 0).text(), 'Rookie')

                window.name_input.setText('Legend')
                window.description_input.setText('For all-time great entities')
                window.handle_add_medal()
                self.assertEqual(backend.add_calls, [('Legend', 'For all-time great entities')])

                description_editor = window.table.cellWidget(0, 1)
                description_editor.setText('Updated rookie description')
                save_button = window.table.cellWidget(0, 2).findChild(type(window.btn_add), 'save_button_0')
                save_button.click()
                self.assertEqual(backend.update_calls, [('Rookie', 'Updated rookie description')])

                delete_button = window.table.cellWidget(1, 2).findChild(type(window.btn_add), 'delete_button_1')
                delete_button.click()
                self.assertEqual(backend.delete_calls, ['Evergreen'])
            finally:
                window.hide()
                window.deleteLater()

    def test_global_medal_picker_disables_owned_medals_and_returns_new_choices(self):
        dialog = GlobalMedalPickerDialog(
            medals=[
                {'name': 'Rookie', 'description': 'For debut-level standouts'},
                {'name': 'Evergreen', 'description': 'For long-running elite entries'},
            ],
            owned_medals=['Rookie'],
        )
        try:
            owned_checkbox = dialog.medal_checkboxes['Rookie']
            self.assertFalse(owned_checkbox.isEnabled())

            selectable_checkbox = dialog.medal_checkboxes['Evergreen']
            selectable_checkbox.setChecked(True)

            self.assertEqual(dialog.selected_medal_names(), ['Evergreen'])
        finally:
            dialog.hide()
            dialog.deleteLater()

    def test_global_medal_picker_uses_four_column_name_only_grid(self):
        dialog = GlobalMedalPickerDialog(
            medals=[
                {'name': 'Rookie', 'description': 'For debut-level standouts'},
                {'name': 'Evergreen', 'description': 'For long-running elite entries'},
                {'name': 'Legend', 'description': 'All-time greats'},
                {'name': 'Icon', 'description': 'Signature picks'},
                {'name': 'Classic', 'description': 'Everlasting classics'},
            ],
            owned_medals=[],
        )
        try:
            self.assertEqual(dialog.medal_grid.itemAtPosition(0, 0).widget().text(), 'Rookie')
            self.assertEqual(dialog.medal_grid.itemAtPosition(0, 3).widget().text(), 'Icon')
            self.assertEqual(dialog.medal_grid.itemAtPosition(1, 0).widget().text(), 'Classic')
            self.assertEqual(dialog.medal_grid.columnCount(), 4)

            checkbox_texts = [checkbox.text() for checkbox in dialog.findChildren(QCheckBox)]
            self.assertNotIn('For debut-level standouts', checkbox_texts)
            self.assertNotIn('For long-running elite entries', checkbox_texts)
        finally:
            dialog.hide()
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
