import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BAOMU_ACTOR_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    SUPPLEMENT_TASK_SOURCE,
)
from app.core.enrichment_targets import (
    ACTOR_BIRTHDAY_TARGET,
    ACTOR_LIBRARY_TARGET,
    CODE_PREFIX_LIBRARY_TARGET,
    VIDEO_LIBRARY_TARGET,
)
from app.gui.enrichment_dialog import DEFAULT_SETTINGS_PAYLOAD, EnrichmentDialog


_APP = QApplication.instance() or QApplication([])


def build_default_payload():
    return {
        'target_type': DEFAULT_SETTINGS_PAYLOAD['target_type'],
        'selected_source_by_target': dict(DEFAULT_SETTINGS_PAYLOAD['selected_source_by_target']),
        'selected_combo_key': DEFAULT_SETTINGS_PAYLOAD['selected_combo_key'],
        'target_settings': {
            target_type: {
                source_key: dict(source_settings)
                for source_key, source_settings in source_settings_by_target.items()
            }
            for target_type, source_settings_by_target in DEFAULT_SETTINGS_PAYLOAD['target_settings'].items()
        },
    }


class EnrichmentDialogActorBirthdayTest(unittest.TestCase):
    def _create_dialog(self, payload=None):
        with patch('app.gui.enrichment_dialog.load_saved_settings', return_value=payload or build_default_payload()):
            dialog = EnrichmentDialog()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_actor_birthday_target_allows_actor_profile_sources_and_hides_combo_controls(self):
        dialog = self._create_dialog()

        dialog.actor_birthday_target_button.setChecked(True)

        self.assertEqual(dialog.selected_target_type(), ACTOR_BIRTHDAY_TARGET)
        self.assertEqual(dialog.selected_source_key(), BINGHUO_ACTOR_SOURCE)
        self.assertTrue(dialog.binghuo_source_button.isChecked())
        self.assertFalse(dialog.avfan_source_button.isEnabled())
        self.assertFalse(dialog.javtxt_source_button.isEnabled())
        self.assertTrue(dialog.binghuo_source_button.isEnabled())
        self.assertTrue(dialog.baomu_source_button.isEnabled())
        self.assertTrue(dialog.combo_group.isHidden())
        self.assertTrue(dialog.combo_single_button.isHidden())
        self.assertTrue(dialog.combo_batch_button.isHidden())
        self.assertTrue(dialog.cooldown_checkbox.isHidden())

        values = dialog.values()
        self.assertEqual(values['source_key'], BINGHUO_ACTOR_SOURCE)
        self.assertEqual(values['target_type'], ACTOR_BIRTHDAY_TARGET)
        self.assertEqual(values['combo_task_settings'], {})

    def test_actor_birthday_target_can_switch_between_binghuo_and_baomu(self):
        dialog = self._create_dialog()

        dialog.actor_birthday_target_button.setChecked(True)
        dialog.baomu_source_button.setChecked(True)

        self.assertEqual(dialog.selected_target_type(), ACTOR_BIRTHDAY_TARGET)
        self.assertEqual(dialog.selected_source_key(), BAOMU_ACTOR_SOURCE)
        values = dialog.values()
        self.assertEqual(values['source_key'], BAOMU_ACTOR_SOURCE)
        self.assertEqual(values['target_type'], ACTOR_BIRTHDAY_TARGET)

    def test_switching_back_restores_regular_source_controls(self):
        dialog = self._create_dialog()
        dialog.javtxt_source_button.setChecked(True)
        self.assertEqual(dialog.selected_source_key(), JAVTXT_VIDEO_SOURCE)

        dialog.actor_birthday_target_button.setChecked(True)
        dialog.video_target_button.setChecked(True)

        self.assertEqual(dialog.selected_target_type(), VIDEO_LIBRARY_TARGET)
        self.assertEqual(dialog.selected_source_key(), JAVTXT_VIDEO_SOURCE)
        self.assertTrue(dialog.avfan_source_button.isEnabled())
        self.assertTrue(dialog.javtxt_source_button.isEnabled())
        self.assertFalse(dialog.combo_group.isHidden())
        self.assertFalse(dialog.combo_single_button.isHidden())
        self.assertFalse(dialog.combo_batch_button.isHidden())

    def test_supplement_source_is_available_for_video_code_prefix_and_actor_targets(self):
        dialog = self._create_dialog()

        dialog.supplement_source_button.setChecked(True)
        self.assertEqual(dialog.selected_target_type(), VIDEO_LIBRARY_TARGET)
        self.assertEqual(dialog.selected_source_key(), SUPPLEMENT_TASK_SOURCE)
        self.assertTrue(dialog.combo_group.isHidden())
        self.assertTrue(dialog.combo_single_button.isHidden())
        self.assertTrue(dialog.combo_batch_button.isHidden())
        self.assertEqual(dialog.values()['combo_task_settings'], {})

        dialog.code_prefix_target_button.setChecked(True)
        self.assertTrue(dialog.supplement_source_button.isEnabled())
        dialog.supplement_source_button.setChecked(True)
        self.assertEqual(dialog.selected_target_type(), CODE_PREFIX_LIBRARY_TARGET)
        self.assertEqual(dialog.selected_source_key(), SUPPLEMENT_TASK_SOURCE)

        dialog.actor_target_button.setChecked(True)
        self.assertTrue(dialog.supplement_source_button.isEnabled())
        dialog.supplement_source_button.setChecked(True)
        self.assertEqual(dialog.selected_target_type(), ACTOR_LIBRARY_TARGET)
        self.assertEqual(dialog.selected_source_key(), SUPPLEMENT_TASK_SOURCE)

        dialog.actor_birthday_target_button.setChecked(True)
        self.assertFalse(dialog.supplement_source_button.isEnabled())

    def test_invalid_saved_source_for_actor_birthday_falls_back_to_first_actor_profile_source(self):
        payload = build_default_payload()
        payload['target_type'] = ACTOR_BIRTHDAY_TARGET
        payload['selected_source_by_target'][ACTOR_BIRTHDAY_TARGET] = AVFAN_VIDEO_SOURCE
        payload['selected_source_by_target'][ACTOR_LIBRARY_TARGET] = JAVTXT_VIDEO_SOURCE

        dialog = self._create_dialog(payload)

        self.assertEqual(dialog.selected_target_type(), ACTOR_BIRTHDAY_TARGET)
        self.assertEqual(dialog.selected_source_key(), BINGHUO_ACTOR_SOURCE)

    def test_saved_baomu_source_for_actor_birthday_is_restored(self):
        payload = build_default_payload()
        payload['target_type'] = ACTOR_BIRTHDAY_TARGET
        payload['selected_source_by_target'][ACTOR_BIRTHDAY_TARGET] = BAOMU_ACTOR_SOURCE

        dialog = self._create_dialog(payload)

        self.assertEqual(dialog.selected_target_type(), ACTOR_BIRTHDAY_TARGET)
        self.assertEqual(dialog.selected_source_key(), BAOMU_ACTOR_SOURCE)
        self.assertTrue(dialog.baomu_source_button.isChecked())


if __name__ == '__main__':
    unittest.main()
