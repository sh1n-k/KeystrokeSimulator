import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.models import EventModel, ProfileModel
from app.ui.simulator_app import KeystrokeSimulatorApp
from app.utils.i18n import set_language


class TestSimulatorEventNameValidation(unittest.TestCase):
    def _make_app_stub(self):
        app = KeystrokeSimulatorApp.__new__(KeystrokeSimulatorApp)
        app.is_running = SimpleNamespace(get=lambda: False)
        app.selected_process = SimpleNamespace(get=lambda: "TargetApp (123)")
        app.selected_profile = SimpleNamespace(get=lambda: "TestProfile")
        app.profiles_dir = "profiles"
        return app

    def test_readiness_snapshot_blocks_duplicate_event_names(self):
        set_language("en")
        app = self._make_app_stub()
        profile = ProfileModel(
            name="TestProfile",
            event_list=[
                EventModel(event_name="A", key_to_enter="X"),
                EventModel(event_name="A", key_to_enter="Y"),
            ],
        )

        with patch("app.ui.simulator_app.load_profile", return_value=profile), patch(
            "app.ui.simulator_app.PermissionUtils.missing_macos_permissions",
            return_value=[],
        ):
            snapshot = app._get_readiness_snapshot()

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Duplicate Events")
        self.assertIn("Duplicate event names were found", snapshot["title"])

    def test_start_simulation_returns_false_for_duplicate_event_names(self):
        app = self._make_app_stub()
        app.terminate_event = SimpleNamespace(clear=lambda: None)
        app.sound_player = SimpleNamespace(play_start_sound=lambda: None)
        app._save_latest_state = lambda: None
        app.keystroke_processor = None
        profile = ProfileModel(
            name="TestProfile",
            event_list=[
                EventModel(event_name="A", key_to_enter="X", use_event=True),
                EventModel(event_name="A", key_to_enter="Y", use_event=True),
            ],
        )

        with patch("app.ui.simulator_app.load_profile", return_value=profile):
            result = app._start_simulation()

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
