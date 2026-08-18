import json
import tempfile
import unittest
from pathlib import Path

from app.core.models import UserSettings
from app.storage.settings_storage import load_user_settings, save_user_settings


class TestUserSettingsStorage(unittest.TestCase):
    def test_load_missing_returns_default_and_can_save(self):
        with tempfile.TemporaryDirectory() as td:
            settings, can_save = load_user_settings(Path(td) / "missing.json")

        self.assertTrue(can_save)
        self.assertEqual(settings, UserSettings())

    def test_load_invalid_json_returns_default_without_rewrite_permission(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            path.write_text("{bad", encoding="utf-8")

            settings, can_save = load_user_settings(path)

            self.assertFalse(can_save)
            self.assertEqual(settings, UserSettings())
            self.assertEqual(path.read_text(encoding="utf-8"), "{bad")

    def test_load_non_object_returns_default_without_rewrite_permission(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            path.write_text("[]", encoding="utf-8")

            settings, can_save = load_user_settings(path)

            self.assertFalse(can_save)
            self.assertEqual(settings, UserSettings())

    def test_load_coerces_known_safe_values_and_ignores_invalid_types(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "language": "ko",
                        "key_pressed_time_min": "123",
                        "toggle_start_stop_mac": "yes",
                    }
                ),
                encoding="utf-8",
            )

            settings, can_save = load_user_settings(path)

            self.assertTrue(can_save)
            self.assertEqual(settings.language, "ko")
            self.assertEqual(settings.key_pressed_time_min, 123)
            self.assertEqual(
                settings.toggle_start_stop_mac, UserSettings().toggle_start_stop_mac
            )

    def test_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            settings = UserSettings(language="ko", key_pressed_time_min=111)

            save_user_settings(settings, path)
            loaded, can_save = load_user_settings(path)

            self.assertTrue(can_save)
            self.assertEqual(loaded.language, "ko")
            self.assertEqual(loaded.key_pressed_time_min, 111)

    def test_notification_sound_pack_roundtrip_and_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            settings = UserSettings(notification_sound_pack="soft_b")
            save_user_settings(settings, path)
            loaded, can_save = load_user_settings(path)
            self.assertTrue(can_save)
            self.assertEqual(loaded.notification_sound_pack, "soft_b")

            path.write_text(
                json.dumps({"notification_sound_pack": "not-a-pack"}),
                encoding="utf-8",
            )
            loaded, can_save = load_user_settings(path)
            self.assertTrue(can_save)
            self.assertEqual(loaded.notification_sound_pack, "classic")

            path.write_text(
                json.dumps({"notification_sound_pack": 123}),
                encoding="utf-8",
            )
            loaded, can_save = load_user_settings(path)
            self.assertTrue(can_save)
            self.assertEqual(loaded.notification_sound_pack, "classic")

    def test_runtime_toggle_sound_roundtrip_and_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "user_settings.json"
            settings = UserSettings(
                runtime_toggle_sound_pack="soft_c",
                runtime_toggle_sound_enabled=False,
            )
            save_user_settings(settings, path)
            loaded, can_save = load_user_settings(path)
            self.assertTrue(can_save)
            self.assertEqual(loaded.runtime_toggle_sound_pack, "soft_c")
            self.assertFalse(loaded.runtime_toggle_sound_enabled)

            path.write_text(
                json.dumps({"runtime_toggle_sound_pack": "not-a-pack"}),
                encoding="utf-8",
            )
            loaded, can_save = load_user_settings(path)
            self.assertTrue(can_save)
            self.assertEqual(loaded.runtime_toggle_sound_pack, "classic")
            self.assertTrue(loaded.runtime_toggle_sound_enabled)

            path.write_text(
                json.dumps(
                    {
                        "runtime_toggle_sound_pack": 123,
                        "runtime_toggle_sound_enabled": "nope",
                    }
                ),
                encoding="utf-8",
            )
            loaded, can_save = load_user_settings(path)
            self.assertTrue(can_save)
            self.assertEqual(loaded.runtime_toggle_sound_pack, "classic")
            self.assertTrue(loaded.runtime_toggle_sound_enabled)


if __name__ == "__main__":
    unittest.main()
