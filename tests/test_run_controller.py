import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.domain.models import EventModel, ProfileModel
from app.domain.runtime_toggle import (
    MOUSE_BUTTON_3_TRIGGER,
    WHEEL_DOWN_TRIGGER,
    WHEEL_UP_TRIGGER,
    normalize_runtime_toggle_listener_key,
)
from app.platform.keys import KeyUtils
from app.presenters.run_controller import RunController, RunSelection
from app.storage.profile_storage import save_profile
from app.storage.run_sets_storage import upsert_run_set


class FakeVar:
    def __init__(self, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _make_app_stub(run_profiles=None) -> RunController:
    """Controller with a fake host. Selection lives on FakeVars set on the stub."""
    host = MagicMock()
    host.window_position.return_value = None
    host.is_alive.return_value = True
    router = MagicMock()

    def _router_add(listener, started=False):
        if not started:
            listener.start()
        return listener

    router.add.side_effect = _router_add
    app = RunController(
        host,
        router=router,
        sound_player=MagicMock(),
        profiles_dir=Path("profiles"),
        modkey_sets_path=Path("modkey_sets.json"),
        run_sets_path=Path("run_sets.json"),
    )
    app.selected_process = FakeVar("")
    app.selected_profile = FakeVar("")
    app.selected_modkey_set = FakeVar("Default")
    app.selected_run_set = FakeVar("__current__")
    host.selection.side_effect = lambda: RunSelection(
        process=app.selected_process.get(),
        profile=app.selected_profile.get(),
        run_set=app.selected_run_set.get(),
        modkey_set=app.selected_modkey_set.get(),
    )
    if run_profiles:
        app.run_profile_names = MagicMock(return_value=list(run_profiles))
    app.terminate_event = MagicMock()
    app.save_state = MagicMock()
    app._target_process_is_active = MagicMock(return_value=True)
    app.toggle_start_stop = MagicMock()
    app.toggle_runtime_event_group = MagicMock()
    app.setup_event_handlers = MagicMock()
    app.settings = type(
        "SettingsStub",
        (),
        {
            "toggle_start_stop_mac": False,
            "use_alt_shift_hotkey": False,
            "start_stop_key": "DISABLED",
            "runtime_toggle_sound_enabled": True,
        },
    )()
    return app


class TestStartSimulation(unittest.TestCase):
    def test_start_simulation_requires_valid_process_and_profile(self):
        app = _make_app_stub()
        app.selected_process.set("")
        app.selected_profile.set("Quick")

        self.assertFalse(RunController.start_simulation(app))

    @patch("app.presenters.run_controller.get_modkey_set")
    @patch("app.presenters.run_controller.KeystrokeProcessor")
    @patch("app.presenters.run_controller.load_profile")
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

        result = RunController.start_simulation(app)

        self.assertTrue(result)
        app.terminate_event.clear.assert_called_once()
        app.save_state.assert_called_once()
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

    @patch("app.presenters.run_controller.KeystrokeProcessor")
    @patch("app.presenters.run_controller.load_profile")
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

        result = RunController.start_simulation(app)

        self.assertFalse(result)
        mock_processor.start.assert_not_called()
        app.sound_player.play_start_sound.assert_not_called()

    @patch("app.presenters.run_controller.KeystrokeProcessor")
    @patch("app.presenters.run_controller.load_profile")
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

        result = RunController.start_simulation(app)

        self.assertTrue(result)
        self.assertTrue(app.runtime_toggle_enabled)
        self.assertEqual(app.runtime_toggle_key, "F6")
        self.assertEqual(app.runtime_toggle_member_count, 1)

    @patch("app.presenters.run_controller.KeystrokeProcessor")
    @patch("app.presenters.run_controller.load_profile")
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

        result = RunController.start_simulation(app)

        self.assertFalse(result)
        mock_processor_cls.assert_not_called()

    @patch("app.presenters.run_controller.KeystrokeProcessor")
    @patch("app.presenters.run_controller.PermissionUtils.missing_macos_permissions", return_value=[])
    @patch("app.presenters.run_controller.load_profile")
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

        snapshot = RunController.readiness(app)
        result = RunController.start_simulation(app)

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Hotkey Conflict")
        self.assertIn("missing an input key", snapshot["detail"])
        self.assertFalse(result)
        mock_processor_cls.assert_not_called()

    @patch("app.presenters.run_controller.platform.system", return_value="Darwin")
    @patch("app.presenters.run_controller.KeystrokeProcessor")
    @patch("app.presenters.run_controller.load_profile")
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

        result = RunController.start_simulation(app)

        self.assertTrue(result)
        app.setup_event_handlers.assert_not_called()

    @patch("app.presenters.run_controller.load_profile", side_effect=RuntimeError("boom"))
    def test_start_simulation_returns_false_on_profile_load_error(
        self, _mock_load_profile
    ):
        app = _make_app_stub()
        app.selected_process.set("Dummy Process (1234)")
        app.selected_profile.set("Quick")

        self.assertFalse(RunController.start_simulation(app))



    @patch("app.presenters.run_controller.get_modkey_set")
    @patch("app.presenters.run_controller.KeystrokeProcessor")
    @patch("app.presenters.run_controller.load_profile")
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

        result = RunController.start_simulation(app)

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
        app.is_running = False

        RunController.toggle_start_stop(app)

        self.assertTrue(app.is_running)
        app.host.on_run_state_changed.assert_called_once()
        app.stop_simulation.assert_not_called()

    def test_toggle_start_stop_refreshes_ui_if_start_fails(self):
        app = _make_app_stub()
        app.start_simulation = MagicMock(return_value=False)
        app.stop_simulation = MagicMock()
        app.is_running = False

        RunController.toggle_start_stop(app)

        self.assertFalse(app.is_running)
        app.host.on_run_state_changed.assert_called_once()
        app.stop_simulation.assert_not_called()

    def test_toggle_start_stop_stops_when_running(self):
        app = _make_app_stub()
        app.start_simulation = MagicMock(return_value=True)
        app.stop_simulation = MagicMock()
        app.is_running = True

        RunController.toggle_start_stop(app)

        self.assertFalse(app.is_running)
        app.stop_simulation.assert_called_once()

    def test_toggle_start_stop_queues_reentrant_requests(self):
        app = _make_app_stub()
        app.toggle_transition_in_progress = True
        app.start_simulation = MagicMock()
        app.stop_simulation = MagicMock()

        RunController.toggle_start_stop(app)

        app.start_simulation.assert_not_called()
        app.stop_simulation.assert_not_called()
        self.assertTrue(app._pending_start_stop_toggle)

    def test_toggle_start_stop_runs_pending_after_transition(self):
        app = _make_app_stub()
        app.is_running = False
        app.start_simulation = MagicMock(return_value=True)
        app.stop_simulation = MagicMock()
        app._pending_start_stop_toggle = True

        RunController.toggle_start_stop(app)

        self.assertTrue(app.is_running)
        self.assertFalse(app._pending_start_stop_toggle)
        app.host.defer.assert_called_once_with(app.toggle_start_stop)

    def test_stop_simulation_stops_processor_and_updates_ui(self):
        app = _make_app_stub()
        processor = MagicMock()
        app.keystroke_processor = processor
        app.host.is_alive.return_value = True

        RunController.stop_simulation(app)

        processor.stop.assert_called_once()
        app.terminate_event.set.assert_called_once()
        app.sound_player.play_stop_sound.assert_called_once()
        app.host.on_run_state_changed.assert_called_once()
        self.assertIsNone(app.keystroke_processor)

    def test_stop_simulation_skips_ui_update_when_app_is_destroyed(self):
        app = _make_app_stub()
        app.keystroke_processor = MagicMock()
        app.host.is_alive.return_value = False

        RunController.stop_simulation(app)

        app.sound_player.play_stop_sound.assert_not_called()
        app.host.on_run_state_changed.assert_not_called()

    def test_toggle_runtime_event_group_updates_processor_and_sound(self):
        app = _make_app_stub()
        app.is_running = True
        app.keystroke_processor = MagicMock()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = "F6"

        self.assertTrue(RunController.toggle_runtime_event_group(app))
        app.keystroke_processor.set_runtime_toggle_active.assert_called_once_with(True)
        app.sound_player.play_runtime_toggle_on_sound.assert_called_once()
        self.assertTrue(app.runtime_toggle_active)

        self.assertTrue(RunController.toggle_runtime_event_group(app))
        self.assertEqual(
            app.keystroke_processor.set_runtime_toggle_active.call_count, 2
        )
        app.keystroke_processor.set_runtime_toggle_active.assert_called_with(False)
        app.sound_player.play_runtime_toggle_off_sound.assert_called_once()
        self.assertFalse(app.runtime_toggle_active)

    def test_toggle_runtime_event_group_skips_sound_when_disabled(self):
        app = _make_app_stub()
        app.is_running = True
        app.keystroke_processor = MagicMock()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = "F6"
        app.settings.runtime_toggle_sound_enabled = False

        self.assertTrue(RunController.toggle_runtime_event_group(app))
        app.keystroke_processor.set_runtime_toggle_active.assert_called_once_with(True)
        app.sound_player.play_runtime_toggle_on_sound.assert_not_called()
        self.assertTrue(app.runtime_toggle_active)

    @patch("app.presenters.run_controller.platform.system", return_value="Darwin")
    def test_stop_simulation_keeps_mac_polling_thread_when_option_shift_enabled(
        self, _mock_system
    ):
        app = _make_app_stub()
        app.keystroke_processor = MagicMock()
        app.ctrl_check_active = True
        app.settings.toggle_start_stop_mac = True

        RunController.stop_simulation(app)

        app.setup_event_handlers.assert_not_called()




class TestReadiness(unittest.TestCase):
    @patch("app.presenters.run_controller.load_profile")
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

        snapshot = RunController.readiness(app)

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Hotkey Conflict")
        self.assertIn("conflicts with event input key", snapshot["detail"])

    @patch("app.presenters.run_controller.PermissionUtils.missing_macos_permissions", return_value=[])
    @patch("app.presenters.run_controller.load_profile")
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

        snapshot = RunController.readiness(app)

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Check Events")
        self.assertIn("captured coordinates", snapshot["title"])

    @patch("app.presenters.run_controller.PermissionUtils.missing_macos_permissions", return_value=[])
    @patch("app.presenters.run_controller.load_profile")
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

        snapshot = RunController.readiness(app)

        self.assertFalse(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Check Events")
        self.assertIn("reference data", snapshot["title"])

    @patch("app.presenters.run_controller.PermissionUtils.missing_macos_permissions", return_value=[])
    @patch("app.presenters.run_controller.load_profile")
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

        snapshot = RunController.readiness(app)

        self.assertTrue(snapshot["can_start"])
        self.assertEqual(snapshot["badge_text"], "Ready")

    @patch("app.presenters.run_controller.PermissionUtils.missing_macos_permissions", return_value=["screen"])
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

            snapshot = RunController.readiness(app)

            self.assertEqual(snapshot["badge_text"], "Permissions")
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_status_detail_appends_selection_once(self):
        app = _make_app_stub()
        app.selected_profile = FakeVar("Dungeon")
        app.selected_modkey_set = FakeVar("Combat")

        first = RunController.status_detail_with_selection(
            app, "Pick a process."
        )
        self.assertIn("Dungeon", first)
        self.assertIn("Combat", first)
        self.assertIn("Modifier keys", first)
        self.assertIn("Run Dungeon", first)

        second = RunController.status_detail_with_selection(app, first)
        self.assertEqual(second, first)

    def test_status_detail_skips_when_no_selection(self):
        app = _make_app_stub()
        app.selected_profile = FakeVar("")
        app.selected_modkey_set = FakeVar("")
        detail = RunController.status_detail_with_selection(
            app, "Nothing selected."
        )
        self.assertEqual(detail, "Nothing selected.")

    def test_start_simulation_closes_open_quick_hud(self):
        app = _make_app_stub()
        RunController.start_simulation(app)

        app.host.before_start.assert_called_once()


class TestEventHandlerSetup(unittest.TestCase):
    @patch("app.presenters.run_controller.MacKeyPollListener")
    @patch("app.presenters.run_controller.MacHotkeyTapListener")
    @patch("app.presenters.run_controller.platform.system", return_value="Darwin")
    @patch("app.presenters.run_controller.pynput.keyboard.Listener")
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

        RunController.setup_event_handlers(app)

        self.assertTrue(app.ctrl_check_active)
        mock_mac_tap.assert_called_once()
        tap.start.assert_called_once()
        app.router.add.assert_called()
        app.router.begin_responsiveness.assert_called_once()
        mock_mac_poll.assert_not_called()
        mock_keyboard_listener.assert_not_called()

    @patch("app.presenters.run_controller.MacKeyPollListener")
    @patch("app.presenters.run_controller.MacHotkeyTapListener")
    @patch("app.presenters.run_controller.platform.system", return_value="Darwin")
    def test_setup_event_handlers_falls_back_to_poll_when_tap_inactive(
        self, _mock_system, mock_mac_tap, mock_mac_poll
    ):
        app = _make_app_stub()
        app.settings.toggle_start_stop_mac = True
        tap = MagicMock()
        tap.is_active = False
        mock_mac_tap.return_value = tap
        mock_mac_poll.return_value = MagicMock()

        RunController.setup_event_handlers(app)

        self.assertTrue(app.ctrl_check_active)
        tap.start.assert_called_once()
        tap.stop.assert_called_once()
        mock_mac_poll.assert_called_once()

    @patch("app.presenters.run_controller.pynput.mouse.Listener")
    @patch("app.presenters.run_controller.platform.system", return_value="Windows")
    def test_setup_event_handlers_starts_runtime_toggle_mouse_listener_for_wheel(
        self, _mock_system, mock_mouse_listener
    ):
        app = _make_app_stub()
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER

        RunController.setup_event_handlers(app)

        self.assertEqual(mock_mouse_listener.call_count, 1)
        mock_mouse_listener.return_value.start.assert_called_once()

    @patch("app.presenters.run_controller.MacKeyPollListener")
    @patch("app.presenters.run_controller.MacHotkeyTapListener")
    @patch("app.presenters.run_controller.pynput.mouse.Listener")
    @patch("app.presenters.run_controller.platform.system", return_value="Darwin")
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

        RunController.setup_event_handlers(app)

        self.assertTrue(app.ctrl_check_active)
        mock_mac_tap.assert_called_once()
        mock_mac_poll.assert_not_called()
        mock_mouse_listener.assert_called_once()
        mock_mouse_listener.return_value.start.assert_called_once()

    @patch("app.presenters.run_controller.MacKeyPollListener")
    @patch("app.presenters.run_controller.MacHotkeyTapListener")
    @patch("app.presenters.run_controller.platform.system", return_value="Darwin")
    @patch("app.presenters.run_controller.pynput.keyboard.Listener")
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

        RunController.setup_event_handlers(app)

        self.assertTrue(app.ctrl_check_active)
        mock_mac_tap.assert_called_once()
        mock_mac_poll.assert_not_called()
        mock_keyboard_listener.assert_not_called()


class TestSaveState(unittest.TestCase):
    @patch("app.presenters.run_controller.StateUtils.save_main_app_state")
    def test_save_latest_state_strips_pid_suffix(self, mock_save_state):
        app = _make_app_stub()
        app.selected_process = FakeVar("SomeProcess (4321)")
        app.selected_profile = FakeVar("Quick")
        app.host.window_position.return_value = "80/90"

        RunController.save_state(app)

        mock_save_state.assert_called_once_with(
            process="SomeProcess",
            profile="Quick",
            run_set="__current__",
            modkey_set="Default",
            main_pos="80/90",
        )


class TestRuntimeToggleMouseHandlers(unittest.TestCase):
    @patch("app.presenters.run_controller.time.time", return_value=100.0)
    def test_runtime_toggle_mouse_scroll_toggles_wheel_up(self, _mock_time):
        app = _make_app_stub()
        app.is_running = True
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER

        RunController.on_runtime_toggle_mouse_scroll(app, 0, 0, 0, 1)

        app.toggle_runtime_event_group.assert_called_once()
        self.assertEqual(app.last_runtime_toggle_time, 100.0)

    @patch("app.presenters.run_controller.time.time", return_value=100.0)
    def test_runtime_toggle_mouse_click_toggles_button_3(self, _mock_time):
        app = _make_app_stub()
        app.is_running = True
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = MOUSE_BUTTON_3_TRIGGER
        button = type("ButtonStub", (), {"name": "x1"})()

        RunController.on_runtime_toggle_mouse_click(
            app,
            0,
            0,
            button,
            True,
        )

        app.toggle_runtime_event_group.assert_called_once()
        self.assertEqual(app.last_runtime_toggle_time, 100.0)

    @patch("app.presenters.run_controller.time.time", return_value=100.1)
    def test_runtime_toggle_mouse_scroll_respects_debounce(self, _mock_time):
        app = _make_app_stub()
        app.is_running = True
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_DOWN_TRIGGER
        app.last_runtime_toggle_time = 100.0

        RunController.on_runtime_toggle_mouse_scroll(app, 0, 0, 0, -1)

        app.toggle_runtime_event_group.assert_not_called()

    @patch("app.presenters.run_controller.time.time", return_value=100.2)
    def test_runtime_toggle_mouse_scroll_ignores_same_scroll_gesture(self, _mock_time):
        app = _make_app_stub()
        app.is_running = True
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = WHEEL_UP_TRIGGER
        app.latest_runtime_scroll_time = 100.0

        RunController.on_runtime_toggle_mouse_scroll(app, 0, 0, 0, 1)

        app.toggle_runtime_event_group.assert_not_called()




class TestRuntimeToggleKeyHandling(unittest.TestCase):
    def test_listener_key_name_uses_vk_for_ime_independent_letters(self):
        key = type("KeyStub", (), {"vk": KeyUtils.get_keycode("Q"), "char": "ㅂ"})()

        self.assertEqual(normalize_runtime_toggle_listener_key(key), "Q")

    @patch("app.presenters.run_controller.time.time", return_value=100.0)
    def test_on_key_press_matches_runtime_toggle_with_ime_text(self, _mock_time):
        app = _make_app_stub()
        app.is_running = True
        app.runtime_toggle_enabled = True
        app.runtime_toggle_key = "Q"
        app.settings.start_stop_key = "DISABLED"
        key = type("KeyStub", (), {"vk": KeyUtils.get_keycode("Q"), "char": "ㅂ"})()

        RunController.on_key_press(app, key)

        app.toggle_runtime_event_group.assert_called_once()
        self.assertEqual(app.last_runtime_toggle_time, 100.0)


class TestRunProfileNames(unittest.TestCase):
    def _controller(self, root: Path) -> RunController:
        app = _make_app_stub()
        app.profiles_dir = root / "profiles"
        app.run_sets_path = root / "run_sets.json"
        save_profile(app.profiles_dir, ProfileModel(name="Rot"))
        save_profile(app.profiles_dir, ProfileModel(name="Util"))
        return app

    def test_named_run_set_lists_existing_members(self):
        with tempfile.TemporaryDirectory() as td:
            app = self._controller(Path(td))
            upsert_run_set("Raid", ["Util", "Gone", "Rot"], app.run_sets_path)
            app.selected_run_set.set("Raid")
            app.selected_profile.set("Rot")

            self.assertEqual(app.run_profile_names(), ["Util", "Rot"])

    def test_empty_run_set_falls_back_to_the_profile(self):
        with tempfile.TemporaryDirectory() as td:
            app = self._controller(Path(td))
            upsert_run_set("Empty", ["Gone"], app.run_sets_path)
            app.selected_run_set.set("Empty")
            app.selected_profile.set("Rot")

            self.assertEqual(app.run_profile_names(), ["Rot"])

    def test_current_set_uses_the_profile(self):
        app = _make_app_stub()
        app.selected_profile.set("Quick")

        self.assertEqual(app.run_profile_names(), ["Quick"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
