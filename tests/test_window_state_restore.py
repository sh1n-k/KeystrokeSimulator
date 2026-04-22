import unittest
from unittest.mock import MagicMock, patch

from app.ui.event_editor import KeystrokeEventEditor
from app.ui.event_importer import EventImporter
from app.ui.profiles import KeystrokeProfiles
from app.ui.quick_event_editor import KeystrokeQuickEventEditor
from app.ui.settings import KeystrokeSettings
from app.ui.sort_events import KeystrokeSortEvents


class TestWindowStateRestore(unittest.TestCase):
    @patch("app.ui.quick_event_editor.WindowUtils.center_window")
    @patch("app.ui.quick_event_editor.StateUtils.load_main_app_state")
    def test_quick_editor_centers_on_invalid_quick_pos(
        self, mock_load_state, mock_center
    ):
        stub = KeystrokeQuickEventEditor.__new__(KeystrokeQuickEventEditor)
        stub.win = MagicMock()
        stub.entries = [MagicMock(), MagicMock()]
        stub._set_entries = MagicMock()
        stub.capturer = MagicMock()
        stub._refresh_status_text = MagicMock()
        mock_load_state.return_value = {"quick_pos": "bad", "quick_ptr": "(10, 20)"}

        KeystrokeQuickEventEditor._load_pos(stub)

        mock_center.assert_called_once_with(stub.win)
        stub._set_entries.assert_called_once_with(stub.entries[:2], 10, 20)
        stub.capturer.set_current_mouse_position.assert_called_once_with((10, 20))

    @patch("app.ui.event_editor.WindowUtils.center_window")
    @patch("app.ui.event_editor.StateUtils.load_main_app_state")
    def test_event_editor_centers_on_invalid_event_position(
        self, mock_load_state, mock_center
    ):
        stub = KeystrokeEventEditor.__new__(KeystrokeEventEditor)
        stub.win = MagicMock()
        stub.is_edit = False
        stub.capturer = MagicMock()
        mock_load_state.return_value = {"event_position": "bad", "event_pointer": "(3, 4)"}

        KeystrokeEventEditor.load_latest_position(stub)

        mock_center.assert_called_once_with(stub.win)
        stub.capturer.set_current_mouse_position.assert_called_once_with((3, 4))

    @patch("app.ui.profiles.WindowUtils.center_window")
    @patch("app.ui.profiles.StateUtils.load_main_app_state")
    def test_profiles_center_on_invalid_prof_pos(self, mock_load_state, mock_center):
        stub = KeystrokeProfiles.__new__(KeystrokeProfiles)
        stub.win = MagicMock()
        mock_load_state.return_value = {"prof_pos": "bad"}

        KeystrokeProfiles._load_pos(stub)

        mock_center.assert_called_once_with(stub.win)
        stub.win.geometry.assert_not_called()

    @patch("app.ui.event_importer.StateUtils.load_main_app_state")
    def test_event_importer_uses_default_geometry_on_invalid_importer_pos(
        self, mock_load_state
    ):
        stub = EventImporter.__new__(EventImporter)
        stub.win = MagicMock()
        mock_load_state.return_value = {"importer_pos": "bad"}

        EventImporter.load_pos(stub)

        stub.win.geometry.assert_called_once_with("500x600")

    @patch("app.ui.settings.WindowUtils.center_window")
    @patch("app.ui.settings.StateUtils.load_main_app_state")
    def test_settings_center_on_invalid_settings_position(
        self, mock_load_state, mock_center
    ):
        stub = MagicMock()
        mock_load_state.return_value = {"settings_position": "bad"}

        KeystrokeSettings._restore_window_position(stub)

        mock_center.assert_called_once_with(stub)


class TestSortWindowStateRestore(unittest.TestCase):
    @patch("app.ui.sort_events.WindowUtils.center_window")
    @patch("app.ui.sort_events.StateUtils.load_main_app_state")
    def test_sort_window_centers_on_invalid_org_pos(
        self, mock_load_state, mock_center
    ):
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.geometry = MagicMock()
        mock_load_state.return_value = {"org_pos": "bad", "org_size": "100/200"}

        KeystrokeSortEvents._load_state(stub)

        mock_center.assert_called_once_with(stub)
        stub.geometry.assert_not_called()

    @patch("app.ui.sort_events.WindowUtils.center_window")
    @patch("app.ui.sort_events.StateUtils.load_main_app_state")
    def test_sort_window_centers_on_invalid_org_size(
        self, mock_load_state, mock_center
    ):
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.geometry = MagicMock()
        mock_load_state.return_value = {"org_pos": "10/20", "org_size": "bad"}

        KeystrokeSortEvents._load_state(stub)

        mock_center.assert_called_once_with(stub)
        stub.geometry.assert_not_called()

    @patch("app.ui.sort_events.WindowUtils.center_window")
    @patch("app.ui.sort_events.StateUtils.load_main_app_state")
    def test_sort_window_centers_on_partial_state(
        self, mock_load_state, mock_center
    ):
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.geometry = MagicMock()
        mock_load_state.return_value = {"org_pos": "10/20"}

        KeystrokeSortEvents._load_state(stub)

        mock_center.assert_called_once_with(stub)
        stub.geometry.assert_not_called()

    @patch("app.ui.sort_events.WindowUtils.center_window")
    @patch("app.ui.sort_events.StateUtils.load_main_app_state")
    def test_sort_window_restores_when_both_position_and_size_are_valid(
        self, mock_load_state, mock_center
    ):
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.geometry = MagicMock()
        mock_load_state.return_value = {"org_pos": "10/20", "org_size": "300/400"}

        KeystrokeSortEvents._load_state(stub)

        stub.geometry.assert_called_once_with("300x400+10+20")
        mock_center.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
