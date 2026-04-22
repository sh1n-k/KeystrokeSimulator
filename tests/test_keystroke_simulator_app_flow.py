import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.models import EventModel, ProfileModel
from app.ui.simulator_app import KeystrokeSimulatorApp
from app.utils.system import KeyUtils
from app.utils.runtime_toggle import (
    MOUSE_BUTTON_3_TRIGGER,
    WHEEL_DOWN_TRIGGER,
    WHEEL_UP_TRIGGER,
)


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
    app._update_main_status = MagicMock()
    app._target_process_is_active = MagicMock(return_value=True)
    app._setup_event_handlers = MagicMock()
    app.winfo_exists = MagicMock(return_value=True)
    app.bind = MagicMock()
    app.protocol = MagicMock()
    app.unbind_events = MagicMock()
    app.runtime_toggle_enabled = False
    app.runtime_toggle_key = None
    app.runtime_toggle_active = False
    app.runtime_toggle_member_count = 0
    app.runtime_toggle_mouse_listener = None
    app.last_runtime_toggle_time = 0
    app.latest_runtime_scroll_time = None
    app.toggle_transition_in_progress = False
    app.settings = type(
        "SettingsStub",
        (),
        {
            "toggle_start_stop_mac": False,
            "use_alt_shift_hotkey": False,
            "start_stop_key": "DISABLED",
        },
    )()
    return app


class TestStartSimulation(unittest.TestCase):
    def test_start_simulation_requires_valid_process_and_profile(self):
        app = _make_app_stub()
        app.selected_process.set("")
        app.selected_profile.set("Quick")

        self.assertFalse(KeystrokeSimulatorApp._start_simulation(app))

    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.load_profile")
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
        self.assertEqual(
            [e.event_name for e in passed_events], ["Action", "ConditionOnly"]
        )

    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.load_profile")
    def test_start_simulation_accepts_legacy_independent_thread_events(
        self, mock_load_profile, mock_processor_cls
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")

        profile = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(
                    event_name="LegacyIndependent",
                    use_event=True,
                    key_to_enter="A",
                    independent_thread=True,
                )
            ],
            modification_keys={},
        )
        mock_load_profile.return_value = profile
        mock_processor = MagicMock()
        mock_processor_cls.return_value = mock_processor

        result = KeystrokeSimulatorApp._start_simulation(app)

        self.assertTrue(result)
        passed_events = mock_processor_cls.call_args.args[2]
        self.assertEqual([e.event_name for e in passed_events], ["LegacyIndependent"])

    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.load_profile")
    def test_start_simulation_configures_runtime_toggle_session(
        self, mock_load_profile, mock_processor_cls
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")

        profile = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(
                    event_name="Base",
                    use_event=True,
                    key_to_enter="A",
                ),
                EventModel(
                    event_name="Extra",
                    use_event=True,
                    key_to_enter="B",
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=True,
            runtime_toggle_key="F6",
        )
        mock_load_profile.return_value = profile
        mock_processor_cls.return_value = MagicMock()

        result = KeystrokeSimulatorApp._start_simulation(app)

        self.assertTrue(result)
        self.assertTrue(app.runtime_toggle_enabled)
        self.assertEqual(app.runtime_toggle_key, "F6")
        self.assertEqual(app.runtime_toggle_member_count, 1)

    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.load_profile")
    def test_start_simulation_returns_false_when_runtime_toggle_conflicts_with_event_key(
        self, mock_load_profile, mock_processor_cls
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")

        profile = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(event_name="Base", use_event=True, key_to_enter="F6"),
                EventModel(
                    event_name="Extra",
                    use_event=True,
                    key_to_enter="B",
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=True,
            runtime_toggle_key="F6",
        )
        mock_load_profile.return_value = profile

        result = KeystrokeSimulatorApp._start_simulation(app)

        self.assertFalse(result)
        mock_processor_cls.assert_not_called()

    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.PermissionUtils.missing_macos_permissions", return_value=[])
    @patch("app.ui.simulator_app.load_profile")
    def test_readiness_and_start_both_block_runtime_toggle_member_missing_key(
        self, mock_load_profile, _mock_permissions, mock_processor_cls
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")

        profile = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(event_name="Base", use_event=True, key_to_enter="A"),
                EventModel(
                    event_name="Extra",
                    use_event=True,
                    key_to_enter=None,
                    execute_action=True,
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=True,
            runtime_toggle_key="F6",
        )
        mock_load_profile.return_value = profile

        snapshot = KeystrokeSimulatorApp._get_readiness_snapshot(app)
        result = KeystrokeSimulatorApp._start_simulation(app)

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Toggle Conflict")
        self.assertIn("missing an input key", snapshot["detail"])
        self.assertFalse(result)
        mock_processor_cls.assert_not_called()

    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.load_profile")
    def test_start_simulation_keeps_active_mac_polling_thread(
        self, mock_load_profile, mock_processor_cls, _mock_system
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")
        app.ctrl_check_active = True
        app.settings.toggle_start_stop_mac = True
        profile = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(event_name="Base", use_event=True, key_to_enter="A")
            ],
        )
        mock_load_profile.return_value = profile
        mock_processor_cls.return_value = MagicMock()

        result = KeystrokeSimulatorApp._start_simulation(app)

        self.assertTrue(result)
        app._setup_event_handlers.assert_not_called()

    @patch("app.ui.simulator_app.load_profile", side_effect=RuntimeError("boom"))
    def test_start_simulation_returns_false_on_profile_load_error(
        self, _mock_load_profile
    ):
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

    def test_toggle_start_stop_ignores_reentrant_requests(self):
        app = _make_app_stub()
        app.toggle_transition_in_progress = True
        app.start_simulation = MagicMock()
        app.stop_simulation = MagicMock()

        KeystrokeSimulatorApp.toggle_start_stop(app)

        app.start_simulation.assert_not_called()
        app.stop_simulation.assert_not_called()

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

    def test_toggle_runtime_event_group_updates_processor_and_sound(self):
        app = _make_app_stub()
        app.is_running.set(True)
        app.keystroke_processor = MagicMock()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = "F6"

        self.assertTrue(KeystrokeSimulatorApp.toggle_runtime_event_group(app))
        app.keystroke_processor.set_runtime_toggle_active.assert_called_once_with(True)
        app.sound_player.play_runtime_toggle_on_sound.assert_called_once()
        self.assertTrue(app.runtime_toggle_active)

        self.assertTrue(KeystrokeSimulatorApp.toggle_runtime_event_group(app))
        self.assertEqual(
            app.keystroke_processor.set_runtime_toggle_active.call_count, 2
        )
        app.keystroke_processor.set_runtime_toggle_active.assert_called_with(False)
        app.sound_player.play_runtime_toggle_off_sound.assert_called_once()
        self.assertFalse(app.runtime_toggle_active)

    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    def test_stop_simulation_keeps_mac_polling_thread_when_option_shift_enabled(
        self, _mock_system
    ):
        app = _make_app_stub()
        app.keystroke_processor = MagicMock()
        app.ctrl_check_active = True
        app.settings.toggle_start_stop_mac = True

        KeystrokeSimulatorApp._stop_simulation(app)

        app._setup_event_handlers.assert_not_called()


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
        app._get_readiness_snapshot = MagicMock(
            return_value={
                "can_start": not running,
                "badge_text": "Ready",
                "title": "title",
                "detail": "detail",
                "bg": "bg",
                "fg": "fg",
            }
        )
        app._update_main_status = MagicMock()
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

    def test_update_ui_updates_start_button_label_for_running_state(self):
        app = self._make_ui_stub(running=True)

        KeystrokeSimulatorApp._update_ui(app)

        app.button_frame.start_stop_button.config.assert_called_once_with(
            text="Stop",
            state="normal",
        )

    def test_update_ui_disables_start_button_when_not_ready(self):
        app = self._make_ui_stub(running=False)
        app._get_readiness_snapshot.return_value["can_start"] = False

        KeystrokeSimulatorApp._update_ui(app)

        app.button_frame.start_stop_button.config.assert_called_once_with(
            text="Start",
            state="disabled",
        )

    @patch("app.ui.simulator_app.load_profile")
    def test_readiness_snapshot_reports_runtime_toggle_conflict(
        self, mock_load_profile
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")
        profile = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(event_name="SameKey", use_event=True, key_to_enter="F6"),
                EventModel(
                    event_name="Extra",
                    use_event=True,
                    key_to_enter="A",
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=True,
            runtime_toggle_key="F6",
        )
        mock_load_profile.return_value = profile

        snapshot = KeystrokeSimulatorApp._get_readiness_snapshot(app)

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Toggle Conflict")
        self.assertIn("conflicts with event input key", snapshot["detail"])


class TestRuntimeEditGuards(unittest.TestCase):
    @patch("app.ui.simulator_app.KeystrokeQuickEventEditor")
    def test_open_quick_events_noop_when_running(self, mock_editor):
        app = _make_app_stub()
        app.is_running = FakeVar(True)

        KeystrokeSimulatorApp.open_quick_events(app)

        mock_editor.assert_not_called()

    @patch("app.ui.simulator_app.KeystrokeQuickEventEditor")
    def test_open_quick_events_opens_when_stopped(self, mock_editor):
        app = _make_app_stub()
        app.is_running = FakeVar(False)

        KeystrokeSimulatorApp.open_quick_events(app)

        mock_editor.assert_called_once_with(app)


class TestReadinessSnapshotSideEffects(unittest.TestCase):
    @patch("app.ui.simulator_app.PermissionUtils.missing_macos_permissions", return_value=["screen"])
    def test_readiness_snapshot_does_not_modify_profile_file_on_permission_error(
        self, _mock_permissions
    ):
        app = _make_app_stub()

        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            app.profiles_dir = str(prof_dir)
            app.selected_process.set("Dummy Process (1234)")
            app.selected_profile.set("Quick")
            payload = {
                "schema_version": 1,
                "profile": {
                    "name": "Quick",
                    "favorite": False,
                    "modification_keys": None,
                },
                "events": [
                    {"event_name": "  ", "key_to_enter": "X"},
                ],
            }
            path = prof_dir / "Quick.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            before = path.read_text(encoding="utf-8")

            snapshot = KeystrokeSimulatorApp._get_readiness_snapshot(app)

            self.assertEqual(snapshot["badge_text"], "Permissions")
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    @patch("app.ui.simulator_app.ModificationKeysWindow")
    def test_open_modkeys_noop_when_running(self, mock_modkeys):
        app = _make_app_stub()
        app.is_running = FakeVar(True)
        app.selected_profile = FakeVar("Quick")

        KeystrokeSimulatorApp.open_modkeys(app)

        mock_modkeys.assert_not_called()

    @patch("app.ui.simulator_app.ModificationKeysWindow")
    def test_open_modkeys_opens_when_stopped(self, mock_modkeys):
        app = _make_app_stub()
        app.is_running = FakeVar(False)
        app.selected_profile = FakeVar("Quick")

        KeystrokeSimulatorApp.open_modkeys(app)

        mock_modkeys.assert_called_once_with(app, "Quick")

    @patch("app.ui.simulator_app.KeystrokeSettings")
    def test_open_settings_opens_when_missing(self, mock_settings):
        app = _make_app_stub()
        app.settings_window = None
        app.unbind_events = MagicMock()

        KeystrokeSimulatorApp.open_settings(app)

        app.unbind_events.assert_called_once()
        mock_settings.assert_called_once_with(app)
        self.assertEqual(app.settings_window, mock_settings.return_value)


class TestEventHandlerSetup(unittest.TestCase):
    @patch("app.ui.simulator_app.threading.Thread")
    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    @patch("app.ui.simulator_app.pynput.keyboard.Listener")
    def test_setup_event_handlers_uses_mac_polling_without_keyboard_listener(
        self, mock_keyboard_listener, _mock_system, mock_thread
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.settings.toggle_start_stop_mac = True
        app.settings.start_stop_key = "`"
        app.start_stop_mouse_listener = None

        KeystrokeSimulatorApp._setup_event_handlers(app)

        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        mock_keyboard_listener.assert_not_called()

    @patch("app.ui.simulator_app.pynput.mouse.Listener")
    @patch("app.ui.simulator_app.platform.system", return_value="Windows")
    def test_setup_event_handlers_starts_runtime_toggle_mouse_listener_for_wheel(
        self, _mock_system, mock_mouse_listener
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER

        KeystrokeSimulatorApp._setup_event_handlers(app)

        self.assertEqual(mock_mouse_listener.call_count, 1)
        mock_mouse_listener.return_value.start.assert_called_once()

    @patch("app.ui.simulator_app.pynput.mouse.Listener")
    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    @patch("app.ui.simulator_app.threading.Thread")
    def test_setup_event_handlers_keeps_mac_polling_and_runtime_mouse_listener(
        self, mock_thread, _mock_system, mock_mouse_listener
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = MOUSE_BUTTON_3_TRIGGER
        app.settings.toggle_start_stop_mac = True

        KeystrokeSimulatorApp._setup_event_handlers(app)

        mock_thread.assert_called_once()
        mock_mouse_listener.assert_called_once()
        mock_mouse_listener.return_value.start.assert_called_once()

    @patch("app.ui.simulator_app.threading.Thread")
    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    @patch("app.ui.simulator_app.pynput.keyboard.Listener")
    def test_setup_event_handlers_uses_mac_polling_for_runtime_keyboard_trigger_only(
        self, mock_keyboard_listener, _mock_system, mock_thread
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = "Q"
        app.settings.toggle_start_stop_mac = False

        KeystrokeSimulatorApp._setup_event_handlers(app)

        mock_thread.assert_called_once()
        mock_keyboard_listener.assert_not_called()

    def test_open_settings_reuses_existing_window(self):
        app = _make_app_stub()
        existing = MagicMock()
        existing.winfo_exists.return_value = True
        app.settings_window = existing
        app.unbind_events = MagicMock()

        KeystrokeSimulatorApp.open_settings(app)

        app.unbind_events.assert_not_called()
        existing.lift.assert_called_once()
        existing.focus_force.assert_called_once()
        existing.grab_set.assert_called_once()

    @patch("app.ui.simulator_app.KeystrokeSettings")
    def test_open_settings_recreates_stale_window_reference(self, mock_settings):
        app = _make_app_stub()
        stale = MagicMock()
        stale.winfo_exists.return_value = False
        app.settings_window = stale
        app.unbind_events = MagicMock()

        KeystrokeSimulatorApp.open_settings(app)

        app.unbind_events.assert_called_once()
        mock_settings.assert_called_once_with(app)
        self.assertEqual(app.settings_window, mock_settings.return_value)


class TestSaveLatestState(unittest.TestCase):
    @patch("app.ui.simulator_app.StateUtils.save_main_app_state")
    def test_save_latest_state_strips_pid_suffix(self, mock_save_state):
        app = _make_app_stub()
        app.selected_process = FakeVar("SomeProcess (4321)")
        app.selected_profile = FakeVar("Quick")

        KeystrokeSimulatorApp._save_latest_state(app)

        mock_save_state.assert_called_once_with(process="SomeProcess", profile="Quick")


class TestRuntimeToggleMouseHandlers(unittest.TestCase):
    @patch("app.ui.simulator_app.time.time", return_value=100.0)
    def test_runtime_toggle_mouse_scroll_toggles_wheel_up(self, _mock_time):
        app = _make_app_stub()
        app.after = MagicMock()
        app.is_running.set(True)
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER

        KeystrokeSimulatorApp._on_runtime_toggle_mouse_scroll(app, 0, 0, 0, 1)

        app.after.assert_called_once()
        self.assertEqual(app.last_runtime_toggle_time, 100.0)

    @patch("app.ui.simulator_app.time.time", return_value=100.0)
    def test_runtime_toggle_mouse_click_toggles_button_3(self, _mock_time):
        app = _make_app_stub()
        app.after = MagicMock()
        app.is_running.set(True)
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = MOUSE_BUTTON_3_TRIGGER
        button = type("ButtonStub", (), {"name": "x1"})()

        KeystrokeSimulatorApp._on_runtime_toggle_mouse_click(
            app,
            0,
            0,
            button,
            True,
        )

        app.after.assert_called_once()
        self.assertEqual(app.last_runtime_toggle_time, 100.0)

    @patch("app.ui.simulator_app.time.time", return_value=100.1)
    def test_runtime_toggle_mouse_scroll_respects_debounce(self, _mock_time):
        app = _make_app_stub()
        app.after = MagicMock()
        app.is_running.set(True)
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_DOWN_TRIGGER
        app.last_runtime_toggle_time = 100.0

        KeystrokeSimulatorApp._on_runtime_toggle_mouse_scroll(app, 0, 0, 0, -1)

        app.after.assert_not_called()

    @patch("app.ui.simulator_app.time.time", return_value=100.2)
    def test_runtime_toggle_mouse_scroll_ignores_same_scroll_gesture(self, _mock_time):
        app = _make_app_stub()
        app.after = MagicMock()
        app.is_running.set(True)
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER
        app.latest_runtime_scroll_time = 100.0

        KeystrokeSimulatorApp._on_runtime_toggle_mouse_scroll(app, 0, 0, 0, 1)

        app.after.assert_not_called()


class TestRuntimeToggleKeyHandling(unittest.TestCase):
    def test_listener_key_name_uses_vk_for_ime_independent_letters(self):
        key = type("KeyStub", (), {"vk": KeyUtils.get_keycode("Q"), "char": "ㅂ"})()

        self.assertEqual(KeystrokeSimulatorApp._listener_key_name(key), "Q")

    @patch("app.ui.simulator_app.time.time", return_value=100.0)
    def test_on_key_press_matches_runtime_toggle_with_ime_text(self, _mock_time):
        app = _make_app_stub()
        app.after = MagicMock()
        app.is_running.set(True)
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = "Q"
        app.settings.start_stop_key = "DISABLED"
        key = type("KeyStub", (), {"vk": KeyUtils.get_keycode("Q"), "char": "ㅂ"})()

        KeystrokeSimulatorApp._on_key_press(app, key)

        app.after.assert_called_once()
        self.assertEqual(app.last_runtime_toggle_time, 100.0)


class TestMacPollingBehavior(unittest.TestCase):
    @patch("app.ui.simulator_app.KeyUtils.key_pressed", return_value=False)
    @patch("app.ui.simulator_app.KeyUtils.mod_key_pressed", side_effect=[True, True])
    @patch("app.ui.simulator_app.time.sleep", side_effect=RuntimeError("stop"))
    @patch("app.ui.simulator_app.time.time", side_effect=[100.0, 100.0])
    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    def test_mac_polling_does_not_toggle_start_stop_when_disabled(
        self,
        _mock_system,
        _mock_time,
        _mock_sleep,
        _mock_mod_pressed,
        _mock_key_pressed,
    ):
        app = _make_app_stub()
        app.after = MagicMock()
        app.ctrl_check_active = True
        app.settings.toggle_start_stop_mac = False
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = "Q"

        try:
            KeystrokeSimulatorApp._check_for_long_alt_shift(app)
        except RuntimeError:
            pass

        app.after.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
