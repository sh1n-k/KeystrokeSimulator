import unittest
from unittest.mock import MagicMock, patch

from app.platform.keys import KeyUtils


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

        with (
            patch(
                "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
            ),
            patch("app.platform.mac_key_poll.KeyUtils.key_pressed", return_value=False),
        ):
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
        with (
            patch(
                "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
            ),
            patch("app.platform.mac_key_poll.time.time", return_value=100.0),
        ):
            listener._tick()
        with (
            patch(
                "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=True
            ),
            patch("app.platform.mac_key_poll.time.time", return_value=100.05),
        ):
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

        with (
            patch(
                "app.platform.mac_key_poll.KeyUtils.mod_key_pressed",
                side_effect=only_option,
            ),
            patch("app.platform.mac_key_poll.time.time", return_value=100.5),
        ):
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

        with (
            patch(
                "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", side_effect=track
            ),
            patch("app.platform.mac_key_poll.time.time", return_value=100.0),
        ):
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

        with (
            patch(
                "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=False
            ),
            patch("app.platform.mac_key_poll.time.time", return_value=100.5),
        ):
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

        with (
            patch(
                "app.platform.mac_key_poll.KeyUtils.mod_key_pressed", return_value=False
            ),
            patch("app.platform.mac_key_poll.time.time", return_value=100.05),
        ):
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
