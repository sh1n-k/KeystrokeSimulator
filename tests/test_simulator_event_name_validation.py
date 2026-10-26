import unittest
from unittest.mock import patch

from app.domain.models import EventModel, ProfileModel
from tests.test_run_controller import _make_app_stub
from app.utils.i18n import set_language


class TestSimulatorEventNameValidation(unittest.TestCase):
    def _make_app_stub(self):
        app = _make_app_stub()
        app.selected_process.set("TargetApp (123)")
        app.selected_profile.set("TestProfile")
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

        with patch("app.presenters.run_controller.load_profile", return_value=profile), patch(
            "app.presenters.run_controller.PermissionUtils.missing_macos_permissions",
            return_value=[],
        ):
            snapshot = app.readiness()

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Duplicate Events")
        self.assertIn("Duplicate event names were found", snapshot["title"])

    def test_start_simulation_returns_false_for_duplicate_event_names(self):
        app = self._make_app_stub()
        profile = ProfileModel(
            name="TestProfile",
            event_list=[
                EventModel(event_name="A", key_to_enter="X", use_event=True),
                EventModel(event_name="A", key_to_enter="Y", use_event=True),
            ],
        )

        with patch("app.presenters.run_controller.load_profile", return_value=profile):
            result = app.start_simulation()

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
