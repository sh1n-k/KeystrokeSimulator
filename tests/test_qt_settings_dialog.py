import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.qt_support import qt_app

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from app.domain.models import UserSettings
from app.presenters.settings_form import SettingsForm
from app.storage.settings_storage import save_user_settings
from app.ui.settings_dialog import SettingsDialog, open_settings
from app.utils.i18n import set_language, txt


class FakeHost(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.settings_dialog: QWidget | None = None
        self.sound_player = MagicMock()
        self.calls: list[str] = []
        self.alive = True

    def load_settings(self) -> None:
        self.calls.append("load_settings")

    def setup_event_handlers(self) -> None:
        self.calls.append("setup_event_handlers")

    def unbind_events(self) -> None:
        self.calls.append("unbind_events")

    def is_alive(self) -> bool:
        return self.alive


class QtSettingsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        qt_app()
        set_language("en")
        self.addCleanup(set_language, "en")
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.chdir, self._cwd)
        self.host = FakeHost()
        self.addCleanup(self.host.deleteLater)

    def make(self, *, is_windows: bool = False) -> SettingsDialog:
        form = SettingsForm.load(Path("user_settings.json"), is_windows=is_windows)
        dialog = SettingsDialog(self.host, self.host, form=form)
        self.host.settings_dialog = dialog
        self.addCleanup(dialog.deleteLater)
        return dialog

    def saved(self) -> dict[str, object]:
        return json.loads(Path("user_settings.json").read_text(encoding="utf-8"))


class TestOpenSettings(QtSettingsTestCase):
    def test_open_unbinds_then_reuses_open_dialog(self) -> None:
        open_settings(self.host)
        first = self.host.settings_dialog
        assert first is not None
        self.addCleanup(first.deleteLater)

        open_settings(self.host)

        self.assertIs(self.host.settings_dialog, first)
        self.assertEqual(self.host.calls, ["unbind_events"])
        self.assertTrue(first.isVisible())
        self.assertFalse(
            bool(first.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        )
        first.close()

    def test_cancel_reloads_then_restarts_listeners_without_saving(self) -> None:
        dialog = self.make()
        dialog.show()
        dialog.timing_edits["key_pressed_time_min"].setText("60")

        dialog.cancel_button.click()

        self.assertFalse(Path("user_settings.json").exists())
        self.assertEqual(self.host.calls, ["load_settings", "setup_event_handlers"])
        self.assertIsNone(self.host.settings_dialog)
        self.assertFalse(dialog.isVisible())

    def test_escape_closes_like_cancel(self) -> None:
        dialog = self.make()
        dialog.show()

        QTest.keyClick(dialog, Qt.Key.Key_Escape)

        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.host.calls, ["load_settings", "setup_event_handlers"])

    def test_ok_saves_before_reload_and_restart(self) -> None:
        dialog = self.make()
        dialog.show()
        order: list[str] = []
        real_submit = SettingsForm.submit

        def submit(form: SettingsForm) -> object:
            result = real_submit(form)
            order.append("saved")
            return result

        self.host.load_settings = lambda: order.append("load_settings")  # type: ignore[method-assign]
        self.host.setup_event_handlers = lambda: order.append("setup")  # type: ignore[method-assign]
        with patch.object(SettingsForm, "submit", submit):
            dialog.timing_edits["delay_between_loop_max"].clear()
            QTest.keyClicks(dialog.timing_edits["delay_between_loop_max"], "400")
            dialog.ok_button.click()

        self.assertEqual(order, ["saved", "load_settings", "setup"])
        self.assertEqual(self.saved()["delay_between_loop_max"], 400)
        self.assertSetEqual(set(self.saved()), set(UserSettings().__dict__))

    def test_close_during_shutdown_skips_listener_restart(self) -> None:
        dialog = self.make()
        dialog.show()
        self.host.alive = False

        dialog.close()

        self.assertEqual(self.host.calls, [])

    def test_position_is_saved_on_close(self) -> None:
        dialog = self.make()
        dialog.show()
        dialog.move(120, 140)

        dialog.reject()

        state = json.loads(Path("app_state.json").read_text(encoding="utf-8"))
        self.assertIn("settings_position", state)


class TestFields(QtSettingsTestCase):
    def test_number_fields_reject_invalid_typing(self) -> None:
        dialog = self.make()
        edit = dialog.timing_edits["key_pressed_time_min"]
        edit.clear()

        QTest.keyClicks(edit, "0a1-.5")

        self.assertEqual(edit.text(), "0")
        edit.clear()
        QTest.keyClicks(edit, "12345")
        self.assertEqual(edit.text(), "123")
        self.assertEqual(dialog.form.timing["key_pressed_time_min"], "123")

    def test_invalid_timing_shows_warning_in_timing_and_keeps_open(self) -> None:
        dialog = self.make()
        dialog.show()
        for name, text in (("key_pressed_time_min", "300"), ("key_pressed_time_max", "200")):
            edit = dialog.timing_edits[name]
            edit.clear()
            QTest.keyClicks(edit, text)

        dialog.ok_button.click()

        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.error_labels["timing"].isHidden())
        self.assertTrue(dialog.error_labels["keys"].isHidden())
        self.assertIn("Min must be less", dialog.error_labels["timing"].text())
        self.assertFalse(Path("user_settings.json").exists())
        self.assertEqual(self.host.calls, [])

    def test_key_capture_sets_start_stop_key(self) -> None:
        dialog = self.make()

        QTest.keyClick(dialog.key_edit, Qt.Key.Key_F5)
        self.assertEqual(dialog.key_edit.text(), "F5")
        QTest.keyClick(dialog.key_edit, Qt.Key.Key_K)
        self.assertEqual(dialog.key_edit.text(), "K")
        QTest.keyClick(dialog.key_edit, Qt.Key.Key_Exclam, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(dialog.form.settings.start_stop_key, "K")

        dialog.ok_button.click()

        self.assertEqual(self.saved()["start_stop_key"], "K")

    def test_mac_toggle_disables_key_and_saves_disabled(self) -> None:
        dialog = self.make(is_windows=False)

        dialog.hotkey_check.setChecked(False)

        self.assertFalse(dialog.key_edit.isEnabled())
        self.assertEqual(dialog.key_edit.text(), "")
        dialog.ok_button.click()
        self.assertEqual(self.saved()["start_stop_key"], "DISABLED")
        self.assertFalse(self.saved()["toggle_start_stop_mac"])

    def test_windows_requires_key_unless_alt_shift(self) -> None:
        save_user_settings(UserSettings(start_stop_key="DISABLED"))
        dialog = self.make(is_windows=True)
        dialog.show()

        dialog.ok_button.click()
        self.assertFalse(dialog.error_labels["keys"].isHidden())
        self.assertTrue(dialog.isVisible())

        dialog.hotkey_check.setChecked(True)
        self.assertFalse(dialog.key_edit.isEnabled())
        dialog.ok_button.click()

        self.assertFalse(dialog.isVisible())
        self.assertTrue(self.saved()["use_alt_shift_hotkey"])

    def test_language_switch_is_saved_and_applied(self) -> None:
        dialog = self.make()
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("ko"))

        dialog.ok_button.click()

        self.assertEqual(self.saved()["language"], "ko")
        self.assertEqual(txt("Settings", "설정"), "설정")

    def test_reset_shows_defaults_but_saves_only_on_ok(self) -> None:
        save_user_settings(UserSettings(key_pressed_time_min=200, key_pressed_time_max=300))
        before = Path("user_settings.json").read_text(encoding="utf-8")
        dialog = self.make()
        self.assertEqual(dialog.timing_edits["key_pressed_time_min"].text(), "200")

        with patch.object(SettingsDialog, "ask_reset", return_value=True):
            dialog.reset_button.click()

        self.assertEqual(dialog.timing_edits["key_pressed_time_min"].text(), "95")
        self.assertEqual(Path("user_settings.json").read_text(encoding="utf-8"), before)
        dialog.ok_button.click()
        self.assertEqual(self.saved()["key_pressed_time_min"], 95)

    def test_reset_cancelled_keeps_values(self) -> None:
        save_user_settings(UserSettings(key_pressed_time_min=200, key_pressed_time_max=300))
        dialog = self.make()

        with patch.object(SettingsDialog, "ask_reset", return_value=False):
            dialog.reset_button.click()

        self.assertEqual(dialog.timing_edits["key_pressed_time_min"].text(), "200")

    def test_sound_preview_uses_shared_player(self) -> None:
        dialog = self.make()
        dialog.sound_pack_combo.setCurrentIndex(dialog.sound_pack_combo.findData("soft_a"))
        dialog.toggle_sound_pack_combo.setCurrentIndex(
            dialog.toggle_sound_pack_combo.findData("soft_c")
        )
        player = self.host.sound_player

        with patch("app.utils.sounds.SoundPlayer") as new_player:
            dialog.preview_start_button.click()
            dialog.preview_off_button.click()
            new_player.assert_not_called()

        player.set_notification_pack.assert_called_with("soft_a")
        player.play_start_sound.assert_called_once()
        player.set_runtime_toggle_pack.assert_called_with("soft_c")
        player.play_runtime_toggle_off_sound.assert_called_once()

    def test_sound_fields_are_saved(self) -> None:
        dialog = self.make()
        dialog.sound_pack_combo.setCurrentIndex(dialog.sound_pack_combo.findData("soft_b"))
        dialog.toggle_sound_check.setChecked(False)

        dialog.ok_button.click()

        self.assertEqual(self.saved()["notification_sound_pack"], "soft_b")
        self.assertFalse(self.saved()["runtime_toggle_sound_enabled"])


class TestWithRunWindow(QtSettingsTestCase):
    def test_run_window_tools_entry_round_trip(self) -> None:
        from app.presenters.run_controller import RunController
        from app.ui.main_window import RunWindow

        patches = [
            patch("app.ui.main_window.ProcessCollector.get", return_value=[]),
            patch("app.ui.main_window.SoundPlayer", MagicMock),
            patch.object(RunController, "setup_event_handlers"),
            patch.object(RunController, "unbind_events"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        window = RunWindow()
        self.addCleanup(window.deleteLater)
        unbind = RunController.unbind_events
        setup = RunController.setup_event_handlers
        assert isinstance(unbind, MagicMock) and isinstance(setup, MagicMock)
        setup.reset_mock()

        window.open_settings()
        dialog = window.settings_dialog
        assert isinstance(dialog, SettingsDialog)
        unbind.assert_called()
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("ko"))
        dialog.ok_button.click()

        self.assertIsNone(window.settings_dialog)
        setup.assert_called_once()
        self.assertEqual(window.settings.language, "ko")
        self.assertEqual(window.lbl_target.text(), "실행")
        window._closing = True


if __name__ == "__main__":
    unittest.main(verbosity=2)
