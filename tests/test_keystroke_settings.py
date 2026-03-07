import json
import os
import tkinter as tk
import unittest
from unittest.mock import patch, mock_open, MagicMock

from keystroke_models import UserSettings
from keystroke_settings import KeystrokeSettings

_RUN_GUI_TESTS = os.environ.get("RUN_GUI_TESTS", "0") == "1"


@unittest.skipUnless(_RUN_GUI_TESTS, "GUI tests require RUN_GUI_TESTS=1")
class TestKeystrokeSettings(unittest.TestCase):
    def setUp(self):
        # Create a hidden Tk root for Toplevel widgets
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    @patch("keystroke_settings.Path.exists")
    @patch("keystroke_settings.Path.read_text")
    def test_load_settings_success(self, mock_read_text, mock_exists):
        mock_exists.return_value = True
        fake_data = {
            "key_pressed_time_min": 100,
            "delay_between_loop_max": 300,
            "language": "ko",
        }
        mock_read_text.return_value = json.dumps(fake_data)

        # Mock geometry/center_window to avoid screen size issues in headless
        with patch("keystroke_settings.WindowUtils.center_window"):
            settings_win = KeystrokeSettings(self.root)

        self.assertEqual(settings_win.settings.key_pressed_time_min, 100)
        self.assertEqual(settings_win.settings.delay_between_loop_max, 300)
        self.assertEqual(settings_win.settings.language, "ko")
        # Default value for others
        self.assertEqual(settings_win.settings.key_pressed_time_max, 135)
        settings_win.destroy()

    @patch("keystroke_settings.Path.exists")
    @patch("keystroke_settings.Path.read_text")
    def test_load_settings_fallback_on_invalid_language(self, mock_read_text, mock_exists):
        mock_exists.return_value = True
        mock_read_text.return_value = json.dumps({"language": "jp"})

        with patch("keystroke_settings.WindowUtils.center_window"):
            settings_win = KeystrokeSettings(self.root)

        self.assertEqual(settings_win.settings.language, "en")
        settings_win.destroy()

    @patch("keystroke_settings.Path.exists")
    def test_load_settings_fallback_on_missing(self, mock_exists):
        mock_exists.return_value = False

        with patch("keystroke_settings.WindowUtils.center_window"):
            settings_win = KeystrokeSettings(self.root)

        # Should load default UserSettings
        default_settings = UserSettings()
        self.assertEqual(settings_win.settings.key_pressed_time_min, default_settings.key_pressed_time_min)
        settings_win.destroy()

    @patch("keystroke_settings.Path.write_text")
    def test_save_settings(self, mock_write_text):
        with patch("keystroke_settings.WindowUtils.center_window"):
            settings_win = KeystrokeSettings(self.root)

        settings_win.settings.key_pressed_time_min = 123
        settings_win.settings.language = "ko"
        settings_win._save_settings()

        mock_write_text.assert_called_once()
        saved_data = json.loads(mock_write_text.call_args[0][0])
        self.assertEqual(saved_data["key_pressed_time_min"], 123)
        self.assertEqual(saved_data["language"], "ko")
        settings_win.destroy()

class TestValidateNumeric(unittest.TestCase):
    """_validate_numeric: Tk 불필요한 static method 테스트"""

    def test_validate_numeric_basic(self):
        self.assertTrue(KeystrokeSettings._validate_numeric(""))
        self.assertTrue(KeystrokeSettings._validate_numeric("0"))
        self.assertTrue(KeystrokeSettings._validate_numeric("999"))

        self.assertFalse(KeystrokeSettings._validate_numeric("1000"))
        self.assertFalse(KeystrokeSettings._validate_numeric("01"))
        self.assertFalse(KeystrokeSettings._validate_numeric("abc"))
        self.assertFalse(KeystrokeSettings._validate_numeric("-5"))

    def test_validate_numeric_float(self):
        """부동소수점 입력은 거부"""
        self.assertFalse(KeystrokeSettings._validate_numeric("3.14"))

    def test_validate_numeric_very_large(self):
        """매우 큰 수는 거부 (>= 1000)"""
        self.assertFalse(KeystrokeSettings._validate_numeric("99999"))


class TestKeystrokeSettingsWindowState(unittest.TestCase):
    @patch("keystroke_settings.StateUtils.load_main_app_state")
    @patch("keystroke_settings.WindowUtils.center_window")
    def test_restore_window_position_uses_saved_coordinates(self, mock_center, mock_load_state):
        mock_load_state.return_value = {"settings_position": "120/340"}
        stub = MagicMock()

        KeystrokeSettings._restore_window_position(stub)

        stub.geometry.assert_called_once_with("+120+340")
        mock_center.assert_not_called()

    @patch("keystroke_settings.StateUtils.load_main_app_state")
    @patch("keystroke_settings.WindowUtils.center_window")
    def test_restore_window_position_centers_when_missing(self, mock_center, mock_load_state):
        mock_load_state.return_value = {}
        stub = MagicMock()

        KeystrokeSettings._restore_window_position(stub)

        mock_center.assert_called_once_with(stub)

    @patch("keystroke_settings.StateUtils.save_main_app_state")
    def test_save_window_position_persists_coordinates(self, mock_save_state):
        stub = MagicMock()
        stub.winfo_x.return_value = 55
        stub.winfo_y.return_value = 77

        KeystrokeSettings._save_window_position(stub)

        mock_save_state.assert_called_once_with(settings_position="55/77")


if __name__ == "__main__":
    unittest.main()
