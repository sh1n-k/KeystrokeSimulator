import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.domain.models import UserSettings
from app.presenters.settings_form import FormError, SaveResult, SettingsForm
from app.storage.settings_storage import save_user_settings
from app.utils.i18n import set_language, txt


class SettingsFormTestCase(unittest.TestCase):
    def setUp(self) -> None:
        set_language("en")
        self.addCleanup(set_language, "en")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "user_settings.json"

    def form(self, *, is_windows: bool = False, **values: object) -> SettingsForm:
        return SettingsForm(UserSettings(**values), is_windows=is_windows, path=self.path)  # type: ignore[arg-type]

    def saved(self) -> dict[str, object]:
        return json.loads(self.path.read_text(encoding="utf-8"))


class TestLoad(SettingsFormTestCase):
    def test_load_reads_file_and_applies_language(self) -> None:
        self.path.write_text(
            json.dumps(
                {"key_pressed_time_min": 100, "delay_between_loop_max": 300, "language": "ko"}
            ),
            encoding="utf-8",
        )

        form = SettingsForm.load(self.path)

        self.assertEqual(form.settings.key_pressed_time_min, 100)
        self.assertEqual(form.settings.delay_between_loop_max, 300)
        self.assertEqual(form.settings.key_pressed_time_max, 135)
        self.assertEqual(form.settings.language, "ko")
        self.assertEqual(form.timing["key_pressed_time_min"], "100")

    def test_invalid_language_falls_back_to_english(self) -> None:
        self.path.write_text(json.dumps({"language": "jp"}), encoding="utf-8")

        self.assertEqual(SettingsForm.load(self.path).settings.language, "en")

    def test_missing_file_gives_defaults(self) -> None:
        form = SettingsForm.load(self.path)

        self.assertEqual(form.settings, UserSettings())
        self.assertFalse(self.path.exists())


class TestStartStopKey(SettingsFormTestCase):
    def test_mac_disable_sets_disabled_and_enable_restores_default(self) -> None:
        form = self.form(start_stop_key="Q")

        form.set_mac_hotkey_enabled(False)
        self.assertEqual(form.settings.start_stop_key, "DISABLED")
        self.assertFalse(form.key_capture_enabled)

        form.set_mac_hotkey_enabled(True)
        self.assertEqual(form.settings.start_stop_key, "`")
        self.assertTrue(form.key_capture_enabled)

    def test_mac_ignores_keys_while_disabled(self) -> None:
        form = self.form(toggle_start_stop_mac=False, start_stop_key="DISABLED")

        self.assertFalse(form.capture_key("a"))
        self.assertEqual(form.settings.start_stop_key, "DISABLED")

    def test_capture_accepts_alnum_symbols_and_function_keys(self) -> None:
        form = self.form()
        for key, expected in (("a", "A"), ("7", "7"), ("[", "["), ("F12", "F12")):
            self.assertTrue(form.capture_key(key))
            self.assertEqual(form.settings.start_stop_key, expected)

    def test_capture_rejects_other_keys(self) -> None:
        form = self.form(start_stop_key="Q")
        for key in ("!", "RETURN", "~", ""):
            self.assertFalse(form.capture_key(key))
        self.assertEqual(form.settings.start_stop_key, "Q")

    def test_windows_alt_shift_locks_key_field(self) -> None:
        form = self.form(is_windows=True)

        form.set_use_alt_shift(True)

        self.assertFalse(form.key_capture_enabled)
        self.assertFalse(form.capture_key("A"))

    def test_wheel_keys_round_trip_unchanged(self) -> None:
        form = self.form(is_windows=True, start_stop_key="W_UP")

        result = form.submit()

        self.assertIsInstance(result, SaveResult)
        self.assertEqual(self.saved()["start_stop_key"], "W_UP")
        self.assertEqual(form.start_stop_key_display, "W_UP")

    def test_windows_requires_key_without_alt_shift(self) -> None:
        form = self.form(is_windows=True, start_stop_key="DISABLED")

        result = form.submit()

        self.assertIsInstance(result, FormError)
        assert isinstance(result, FormError)
        self.assertEqual(result.section, "keys")
        self.assertFalse(self.path.exists())

    def test_windows_alt_shift_needs_no_key(self) -> None:
        form = self.form(is_windows=True, start_stop_key="DISABLED")
        form.set_use_alt_shift(True)

        self.assertIsInstance(form.submit(), SaveResult)
        self.assertTrue(self.saved()["use_alt_shift_hotkey"])

    def test_mac_disabled_saves_disabled_key(self) -> None:
        form = self.form()
        form.set_mac_hotkey_enabled(False)

        self.assertIsInstance(form.submit(), SaveResult)
        saved = self.saved()
        self.assertEqual(saved["start_stop_key"], "DISABLED")
        self.assertFalse(saved["toggle_start_stop_mac"])


class TestTiming(SettingsFormTestCase):
    def test_entry_validation_matches_tk(self) -> None:
        form = self.form()
        self.assertTrue(form.set_timing("key_pressed_time_min", ""))
        self.assertTrue(form.set_timing("key_pressed_time_min", "999"))
        for bad in ("1000", "01", "abc", "-5", "3.14"):
            self.assertFalse(form.set_timing("key_pressed_time_min", bad))
        self.assertFalse(form.set_timing("unknown", "100"))
        self.assertEqual(form.timing["key_pressed_time_min"], "999")

    def test_min_not_less_than_max_is_rejected_in_timing(self) -> None:
        form = self.form()
        form.set_timing("key_pressed_time_min", "300")
        form.set_timing("key_pressed_time_max", "200")

        result = form.submit()

        assert isinstance(result, FormError)
        self.assertEqual(result.section, "timing")
        self.assertIn("Min must be less", result.message)
        self.assertFalse(self.path.exists())

    def test_out_of_range_is_rejected(self) -> None:
        form = self.form()
        form.set_timing("delay_between_loop_min", "40")

        result = form.submit()

        assert isinstance(result, FormError)
        self.assertIn("between 50 and 500", result.message)

    def test_empty_counts_as_zero(self) -> None:
        form = self.form()
        form.set_timing("key_pressed_time_min", "")

        result = form.submit()

        assert isinstance(result, FormError)
        self.assertEqual(result.section, "timing")

    def test_failed_validation_keeps_working_copy_untouched(self) -> None:
        form = self.form()
        form.set_timing("key_pressed_time_min", "60")
        form.set_timing("delay_between_loop_min", "10")

        form.submit()

        self.assertEqual(form.settings.key_pressed_time_min, 95)


class TestSubmitAndReset(SettingsFormTestCase):
    def test_submit_saves_all_fields(self) -> None:
        form = self.form()
        form.set_timing("key_pressed_time_min", "60")
        form.set_timing("key_pressed_time_max", "70")
        form.set_timing("delay_between_loop_min", "200")
        form.set_timing("delay_between_loop_max", "500")
        form.settings.notification_sound_pack = "soft_b"
        form.settings.runtime_toggle_sound_pack = "bogus"
        form.settings.runtime_toggle_sound_enabled = False

        result = form.submit()

        assert isinstance(result, SaveResult)
        self.assertFalse(result.language_changed)
        saved = self.saved()
        self.assertEqual(
            (
                saved["key_pressed_time_min"],
                saved["key_pressed_time_max"],
                saved["delay_between_loop_min"],
                saved["delay_between_loop_max"],
            ),
            (60, 70, 200, 500),
        )
        self.assertEqual(saved["notification_sound_pack"], "soft_b")
        self.assertEqual(saved["runtime_toggle_sound_pack"], "classic")
        self.assertFalse(saved["runtime_toggle_sound_enabled"])
        self.assertEqual(set(saved), set(UserSettings().__dict__))

    def test_language_change_is_reported_and_applied(self) -> None:
        form = self.form()
        form.settings.language = "ko"

        result = form.submit()

        assert isinstance(result, SaveResult)
        self.assertTrue(result.language_changed)
        self.assertEqual(self.saved()["language"], "ko")
        self.assertEqual(txt("a", "b"), "b")

    def test_reset_shows_defaults_without_saving(self) -> None:
        save_user_settings(
            UserSettings(key_pressed_time_min=200, key_pressed_time_max=300), self.path
        )
        before = self.path.read_text(encoding="utf-8")
        form = SettingsForm.load(self.path)

        with patch("app.presenters.settings_form.save_user_settings") as save:
            form.reset()
            save.assert_not_called()

        self.assertEqual(form.settings, UserSettings())
        self.assertEqual(form.timing["key_pressed_time_min"], "95")
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_save_failure_is_logged_and_still_returns_result(self) -> None:
        form = self.form()
        with patch(
            "app.presenters.settings_form.save_user_settings", side_effect=OSError("x")
        ):
            self.assertIsInstance(form.submit(), SaveResult)


if __name__ == "__main__":
    unittest.main()
