import unittest
from unittest.mock import MagicMock, patch

from app.ui.capture_hud import CaptureHud
from app.engine.capture_session import CaptureSession
from app.ui.settings import KeystrokeSettings
from app.ui.simulator_app import KeystrokeSimulatorApp
from app.ui.workspace import Workspace


class TestWindowStateRestore(unittest.TestCase):
    @patch("app.ui.capture_hud.WindowUtils.center_window")
    @patch("app.ui.capture_hud.StateUtils.load_main_app_state")
    def test_capture_hud_centers_on_invalid_position(
        self, mock_load_state, mock_center
    ):
        stub = CaptureHud.__new__(CaptureHud)
        stub.win = MagicMock()
        stub.capture_session = CaptureSession(MagicMock())
        stub._pointer_state_key = "quick_ptr"
        mock_load_state.return_value = {
            "capture_hud_pos": "bad",
            "quick_ptr": "(10, 20)",
        }

        CaptureHud._restore_state(stub, restore_pointer=True)

        mock_center.assert_called_once_with(stub.win)
        stub.capture_session.capturer.set_current_mouse_position.assert_called_once_with(
            (10, 20)
        )

    @patch("app.ui.settings.WindowUtils.center_window")
    @patch("app.ui.settings.StateUtils.load_main_app_state")
    def test_settings_center_on_invalid_settings_position(
        self, mock_load_state, mock_center
    ):
        stub = MagicMock()
        mock_load_state.return_value = {"settings_position": "bad"}

        KeystrokeSettings._restore_window_position(stub)

        mock_center.assert_called_once_with(stub)

    @patch("app.ui.simulator_app.WindowUtils.center_window")
    @patch("app.ui.simulator_app.StateUtils.load_main_app_state")
    def test_main_window_centers_on_invalid_main_pos(
        self, mock_load_state, mock_center
    ):
        stub = MagicMock()
        mock_load_state.return_value = {"main_pos": "bad"}

        KeystrokeSimulatorApp._restore_window_position(stub)

        mock_center.assert_called_once_with(stub)
        stub.geometry.assert_not_called()


class TestWorkspaceStateRestore(unittest.TestCase):
    def _stub(self):
        stub = Workspace.__new__(Workspace)
        stub.win = MagicMock()
        return stub

    @patch("app.ui.workspace.WindowUtils.center_window")
    @patch("app.ui.workspace.StateUtils.load_main_app_state")
    def test_workspace_centers_on_invalid_state(self, mock_load_state, mock_center):
        for state in (
            {"workspace_pos": "bad", "workspace_size": "100/200"},
            {"workspace_pos": "10/20", "workspace_size": "bad"},
            {"workspace_pos": "10/20"},
        ):
            with self.subTest(state=state):
                stub = self._stub()
                mock_load_state.return_value = state
                mock_center.reset_mock()

                Workspace._restore_geometry(stub)

                mock_center.assert_called_once_with(stub.win)
                stub.win.geometry.assert_not_called()

    @patch("app.ui.workspace.WindowUtils.center_window")
    @patch("app.ui.workspace.StateUtils.load_main_app_state")
    def test_workspace_restores_position_and_size(self, mock_load_state, mock_center):
        stub = self._stub()
        mock_load_state.return_value = {
            "workspace_pos": "10/20",
            "workspace_size": "1200/700",
        }

        Workspace._restore_geometry(stub)

        stub.win.geometry.assert_called_once_with("1200x700+10+20")
        mock_center.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
