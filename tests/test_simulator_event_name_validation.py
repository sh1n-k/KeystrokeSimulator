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

    def test_duplicate_badge_does_not_depend_on_ui_language(self):
        set_language("ko")
        self.addCleanup(set_language, "en")
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

        self.assertEqual(snapshot["badge_text"], "중복 이벤트")

    def test_load_error_mentioning_duplicate_is_not_classified_as_duplicate(self):
        set_language("en")
        app = self._make_app_stub()

        with patch(
            "app.presenters.run_controller.load_profile",
            side_effect=ValueError("duplicate key in JSON"),
        ):
            snapshot = app.readiness()

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Profile Error")
        self.assertIn("duplicate key in JSON", snapshot["detail"])

    def test_load_error_before_session_error_stays_unclassified(self):
        set_language("en")
        app = _make_app_stub()
        app.selected_process.set("TargetApp (123)")
        app.selected_run_set.set("Raid")
        app.run_profile_names = lambda: ["Broken", "Dup"]
        dup = ProfileModel(
            name="Dup",
            event_list=[
                EventModel(event_name="A", key_to_enter="X"),
                EventModel(event_name="A", key_to_enter="Y"),
            ],
        )

        def load(_dir, name, migrate=True):
            if name == "Broken":
                raise ValueError("broken file")
            return dup

        with patch("app.presenters.run_controller.load_profile", side_effect=load):
            snapshot = app.readiness()

        # 첫 오류(불러오기 실패)를 그대로 보이고, 뒤따르는 중복 오류로 분류하지 않는다.
        self.assertEqual(snapshot["badge_text"], "Profile Error")
        self.assertIn("broken file", snapshot["detail"])

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
