import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.models import EventModel, ProfileModel
from app.storage.profile_display import QUICK_PROFILE_NAME
from app.ui.main_frames import ProfileFrame
from app.ui.simulator_app import KeystrokeSimulatorApp
from app.utils.keys import KeyUtils
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



class FakeRunSetFrame:
    def __init__(self, names=None, set_id="__current__"):
        self._names = list(names or [])
        self._set_id = set_id
        self.sets_combobox = MagicMock()
        self.edit_button = MagicMock()
        self.copy_button = MagicMock()
        self.del_button = MagicMock()
        self.set_ids = ["__current__"]

    def get_run_profiles(self):
        return list(self._names)

    def get_selected_set_id(self):
        return self._set_id

    def set_selected_set(self, set_id):
        self._set_id = set_id
        return True

    def set_available_profiles(self, names):
        pass

    def load_sets(self, select_id=None):
        if select_id is not None:
            self._set_id = select_id

    def _update_action_states(self):
        pass

    def _refresh_display_value(self):
        pass


def _make_app_stub(run_profiles=None) -> KeystrokeSimulatorApp:
    app = KeystrokeSimulatorApp.__new__(KeystrokeSimulatorApp)
    app.profiles_dir = "profiles"
    app.modkey_sets_path = Path("modkey_sets.json")
    app.run_sets_path = Path("run_sets.json")
    app.selected_process = FakeVar("")
    app.selected_profile = FakeVar("")
    app.selected_modkey_set = FakeVar("Default")
    app.selected_run_set = FakeVar("__current__")
    app.is_running = FakeVar(False)
    app.keystroke_processor = None
    app.terminate_event = MagicMock()
    app.sound_player = MagicMock()
    app._save_latest_state = MagicMock()
    app.update_ui = MagicMock()
    app._update_main_status = MagicMock()
    app._target_process_is_active = MagicMock(return_value=True)
    app.toggle_start_stop = MagicMock()
    app.toggle_runtime_event_group = MagicMock()
    app.setup_event_handlers = MagicMock()
    app.winfo_exists = MagicMock(return_value=True)
    app.bind = MagicMock()
    app.protocol = MagicMock()
    app.unbind_events = MagicMock()
    app.runtime_toggle_enabled = False
    app.runtime_toggle_key = None
    app.runtime_toggle_active = False
    app.runtime_toggle_member_count = 0
    app.runtime_toggle_mouse_listener = None
    app.input_listener_session = MagicMock()

    def _session_add(listener, started=False):
        if not started:
            listener.start()
        return listener

    app.input_listener_session.add.side_effect = _session_add
    app.last_runtime_toggle_time = 0
    app.latest_runtime_scroll_time = None
    app.toggle_transition_in_progress = False
    app._pending_start_stop_toggle = False
    app.ctrl_check_active = False
    app._mac_hotkey_tap_listener = None
    app._mac_key_poll_listener = None
    app.settings = type(
        "SettingsStub",
        (),
        {
            "toggle_start_stop_mac": False,
            "use_alt_shift_hotkey": False,
            "start_stop_key": "DISABLED",
        },
    )()
    app.run_set_frame = FakeRunSetFrame(list(run_profiles or []))
    return app


class TestProfileProtection(unittest.TestCase):
    @patch("app.ui.main_frames.delete_profile_files")
    @patch("app.ui.simulator_app.messagebox.showinfo")
    def test_quick_profile_cannot_be_deleted(
        self, mock_showinfo, mock_delete_profile_files
    ):
        frame = ProfileFrame.__new__(ProfileFrame)
        frame.profile_combobox = MagicMock()
        frame.profile_combobox.current.return_value = -1
        frame.profile_names = []
        frame.selected_profile_var = FakeVar(QUICK_PROFILE_NAME)

        ProfileFrame.delete_profile(frame)

        mock_showinfo.assert_called_once()
        mock_delete_profile_files.assert_not_called()


class TestStartSimulation(unittest.TestCase):
    def test_start_simulation_requires_valid_process_and_profile(self):
        app = _make_app_stub()
        app.selected_process.set("")
        app.selected_profile.set("Quick")

        self.assertFalse(KeystrokeSimulatorApp.start_simulation(app))

    @patch("app.ui.simulator_app.get_modkey_set")
    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.load_profile")
    def test_start_simulation_filters_events_and_starts_processor(
        self, mock_load_profile, mock_processor_cls, mock_get_modkey_set
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")
        app.selected_modkey_set.set("Combat")
        mock_get_modkey_set.return_value = {
            "alt": {"enabled": True, "pass": True, "value": "Pass"}
        }

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
        )
        mock_load_profile.return_value = profile
        mock_processor = MagicMock()
        mock_processor_cls.return_value = mock_processor

        result = KeystrokeSimulatorApp.start_simulation(app)

        self.assertTrue(result)
        app.terminate_event.clear.assert_called_once()
        app._save_latest_state.assert_called_once()
        app.sound_player.play_start_sound.assert_called_once()
        mock_processor.start.assert_called_once()
        mock_get_modkey_set.assert_called_once_with("Combat", app.modkey_sets_path)
        self.assertEqual(
            mock_processor_cls.call_args.args[3], mock_get_modkey_set.return_value
        )

        passed_events = mock_processor_cls.call_args.args[2]
        self.assertEqual(
            [e.event_name for e in passed_events],
            ["Quick/Action", "Quick/ConditionOnly"],
        )

    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.load_profile")
    def test_start_simulation_returns_false_when_processor_has_no_event_data(
        self, mock_load_profile, mock_processor_cls
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")
        profile = ProfileModel(
            name="Quick",
            event_list=[EventModel(event_name="MissingCapture", key_to_enter="A")],
        )
        mock_load_profile.return_value = profile
        mock_processor = MagicMock()
        mock_processor.event_data_list = []
        mock_processor_cls.return_value = mock_processor

        result = KeystrokeSimulatorApp.start_simulation(app)

        self.assertFalse(result)
        mock_processor.start.assert_not_called()
        app.sound_player.play_start_sound.assert_not_called()

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

        result = KeystrokeSimulatorApp.start_simulation(app)

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

        result = KeystrokeSimulatorApp.start_simulation(app)

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
        result = KeystrokeSimulatorApp.start_simulation(app)

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

        result = KeystrokeSimulatorApp.start_simulation(app)

        self.assertTrue(result)
        app.setup_event_handlers.assert_not_called()

    @patch("app.ui.simulator_app.load_profile", side_effect=RuntimeError("boom"))
    def test_start_simulation_returns_false_on_profile_load_error(
        self, _mock_load_profile
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")

        self.assertFalse(KeystrokeSimulatorApp.start_simulation(app))



    @patch("app.ui.simulator_app.get_modkey_set")
    @patch("app.ui.simulator_app.KeystrokeProcessor")
    @patch("app.ui.simulator_app.load_profile")
    def test_start_simulation_merges_multiple_run_profiles(
        self, mock_load_profile, mock_processor_cls, mock_get_modkey_set
    ):
        app = _make_app_stub(run_profiles=["Rot", "Util"])
        app.selected_process.set("Dummy Process (1234)")
        mock_get_modkey_set.return_value = {
            "alt": {"enabled": True, "pass": True, "value": "Pass"}
        }

        def _load(_dir, name, migrate=False):
            return ProfileModel(
                name=name,
                event_list=[
                    EventModel(event_name="Skill", use_event=True, key_to_enter="1"),
                ],
            )

        mock_load_profile.side_effect = _load
        mock_processor_cls.return_value = MagicMock()

        result = KeystrokeSimulatorApp.start_simulation(app)

        self.assertTrue(result)
        self.assertEqual(mock_load_profile.call_count, 2)
        passed = mock_processor_cls.call_args.args[2]
        self.assertEqual(
            [e.event_name for e in passed], ["Rot/Skill", "Util/Skill"]
        )


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

    def test_toggle_start_stop_refreshes_ui_if_start_fails(self):
        app = _make_app_stub()
        app.start_simulation = MagicMock(return_value=False)
        app.stop_simulation = MagicMock()
        app.is_running.set(False)

        KeystrokeSimulatorApp.toggle_start_stop(app)

        self.assertFalse(app.is_running.get())
        app.update_ui.assert_called_once()
        app.stop_simulation.assert_not_called()

    def test_toggle_start_stop_stops_when_running(self):
        app = _make_app_stub()
        app.start_simulation = MagicMock(return_value=True)
        app.stop_simulation = MagicMock()
        app.is_running.set(True)

        KeystrokeSimulatorApp.toggle_start_stop(app)

        self.assertFalse(app.is_running.get())
        app.stop_simulation.assert_called_once()

    def test_toggle_start_stop_queues_reentrant_requests(self):
        app = _make_app_stub()
        app.toggle_transition_in_progress = True
        app.start_simulation = MagicMock()
        app.stop_simulation = MagicMock()
        app.after = MagicMock()

        KeystrokeSimulatorApp.toggle_start_stop(app)

        app.start_simulation.assert_not_called()
        app.stop_simulation.assert_not_called()
        self.assertTrue(app._pending_start_stop_toggle)

    def test_toggle_start_stop_runs_pending_after_transition(self):
        app = _make_app_stub()
        app.is_running.set(False)
        app.start_simulation = MagicMock(return_value=True)
        app.stop_simulation = MagicMock()
        app.after = MagicMock()
        app._pending_start_stop_toggle = True

        KeystrokeSimulatorApp.toggle_start_stop(app)

        self.assertTrue(app.is_running.get())
        self.assertFalse(app._pending_start_stop_toggle)
        app.after.assert_called_once()
        self.assertEqual(app.after.call_args[0][0], 0)

    def test_stop_simulation_stops_processor_and_updates_ui(self):
        app = _make_app_stub()
        processor = MagicMock()
        app.keystroke_processor = processor
        app.winfo_exists.return_value = True

        KeystrokeSimulatorApp.stop_simulation(app)

        processor.stop.assert_called_once()
        app.terminate_event.set.assert_called_once()
        app.sound_player.play_stop_sound.assert_called_once()
        app.update_ui.assert_called_once()
        self.assertIsNone(app.keystroke_processor)

    def test_stop_simulation_skips_ui_update_when_app_is_destroyed(self):
        app = _make_app_stub()
        app.keystroke_processor = MagicMock()
        app.winfo_exists.return_value = False

        KeystrokeSimulatorApp.stop_simulation(app)

        app.sound_player.play_stop_sound.assert_not_called()
        app.update_ui.assert_not_called()

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

        KeystrokeSimulatorApp.stop_simulation(app)

        app.setup_event_handlers.assert_not_called()


class TestMainUiState(unittest.TestCase):
    def _make_ui_stub(self, running: bool) -> KeystrokeSimulatorApp:
        app = _make_app_stub()
        app.is_running = FakeVar(running)

        app.process_frame = MagicMock()
        app.process_frame.process_combobox = MagicMock()
        app.process_frame.refresh_button = MagicMock()

        app.profile_frame = MagicMock()
        app.profile_frame.profile_combobox = MagicMock()
        app.profile_frame.edit_button = MagicMock()
        app.profile_frame.copy_button = MagicMock()
        app.profile_frame.del_button = MagicMock()
        app.profile_frame.sort_button = MagicMock()

        app.modkey_set_frame = MagicMock()
        app.modkey_set_frame.sets_combobox = MagicMock()
        app.modkey_set_frame.edit_button = MagicMock()
        app.modkey_set_frame.copy_button = MagicMock()
        app.modkey_set_frame.del_button = MagicMock()

        app.button_frame = MagicMock()
        app.run_start_button = MagicMock()
        app.button_frame.quick_events_button = MagicMock()
        app.button_frame.settings_button = MagicMock()
        app.button_frame.clear_logs_button = MagicMock()

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

    def test_update_ui_disables_quick_events_and_modkey_set_when_running(self):
        app = self._make_ui_stub(running=True)

        KeystrokeSimulatorApp.update_ui(app)

        app.button_frame.quick_events_button.config.assert_called_once_with(
            state="disabled"
        )
        app.modkey_set_frame.sets_combobox.config.assert_called_once_with(
            state="disabled"
        )
        app.modkey_set_frame.edit_button.config.assert_called_once_with(
            state="disabled"
        )
        app.profile_frame.edit_button.config.assert_called_once_with(state="disabled")
        app.profile_frame.sort_button.config.assert_called_once_with(state="disabled")

    def test_update_ui_enables_quick_events_and_modkey_set_when_stopped(self):
        app = self._make_ui_stub(running=False)

        KeystrokeSimulatorApp.update_ui(app)

        app.button_frame.quick_events_button.config.assert_called_once_with(
            state="normal"
        )
        app.modkey_set_frame.edit_button.config.assert_called_once_with(state="normal")
        app.profile_frame.edit_button.config.assert_called_once_with(state="normal")
        app.profile_frame.sort_button.config.assert_called_once_with(state="normal")

    def test_update_ui_updates_start_button_label_for_running_state(self):
        app = self._make_ui_stub(running=True)

        KeystrokeSimulatorApp.update_ui(app)

        app.run_start_button.config.assert_called_once_with(
            text="Stop",
            state="normal",
        )

    def test_update_ui_disables_start_button_when_not_ready(self):
        app = self._make_ui_stub(running=False)
        app._get_readiness_snapshot.return_value["can_start"] = False

        KeystrokeSimulatorApp.update_ui(app)

        app.run_start_button.config.assert_called_once_with(
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

    @patch("app.ui.simulator_app.PermissionUtils.missing_macos_permissions", return_value=[])
    @patch("app.ui.simulator_app.load_profile")
    def test_readiness_snapshot_blocks_missing_capture_data(
        self, mock_load_profile, _mock_permissions
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")
        mock_load_profile.return_value = ProfileModel(
            name="Quick",
            event_list=[EventModel(event_name="MissingCapture", key_to_enter="A")],
        )

        snapshot = KeystrokeSimulatorApp._get_readiness_snapshot(app)

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Check Events")
        self.assertIn("captured coordinates", snapshot["title"])

    @patch("app.ui.simulator_app.PermissionUtils.missing_macos_permissions", return_value=[])
    @patch("app.ui.simulator_app.load_profile")
    def test_readiness_snapshot_blocks_region_without_reference_image(
        self, mock_load_profile, _mock_permissions
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")
        mock_load_profile.return_value = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(
                    event_name="MissingReference",
                    key_to_enter="A",
                    latest_position=(10, 10),
                    clicked_position=(10, 10),
                    match_mode="region",
                    region_size=(20, 20),
                    held_screenshot=None,
                )
            ],
        )

        snapshot = KeystrokeSimulatorApp._get_readiness_snapshot(app)

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Check Events")
        self.assertIn("reference data", snapshot["title"])

    @patch("app.ui.simulator_app.PermissionUtils.missing_macos_permissions", return_value=[])
    @patch("app.ui.simulator_app.load_profile")
    def test_readiness_snapshot_allows_screenless_input_with_conditions(
        self, mock_load_profile, _mock_permissions
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")
        mock_load_profile.return_value = ProfileModel(
            name="Quick",
            event_list=[
                EventModel(
                    event_name="Gate",
                    execute_action=False,
                    latest_position=(10, 10),
                    clicked_position=(1, 1),
                    ref_pixel_value=(1, 2, 3),
                ),
                EventModel(
                    event_name="Fire",
                    key_to_enter="A",
                    conditions={"Gate": True},
                ),
            ],
        )

        snapshot = KeystrokeSimulatorApp._get_readiness_snapshot(app)

        self.assertTrue(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Ready")


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

        mock_editor.assert_called_once_with(
            app,
            profiles_dir=app.profiles_dir,
            on_close=app.update_ui,
        )


class TestReadinessSnapshotSideEffects(unittest.TestCase):
    @patch("app.ui.simulator_app.PermissionUtils.missing_macos_permissions", return_value=["screen"])
    def test_readiness_snapshot_does_not_modify_profile_file_on_permission_error(
        self, _mock_permissions
    ):
        app = _make_app_stub()

        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            app.profiles_dir = prof_dir
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
        app.selected_modkey_set = FakeVar("Default")

        KeystrokeSimulatorApp.open_modkeys(app)

        mock_modkeys.assert_not_called()

    @patch("app.ui.simulator_app.ModificationKeysWindow")
    def test_open_modkeys_opens_when_stopped(self, mock_modkeys):
        app = _make_app_stub()
        app.is_running = FakeVar(False)
        app.selected_modkey_set = FakeVar("Combat")

        KeystrokeSimulatorApp.open_modkeys(app)

        mock_modkeys.assert_called_once_with(
            app, "Combat", sets_path=app.modkey_sets_path
        )

    @patch("app.ui.simulator_app.ModificationKeysWindow")
    def test_open_modkeys_refreshes_status_after_close(self, mock_modkeys):
        app = _make_app_stub()
        app.is_running = FakeVar(False)
        app.selected_modkey_set = FakeVar("Default")

        KeystrokeSimulatorApp.open_modkeys(app)

        app._update_main_status.assert_called()

    def test_status_detail_appends_selection_once(self):
        app = _make_app_stub()
        app.selected_profile = FakeVar("Dungeon")
        app.selected_modkey_set = FakeVar("Combat")

        first = KeystrokeSimulatorApp._status_detail_with_selection(
            app, "Pick a process."
        )
        self.assertIn("Dungeon", first)
        self.assertIn("Combat", first)
        self.assertIn("ModKey", first)
        self.assertIn("Current profile", first)

        second = KeystrokeSimulatorApp._status_detail_with_selection(app, first)
        self.assertEqual(second, first)

    def test_status_detail_skips_when_no_selection(self):
        app = _make_app_stub()
        app.selected_profile = FakeVar("")
        app.selected_modkey_set = FakeVar("")
        detail = KeystrokeSimulatorApp._status_detail_with_selection(
            app, "Nothing selected."
        )
        self.assertEqual(detail, "Nothing selected.")

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
    @patch("app.ui.simulator_app.MacKeyPollListener")
    @patch("app.ui.simulator_app.MacHotkeyTapListener")
    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    @patch("app.ui.simulator_app.pynput.keyboard.Listener")
    def test_setup_event_handlers_uses_mac_tap_without_keyboard_listener(
        self, mock_keyboard_listener, _mock_system, mock_mac_tap, mock_mac_poll
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.settings.toggle_start_stop_mac = True
        app.settings.start_stop_key = "`"
        app.start_stop_mouse_listener = None
        tap = MagicMock()
        tap.is_active = True
        mock_mac_tap.return_value = tap

        KeystrokeSimulatorApp.setup_event_handlers(app)

        self.assertTrue(app.ctrl_check_active)
        mock_mac_tap.assert_called_once()
        tap.start.assert_called_once()
        app.input_listener_session.add.assert_called()
        app.input_listener_session.begin_responsiveness.assert_called_once()
        mock_mac_poll.assert_not_called()
        mock_keyboard_listener.assert_not_called()

    @patch("app.ui.simulator_app.MacKeyPollListener")
    @patch("app.ui.simulator_app.MacHotkeyTapListener")
    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    def test_setup_event_handlers_falls_back_to_poll_when_tap_inactive(
        self, _mock_system, mock_mac_tap, mock_mac_poll
    ):
        app = _make_app_stub()
        app.settings.toggle_start_stop_mac = True
        tap = MagicMock()
        tap.is_active = False
        mock_mac_tap.return_value = tap
        mock_mac_poll.return_value = MagicMock()

        KeystrokeSimulatorApp.setup_event_handlers(app)

        self.assertTrue(app.ctrl_check_active)
        tap.start.assert_called_once()
        tap.stop.assert_called_once()
        mock_mac_poll.assert_called_once()

    @patch("app.ui.simulator_app.pynput.mouse.Listener")
    @patch("app.ui.simulator_app.platform.system", return_value="Windows")
    def test_setup_event_handlers_starts_runtime_toggle_mouse_listener_for_wheel(
        self, _mock_system, mock_mouse_listener
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER

        KeystrokeSimulatorApp.setup_event_handlers(app)

        self.assertEqual(mock_mouse_listener.call_count, 1)
        mock_mouse_listener.return_value.start.assert_called_once()

    @patch("app.ui.simulator_app.MacKeyPollListener")
    @patch("app.ui.simulator_app.MacHotkeyTapListener")
    @patch("app.ui.simulator_app.pynput.mouse.Listener")
    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    def test_setup_event_handlers_keeps_mac_tap_and_runtime_mouse_listener(
        self, _mock_system, mock_mouse_listener, mock_mac_tap, mock_mac_poll
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = MOUSE_BUTTON_3_TRIGGER
        app.settings.toggle_start_stop_mac = True
        tap = MagicMock()
        tap.is_active = True
        mock_mac_tap.return_value = tap

        KeystrokeSimulatorApp.setup_event_handlers(app)

        self.assertTrue(app.ctrl_check_active)
        mock_mac_tap.assert_called_once()
        mock_mac_poll.assert_not_called()
        mock_mouse_listener.assert_called_once()
        mock_mouse_listener.return_value.start.assert_called_once()

    @patch("app.ui.simulator_app.MacKeyPollListener")
    @patch("app.ui.simulator_app.MacHotkeyTapListener")
    @patch("app.ui.simulator_app.platform.system", return_value="Darwin")
    @patch("app.ui.simulator_app.pynput.keyboard.Listener")
    def test_setup_event_handlers_uses_mac_tap_for_runtime_keyboard_trigger_only(
        self, mock_keyboard_listener, _mock_system, mock_mac_tap, mock_mac_poll
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = "Q"
        app.settings.toggle_start_stop_mac = False
        tap = MagicMock()
        tap.is_active = True
        mock_mac_tap.return_value = tap

        KeystrokeSimulatorApp.setup_event_handlers(app)

        self.assertTrue(app.ctrl_check_active)
        mock_mac_tap.assert_called_once()
        mock_mac_poll.assert_not_called()
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

        mock_save_state.assert_called_once_with(
            process="SomeProcess",
            profile="Quick",
            run_set="__current__",
            modkey_set="Default",
        )


class TestRuntimeToggleMouseHandlers(unittest.TestCase):
    @patch("app.ui.simulator_app.time.time", return_value=100.0)
    def test_runtime_toggle_mouse_scroll_toggles_wheel_up(self, _mock_time):
        app = _make_app_stub()
        app.after = MagicMock()
        app.is_running.set(True)
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER

        KeystrokeSimulatorApp._on_runtime_toggle_mouse_scroll(app, 0, 0, 0, 1)

        app.toggle_runtime_event_group.assert_called_once()
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

        app.toggle_runtime_event_group.assert_called_once()
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

        app.toggle_runtime_event_group.assert_not_called()

    @patch("app.ui.simulator_app.time.time", return_value=100.2)
    def test_runtime_toggle_mouse_scroll_ignores_same_scroll_gesture(self, _mock_time):
        app = _make_app_stub()
        app.after = MagicMock()
        app.is_running.set(True)
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER
        app.latest_runtime_scroll_time = 100.0

        KeystrokeSimulatorApp._on_runtime_toggle_mouse_scroll(app, 0, 0, 0, 1)

        app.toggle_runtime_event_group.assert_not_called()


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

        app.toggle_runtime_event_group.assert_called_once()
        self.assertEqual(app.last_runtime_toggle_time, 100.0)


class TestMacKeyPollListener(unittest.TestCase):
    def _make_listener(self, **kwargs):
        from app.ui.mac_key_poll import MacKeyPollListener

        session = MagicMock()
        posted: list = []
        session.post.side_effect = lambda action: posted.append(action)
        start_stop = MagicMock()
        runtime = MagicMock()
        listener = MacKeyPollListener(
            session,
            interval_ms=10,
            hold_seconds=0.015,
            debounce_seconds=0.2,
            runtime_debounce_seconds=0.25,
            start_stop_enabled=kwargs.get("start_stop_enabled", lambda: True),
            runtime_toggle_enabled=kwargs.get("runtime_toggle_enabled", lambda: False),
            runtime_key_provider=kwargs.get("runtime_key_provider", lambda: None),
            on_start_stop=start_stop,
            on_runtime_toggle=runtime,
        )
        return listener, session, posted, start_stop, runtime

    def test_requires_hold_duration_before_posting_start_stop(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.ui.mac_key_poll.KeyUtils.key_pressed", return_value=False):
            with patch("app.ui.mac_key_poll.time.time", return_value=100.0):
                listener._tick()
            self.assertEqual(posted, [])

            with patch("app.ui.mac_key_poll.time.time", return_value=100.01):
                listener._tick()
            self.assertEqual(posted, [])

            with patch("app.ui.mac_key_poll.time.time", return_value=100.02):
                listener._tick()

        self.assertEqual(len(posted), 1)
        posted[0]()
        start_stop.assert_called_once()
        self.assertTrue(listener._latched)

    def test_disabled_start_stop_never_posts(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make_listener(
            start_stop_enabled=lambda: False
        )
        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.ui.mac_key_poll.time.time", return_value=100.0):
            listener._tick()
        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.ui.mac_key_poll.time.time", return_value=100.05):
            listener._tick()
        self.assertEqual(posted, [])
        start_stop.assert_not_called()

    def test_partial_release_rearms_chord_for_next_press(self) -> None:
        """Either key up breaks the chord and must allow the next Option+Shift."""
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.ui.mac_key_poll.time.time", return_value=100.0):
                listener._tick()
            with patch("app.ui.mac_key_poll.time.time", return_value=100.04):
                listener._tick()
        self.assertEqual(len(posted), 1)

        def only_option(key: str, **_kwargs: object) -> bool:
            return key == "alt"

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", side_effect=only_option
        ), patch("app.ui.mac_key_poll.time.time", return_value=100.5):
            listener._tick()
        self.assertFalse(listener._latched)

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.ui.mac_key_poll.time.time", return_value=101.0):
                listener._tick()
            with patch("app.ui.mac_key_poll.time.time", return_value=101.04):
                listener._tick()
        self.assertEqual(len(posted), 2)
        posted[0]()
        posted[1]()
        self.assertEqual(start_stop.call_count, 2)

    def test_uses_physical_only_mod_query(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make_listener()
        calls: list[tuple] = []

        def track(key: str, **kwargs: object) -> bool:
            calls.append((key, kwargs.get("physical_only")))
            return True

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", side_effect=track
        ), patch("app.ui.mac_key_poll.time.time", return_value=100.0):
            listener._tick()
        self.assertEqual(calls[0], ("alt", True))
        self.assertEqual(calls[1], ("shift", True))

    def test_full_release_rearms_for_next_chord(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.ui.mac_key_poll.time.time", return_value=100.0):
                listener._tick()
            with patch("app.ui.mac_key_poll.time.time", return_value=100.04):
                listener._tick()

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=False
        ), patch("app.ui.mac_key_poll.time.time", return_value=100.5):
            listener._tick()
        self.assertFalse(listener._latched)

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.ui.mac_key_poll.time.time", return_value=101.0):
                listener._tick()
            with patch("app.ui.mac_key_poll.time.time", return_value=101.04):
                listener._tick()

        self.assertEqual(len(posted), 2)
        posted[0]()
        posted[1]()
        self.assertEqual(start_stop.call_count, 2)

    def test_debounce_blocks_rapid_rearm(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.ui.mac_key_poll.time.time", return_value=100.0):
                listener._tick()
            with patch("app.ui.mac_key_poll.time.time", return_value=100.04):
                listener._tick()

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=False
        ), patch("app.ui.mac_key_poll.time.time", return_value=100.05):
            listener._tick()

        # Re-arm attempt still inside 0.2s debounce from first fire at 100.04.
        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.ui.mac_key_poll.time.time", return_value=100.10):
                listener._tick()
            with patch("app.ui.mac_key_poll.time.time", return_value=100.20):
                listener._tick()
        self.assertEqual(len(posted), 1)

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.ui.mac_key_poll.time.time", return_value=100.30):
                listener._tick()
            with patch("app.ui.mac_key_poll.time.time", return_value=100.34):
                listener._tick()
        self.assertEqual(len(posted), 2)
        posted[0]()
        posted[1]()
        self.assertEqual(start_stop.call_count, 2)

    def test_does_not_flood_queue_while_chord_held(self) -> None:
        """Regression: continuous samples must not enqueue every poll tick."""
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.ui.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            t = 100.0
            for _ in range(40):
                with patch("app.ui.mac_key_poll.time.time", return_value=t):
                    listener._tick()
                t += 0.015

        # One fire after hold, then latched: no further posts while still held.
        self.assertEqual(len(posted), 1)
        posted[0]()
        start_stop.assert_called_once()

    def test_listener_stop_joins_thread(self) -> None:
        from app.ui.mac_key_poll import MacKeyPollListener

        session = MagicMock()
        session.post = MagicMock()
        listener = MacKeyPollListener(
            session,
            interval_ms=50,
            start_stop_enabled=lambda: False,
            on_start_stop=lambda: None,
        )
        listener.start()
        self.assertIsNotNone(listener._thread)
        self.assertTrue(listener._thread.is_alive())
        listener.stop()
        self.assertIsNone(listener._thread)


class TestMacModKeyPressed(unittest.TestCase):
    @patch("app.utils.keys.IS_MAC", True)
    @patch("app.utils.keys.IS_WIN", False)
    def test_mod_key_pressed_uses_left_or_right_physical_codes(self):
        calls: list[int] = []

        def fake_symbol(name: str):
            if name == "CGEventSourceKeyState":
                def key_state(_hid: object, code: int) -> bool:
                    calls.append(code)
                    return code == 61  # right Option

                return key_state
            if name == "kCGEventSourceStateHIDSystemState":
                return "HID"
            # Flag fallback symbols should not be needed when key-state hits.
            return 0

        with patch("app.utils.keys.quartz_symbol", side_effect=fake_symbol):
            self.assertTrue(KeyUtils.mod_key_pressed("alt"))
        self.assertIn(58, calls)
        self.assertIn(61, calls)

    @patch("app.utils.keys.IS_MAC", True)
    @patch("app.utils.keys.IS_WIN", False)
    def test_physical_only_skips_sticky_flag_fallback(self):
        def fake_symbol(name: str):
            if name == "CGEventSourceKeyState":
                return lambda _hid, _code: False
            if name == "kCGEventSourceStateHIDSystemState":
                return "HID"
            if name == "CGEventSourceFlagsState":
                return lambda _hid: 0xFFFFFFFF  # all flags set
            return 1

        with patch("app.utils.keys.quartz_symbol", side_effect=fake_symbol):
            self.assertFalse(KeyUtils.mod_key_pressed("shift", physical_only=True))
            self.assertTrue(KeyUtils.mod_key_pressed("shift", physical_only=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
