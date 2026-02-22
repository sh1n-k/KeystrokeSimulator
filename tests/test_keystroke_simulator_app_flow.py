import unittest
from unittest.mock import MagicMock, patch

from keystroke_models import EventModel, ProfileModel
from keystroke_simulator_app import KeystrokeSimulatorApp


class FakeVar:
    def __init__(self, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _make_app_stub() -> KeystrokeSimulatorApp:
    app = KeystrokeSimulatorApp.__new__(KeystrokeSimulatorApp)
    app.profiles_dir = "profiles"
    app.selected_process = FakeVar("")
    app.selected_profile = FakeVar("")
    app.is_running = FakeVar(False)
    app.keystroke_processor = None
    app.terminate_event = MagicMock()
    app.sound_player = MagicMock()
    app._save_latest_state = MagicMock()
    app.update_ui = MagicMock()
    app._update_ui = MagicMock()
    app.winfo_exists = MagicMock(return_value=True)
    return app


class TestStartSimulation(unittest.TestCase):
    def test_start_simulation_requires_valid_process_and_profile(self):
        app = _make_app_stub()
        app.selected_process.set("")
        app.selected_profile.set("Quick")

        self.assertFalse(KeystrokeSimulatorApp._start_simulation(app))

    @patch("keystroke_simulator_app.KeystrokeProcessor")
    @patch("keystroke_simulator_app.load_profile")
    def test_start_simulation_filters_events_and_starts_processor(
        self, mock_load_profile, mock_processor_cls
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")

        profile = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(event_name="Action", use_event=True, key_to_enter="A"),
                EventModel(
                    event_name="ConditionOnly",
                    use_event=True,
                    key_to_enter=None,
                    execute_action=False,
                ),
                EventModel(
                    event_name="Invalid",
                    use_event=True,
                    key_to_enter=None,
                    execute_action=True,
                ),
                EventModel(event_name="Disabled", use_event=False, key_to_enter="B"),
            ],
            modification_keys={"alt": {"enabled": True, "pass": True, "value": "Pass"}},
        )
        mock_load_profile.return_value = profile
        mock_processor = MagicMock()
        mock_processor_cls.return_value = mock_processor

        result = KeystrokeSimulatorApp._start_simulation(app)

        self.assertTrue(result)
        app.terminate_event.clear.assert_called_once()
        app._save_latest_state.assert_called_once()
        app.sound_player.play_start_sound.assert_called_once()
        mock_processor.start.assert_called_once()

        passed_events = mock_processor_cls.call_args.args[2]
        self.assertEqual([e.event_name for e in passed_events], ["Action", "ConditionOnly"])

    @patch("keystroke_simulator_app.load_profile", side_effect=RuntimeError("boom"))
    def test_start_simulation_returns_false_on_profile_load_error(self, _mock_load_profile):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")

        self.assertFalse(KeystrokeSimulatorApp._start_simulation(app))


class TestToggleAndStopSimulation(unittest.TestCase):
    def test_toggle_start_stop_starts_when_not_running(self):
        app = _make_app_stub()
        app.start_simulation = MagicMock(return_value=True)
        app.stop_simulation = MagicMock()
        app.is_running.set(False)

        KeystrokeSimulatorApp.toggle_start_stop(app)

        self.assertTrue(app.is_running.get())
        app.update_ui.assert_called_once()
        app.stop_simulation.assert_not_called()

    def test_toggle_start_stop_does_not_flip_state_if_start_fails(self):
        app = _make_app_stub()
        app.start_simulation = MagicMock(return_value=False)
        app.stop_simulation = MagicMock()
        app.is_running.set(False)

        KeystrokeSimulatorApp.toggle_start_stop(app)

        self.assertFalse(app.is_running.get())
        app.update_ui.assert_not_called()
        app.stop_simulation.assert_not_called()

    def test_toggle_start_stop_stops_when_running(self):
        app = _make_app_stub()
        app.start_simulation = MagicMock(return_value=True)
        app.stop_simulation = MagicMock()
        app.is_running.set(True)

        KeystrokeSimulatorApp.toggle_start_stop(app)

        self.assertFalse(app.is_running.get())
        app.stop_simulation.assert_called_once()

    def test_stop_simulation_stops_processor_and_updates_ui(self):
        app = _make_app_stub()
        processor = MagicMock()
        app.keystroke_processor = processor
        app.winfo_exists.return_value = True

        KeystrokeSimulatorApp._stop_simulation(app)

        processor.stop.assert_called_once()
        app.terminate_event.set.assert_called_once()
        app.sound_player.play_stop_sound.assert_called_once()
        app._update_ui.assert_called_once()
        self.assertIsNone(app.keystroke_processor)

    def test_stop_simulation_skips_ui_update_when_app_is_destroyed(self):
        app = _make_app_stub()
        app.keystroke_processor = MagicMock()
        app.winfo_exists.return_value = False

        KeystrokeSimulatorApp._stop_simulation(app)

        app.sound_player.play_stop_sound.assert_not_called()
        app._update_ui.assert_not_called()


class TestMainUiState(unittest.TestCase):
    def _make_ui_stub(self, running: bool) -> KeystrokeSimulatorApp:
        app = _make_app_stub()
        app.is_running = FakeVar(running)

        app.process_frame = MagicMock()
        app.process_frame.process_combobox = MagicMock()
        app.process_frame.refresh_button = MagicMock()

        app.profile_frame = MagicMock()
        app.profile_frame.profile_combobox = MagicMock()
        app.profile_frame.copy_button = MagicMock()
        app.profile_frame.del_button = MagicMock()

        app.button_frame = MagicMock()
        app.button_frame.start_stop_button = MagicMock()
        app.button_frame.quick_events_button = MagicMock()
        app.button_frame.settings_button = MagicMock()
        app.button_frame.clear_logs_button = MagicMock()

        app.profile_button_frame = MagicMock()
        app.profile_button_frame.modkeys_button = MagicMock()
        app.profile_button_frame.settings_button = MagicMock()
        app.profile_button_frame.sort_button = MagicMock()
        return app

    def test_update_ui_disables_quick_events_and_modkeys_when_running(self):
        app = self._make_ui_stub(running=True)

        KeystrokeSimulatorApp._update_ui(app)

        app.button_frame.quick_events_button.config.assert_called_once_with(
            state="disabled"
        )
        app.profile_button_frame.modkeys_button.config.assert_called_once_with(
            state="disabled"
        )

    def test_update_ui_enables_quick_events_and_modkeys_when_stopped(self):
        app = self._make_ui_stub(running=False)

        KeystrokeSimulatorApp._update_ui(app)

        app.button_frame.quick_events_button.config.assert_called_once_with(
            state="normal"
        )
        app.profile_button_frame.modkeys_button.config.assert_called_once_with(
            state="normal"
        )


class TestRuntimeEditGuards(unittest.TestCase):
    @patch("keystroke_simulator_app.KeystrokeQuickEventEditor")
    def test_open_quick_events_noop_when_running(self, mock_editor):
        app = _make_app_stub()
        app.is_running = FakeVar(True)

        KeystrokeSimulatorApp.open_quick_events(app)

        mock_editor.assert_not_called()

    @patch("keystroke_simulator_app.KeystrokeQuickEventEditor")
    def test_open_quick_events_opens_when_stopped(self, mock_editor):
        app = _make_app_stub()
        app.is_running = FakeVar(False)

        KeystrokeSimulatorApp.open_quick_events(app)

        mock_editor.assert_called_once_with(app)

    @patch("keystroke_simulator_app.ModificationKeysWindow")
    def test_open_modkeys_noop_when_running(self, mock_modkeys):
        app = _make_app_stub()
        app.is_running = FakeVar(True)
        app.selected_profile = FakeVar("Quick")

        KeystrokeSimulatorApp.open_modkeys(app)

        mock_modkeys.assert_not_called()

    @patch("keystroke_simulator_app.ModificationKeysWindow")
    def test_open_modkeys_opens_when_stopped(self, mock_modkeys):
        app = _make_app_stub()
        app.is_running = FakeVar(False)
        app.selected_profile = FakeVar("Quick")

        KeystrokeSimulatorApp.open_modkeys(app)

        mock_modkeys.assert_called_once_with(app, "Quick")


class TestSaveLatestState(unittest.TestCase):
    @patch("keystroke_simulator_app.StateUtils.save_main_app_state")
    def test_save_latest_state_strips_pid_suffix(self, mock_save_state):
        app = _make_app_stub()
        app.selected_process = FakeVar("SomeProcess (4321)")
        app.selected_profile = FakeVar("Quick")

        KeystrokeSimulatorApp._save_latest_state(app)

        mock_save_state.assert_called_once_with(process="SomeProcess", profile="Quick")


if __name__ == "__main__":
    unittest.main(verbosity=2)
