import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ui.simulator_app import KeystrokeSimulatorApp
from app.platform.keys import KeyUtils


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
    app.modkey_sets_path = Path("modkey_sets.json")
    app.run_sets_path = Path("run_sets.json")
    app.selected_process = FakeVar("")
    app.selected_profile = FakeVar("")
    app.selected_modkey_set = FakeVar("Default")
    app.selected_run_set = FakeVar("__current__")
    app.run = MagicMock()
    app.run.is_running = False
    app.run.hotkey_short.return_value = ""
    app.update_ui = MagicMock()
    app._update_main_status = MagicMock()
    return app


class TestMainUiState(unittest.TestCase):
    def _make_ui_stub(self, running: bool) -> KeystrokeSimulatorApp:
        app = _make_app_stub()
        app.run.is_running = running

        app.process_frame = MagicMock()
        app.process_frame.process_combobox = MagicMock()
        app.process_frame.refresh_button = MagicMock()

        app.run_target_frame = MagicMock()
        app.modkey_set_frame = MagicMock()
        app.run_start_button = MagicMock()
        app.tools_menu = MagicMock()
        app._tools_menus = [app.tools_menu]

        app.run.readiness.return_value = {
            "can_start": not running,
            "badge_text": "Ready",
            "title": "title",
            "detail": "detail",
            "tone": "ready",
        }
        app._update_main_status = MagicMock()
        return app

    def _menu_states(self, app):
        entries = KeystrokeSimulatorApp._tools_entries(app)
        states = {}
        for call in app.tools_menu.entryconfigure.call_args_list:
            key = entries[call.args[0]][0]
            states[key] = call.kwargs["state"]
        return states

    def test_update_ui_disables_idle_tools_and_selectors_when_running(self):
        app = self._make_ui_stub(running=True)

        KeystrokeSimulatorApp.update_ui(app)

        states = self._menu_states(app)
        for key in ("quick", "settings", "clear_logs", "modkey_edit", "modkey_copy", "modkey_delete"):
            self.assertEqual(states[key], "disabled", key)
        # W-14: the workspace stays reachable while running.
        self.assertEqual(states["workspace"], "normal")
        app.run_target_frame.edit_button.config.assert_called_once_with(state="normal")
        app.run_target_frame.combobox.config.assert_called_once_with(state="disabled")
        app.modkey_set_frame.sets_combobox.config.assert_called_once_with(
            state="disabled"
        )

    def test_update_ui_enables_tools_when_stopped(self):
        app = self._make_ui_stub(running=False)

        KeystrokeSimulatorApp.update_ui(app)

        self.assertEqual(set(self._menu_states(app).values()), {"normal"})
        app.modkey_set_frame.sets_combobox.config.assert_called_once_with(
            state="readonly"
        )

    def test_update_ui_updates_start_button_label_for_running_state(self):
        app = self._make_ui_stub(running=True)

        KeystrokeSimulatorApp.update_ui(app)

        app.run_start_button.config.assert_called_once_with(
            text="■ Stop",
            state="normal",
        )

    def test_update_ui_disables_start_button_when_not_ready(self):
        app = self._make_ui_stub(running=False)
        app.run.readiness.return_value["can_start"] = False

        KeystrokeSimulatorApp.update_ui(app)

        app.run_start_button.config.assert_called_once_with(
            text="▶ Start",
            state="disabled",
        )

class TestRuntimeEditGuards(unittest.TestCase):
    @patch("app.ui.simulator_app.CaptureHud")
    def test_open_quick_events_noop_when_running(self, mock_hud):
        app = _make_app_stub()
        app.run.is_running = True

        KeystrokeSimulatorApp.open_quick_events(app)

        mock_hud.assert_not_called()

    @patch("app.ui.simulator_app.CaptureHud")
    def test_open_quick_events_opens_continuous_hud_when_stopped(self, mock_hud):
        app = _make_app_stub()
        app.run.is_running = False

        KeystrokeSimulatorApp.open_quick_events(app)

        mock_hud.assert_called_once_with(
            app,
            mode="continuous",
            profiles_dir=app.profiles_dir,
            on_close=app.update_ui,
        )

    @patch("app.ui.simulator_app.CaptureHud")
    def test_open_quick_events_reuses_open_hud(self, mock_hud):
        app = _make_app_stub()
        app.run.is_running = False
        existing = MagicMock()
        existing.is_open.return_value = True
        app._quick_hud = existing

        KeystrokeSimulatorApp.open_quick_events(app)

        mock_hud.assert_not_called()
        existing.win.lift.assert_called_once()


class TestReadinessSnapshotSideEffects(unittest.TestCase):
    @patch("app.ui.simulator_app.ModificationKeysWindow")
    def test_open_modkeys_noop_when_running(self, mock_modkeys):
        app = _make_app_stub()
        app.run.is_running = True
        app.selected_modkey_set = FakeVar("Default")

        KeystrokeSimulatorApp.open_modkeys(app)

        mock_modkeys.assert_not_called()

    @patch("app.ui.simulator_app.ModificationKeysWindow")
    def test_open_modkeys_opens_when_stopped(self, mock_modkeys):
        app = _make_app_stub()
        app.run.is_running = False
        app.selected_modkey_set = FakeVar("Combat")

        KeystrokeSimulatorApp.open_modkeys(app)

        mock_modkeys.assert_called_once_with(
            app, "Combat", sets_path=app.modkey_sets_path
        )

    @patch("app.ui.simulator_app.ModificationKeysWindow")
    def test_open_modkeys_refreshes_status_after_close(self, mock_modkeys):
        app = _make_app_stub()
        app.run.is_running = False
        app.selected_modkey_set = FakeVar("Default")

        KeystrokeSimulatorApp.open_modkeys(app)

        app._update_main_status.assert_called()

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
    @patch("app.ui.simulator_app.WindowUtils.center_window")
    @patch("app.ui.simulator_app.StateUtils.load_main_app_state")
    def test_restore_window_position_uses_saved_coordinates(
        self, mock_load_state, mock_center
    ):
        mock_load_state.return_value = {"main_pos": "120/340"}
        app = _make_app_stub()
        app.geometry = MagicMock()

        KeystrokeSimulatorApp._restore_window_position(app)

        app.geometry.assert_called_once_with("+120+340")
        mock_center.assert_not_called()

    @patch("app.ui.simulator_app.WindowUtils.center_window")
    @patch("app.ui.simulator_app.StateUtils.load_main_app_state")
    def test_restore_window_position_centers_when_missing(
        self, mock_load_state, mock_center
    ):
        mock_load_state.return_value = {}
        app = _make_app_stub()
        app.geometry = MagicMock()

        KeystrokeSimulatorApp._restore_window_position(app)

        mock_center.assert_called_once_with(app)
        app.geometry.assert_not_called()


class TestMacKeyPollListener(unittest.TestCase):
    def _make_listener(self, **kwargs):
        from app.platform.mac_key_poll import MacKeyPollListener

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
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.platform.mac_key_poll.KeyUtils.key_pressed", return_value=False):
            with patch("app.platform.mac_key_poll.time.time", return_value=100.0):
                listener._tick()
            self.assertEqual(posted, [])

            with patch("app.platform.mac_key_poll.time.time", return_value=100.01):
                listener._tick()
            self.assertEqual(posted, [])

            with patch("app.platform.mac_key_poll.time.time", return_value=100.02):
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
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.platform.mac_key_poll.time.time", return_value=100.0):
            listener._tick()
        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.platform.mac_key_poll.time.time", return_value=100.05):
            listener._tick()
        self.assertEqual(posted, [])
        start_stop.assert_not_called()

    def test_partial_release_rearms_chord_for_next_press(self) -> None:
        """Either key up breaks the chord and must allow the next Option+Shift."""
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.platform.mac_key_poll.time.time", return_value=100.0):
                listener._tick()
            with patch("app.platform.mac_key_poll.time.time", return_value=100.04):
                listener._tick()
        self.assertEqual(len(posted), 1)

        def only_option(key: str, **_kwargs: object) -> bool:
            return key == "alt"

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", side_effect=only_option
        ), patch("app.platform.mac_key_poll.time.time", return_value=100.5):
            listener._tick()
        self.assertFalse(listener._latched)

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.platform.mac_key_poll.time.time", return_value=101.0):
                listener._tick()
            with patch("app.platform.mac_key_poll.time.time", return_value=101.04):
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
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", side_effect=track
        ), patch("app.platform.mac_key_poll.time.time", return_value=100.0):
            listener._tick()
        self.assertEqual(calls[0], ("alt", True))
        self.assertEqual(calls[1], ("shift", True))

    def test_full_release_rearms_for_next_chord(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.platform.mac_key_poll.time.time", return_value=100.0):
                listener._tick()
            with patch("app.platform.mac_key_poll.time.time", return_value=100.04):
                listener._tick()

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=False
        ), patch("app.platform.mac_key_poll.time.time", return_value=100.5):
            listener._tick()
        self.assertFalse(listener._latched)

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.platform.mac_key_poll.time.time", return_value=101.0):
                listener._tick()
            with patch("app.platform.mac_key_poll.time.time", return_value=101.04):
                listener._tick()

        self.assertEqual(len(posted), 2)
        posted[0]()
        posted[1]()
        self.assertEqual(start_stop.call_count, 2)

    def test_debounce_blocks_rapid_rearm(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.platform.mac_key_poll.time.time", return_value=100.0):
                listener._tick()
            with patch("app.platform.mac_key_poll.time.time", return_value=100.04):
                listener._tick()

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=False
        ), patch("app.platform.mac_key_poll.time.time", return_value=100.05):
            listener._tick()

        # Re-arm attempt still inside 0.2s debounce from first fire at 100.04.
        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.platform.mac_key_poll.time.time", return_value=100.10):
                listener._tick()
            with patch("app.platform.mac_key_poll.time.time", return_value=100.20):
                listener._tick()
        self.assertEqual(len(posted), 1)

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            with patch("app.platform.mac_key_poll.time.time", return_value=100.30):
                listener._tick()
            with patch("app.platform.mac_key_poll.time.time", return_value=100.34):
                listener._tick()
        self.assertEqual(len(posted), 2)
        posted[0]()
        posted[1]()
        self.assertEqual(start_stop.call_count, 2)

    def test_does_not_flood_queue_while_chord_held(self) -> None:
        """Regression: continuous samples must not enqueue every poll tick."""
        listener, _session, posted, start_stop, _runtime = self._make_listener()

        with patch(
            "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
        ):
            t = 100.0
            for _ in range(40):
                with patch("app.platform.mac_key_poll.time.time", return_value=t):
                    listener._tick()
                t += 0.015

        # One fire after hold, then latched: no further posts while still held.
        self.assertEqual(len(posted), 1)
        posted[0]()
        start_stop.assert_called_once()

    def test_listener_stop_joins_thread(self) -> None:
        from app.platform.mac_key_poll import MacKeyPollListener

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
    @patch("app.platform.keys.IS_MAC", True)
    @patch("app.platform.keys.IS_WIN", False)
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

        with patch("app.platform.keys.quartz_symbol", side_effect=fake_symbol):
            self.assertTrue(KeyUtils.mod_key_pressed("alt"))
        self.assertIn(58, calls)
        self.assertIn(61, calls)

    @patch("app.platform.keys.IS_MAC", True)
    @patch("app.platform.keys.IS_WIN", False)
    def test_physical_only_skips_sticky_flag_fallback(self):
        def fake_symbol(name: str):
            if name == "CGEventSourceKeyState":
                return lambda _hid, _code: False
            if name == "kCGEventSourceStateHIDSystemState":
                return "HID"
            if name == "CGEventSourceFlagsState":
                return lambda _hid: 0xFFFFFFFF  # all flags set
            return 1

        with patch("app.platform.keys.quartz_symbol", side_effect=fake_symbol):
            self.assertFalse(KeyUtils.mod_key_pressed("shift", physical_only=True))
            self.assertTrue(KeyUtils.mod_key_pressed("shift", physical_only=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
