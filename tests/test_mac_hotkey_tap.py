"""Unit tests for macOS CGEventTap hotkey chord consume logic."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.ui.mac_hotkey_tap import MacHotkeyTapListener
from app.utils.keys import KeyUtils


class _QuartzStub:
    kCGEventFlagsChanged = 12
    kCGEventKeyDown = 10
    kCGEventKeyUp = 11
    kCGEventTapDisabledByTimeout = 0xFFFFFFFE
    kCGEventTapDisabledByUserInput = 0xFFFFFFFF
    kCGKeyboardEventKeycode = 9
    kCGKeyboardEventAutorepeat = 8

    def __init__(self) -> None:
        self.keycode = 0
        self.autorepeat = 0
        self.reenabled = False

    def CGEventGetIntegerValueField(self, _event, field):
        if field == self.kCGKeyboardEventKeycode:
            return self.keycode
        if field == self.kCGKeyboardEventAutorepeat:
            return self.autorepeat
        return 0

    def CGEventTapEnable(self, _tap, enabled):
        self.reenabled = bool(enabled)


class TestMacHotkeyTapProcessEvent(unittest.TestCase):
    def _make(self, **kwargs):
        session = MagicMock()
        posted: list = []
        session.post.side_effect = lambda action: posted.append(action)
        start_stop = MagicMock()
        runtime = MagicMock()
        listener = MacHotkeyTapListener(
            session,
            debounce_seconds=0.2,
            runtime_debounce_seconds=0.25,
            start_stop_enabled=kwargs.get("start_stop_enabled", lambda: True),
            runtime_toggle_enabled=kwargs.get("runtime_toggle_enabled", lambda: False),
            runtime_key_provider=kwargs.get("runtime_key_provider", lambda: None),
            on_start_stop=start_stop,
            on_runtime_toggle=runtime,
        )
        return listener, session, posted, start_stop, runtime

    def test_chord_rising_edge_posts_and_swallows_modifier_flags(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make()
        quartz = _QuartzStub()
        quartz.keycode = 56  # shift
        event = object()

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=True
        ):
            # First event with both down: rising edge.
            out = listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)

        self.assertIsNone(out)
        self.assertEqual(len(posted), 1)
        posted[0]()
        start_stop.assert_called_once()

        # Still held: swallow, no second post.
        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=True
        ):
            out2 = listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)
        self.assertIsNone(out2)
        self.assertEqual(len(posted), 1)

        # After fire, partial release still swallows until both keys are up.
        def only_shift(key: str, **_kwargs: object) -> bool:
            return key == "shift"

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", side_effect=only_shift
        ):
            out3 = listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)
        self.assertIsNone(out3)

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=False
        ):
            out4 = listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)
        # Both up clears swallow; this flagsChanged is passed through.
        self.assertIs(out4, event)

    def test_single_modifier_passes_through(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make()
        quartz = _QuartzStub()
        quartz.keycode = 58  # option
        event = object()

        def only_option(key: str, **_kwargs: object) -> bool:
            return key == "alt"

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", side_effect=only_option
        ):
            out = listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)

        self.assertIs(out, event)
        self.assertEqual(posted, [])
        start_stop.assert_not_called()

    def test_debounce_blocks_second_chord(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make()
        quartz = _QuartzStub()
        quartz.keycode = 56
        event = object()

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.ui.mac_hotkey_tap.time.time", return_value=100.0):
            listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=False
        ), patch("app.ui.mac_hotkey_tap.time.time", return_value=100.05):
            listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.ui.mac_hotkey_tap.time.time", return_value=100.10):
            listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)

        self.assertEqual(len(posted), 1)

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=False
        ), patch("app.ui.mac_hotkey_tap.time.time", return_value=100.30):
            listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=True
        ), patch("app.ui.mac_hotkey_tap.time.time", return_value=100.35):
            listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)

        self.assertEqual(len(posted), 2)
        posted[0]()
        posted[1]()
        self.assertEqual(start_stop.call_count, 2)

    def test_disabled_start_stop_does_not_swallow(self) -> None:
        listener, _session, posted, start_stop, _runtime = self._make(
            start_stop_enabled=lambda: False
        )
        quartz = _QuartzStub()
        quartz.keycode = 56
        event = object()

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=True
        ):
            out = listener._process_event(quartz, quartz.kCGEventFlagsChanged, event)

        self.assertIs(out, event)
        self.assertEqual(posted, [])
        start_stop.assert_not_called()

    def test_runtime_key_down_consumed_and_posted(self) -> None:
        q_code = KeyUtils.get_keycode("Q")
        self.assertIsNotNone(q_code)
        listener, _session, posted, _start_stop, runtime = self._make(
            runtime_toggle_enabled=lambda: True,
            runtime_key_provider=lambda: "Q",
        )
        quartz = _QuartzStub()
        quartz.keycode = int(q_code or 12)
        event = object()

        with patch(
            "app.ui.mac_hotkey_tap.KeyUtils.mod_key_pressed", return_value=False
        ), patch("app.ui.mac_hotkey_tap.time.time", return_value=50.0):
            out = listener._process_event(quartz, quartz.kCGEventKeyDown, event)

        self.assertIsNone(out)
        self.assertEqual(len(posted), 1)
        posted[0]()
        runtime.assert_called_once()

    def test_tap_disabled_event_reenabled(self) -> None:
        listener, _session, _posted, _s, _r = self._make()
        quartz = _QuartzStub()
        listener._tap = object()
        event = object()
        out = listener._handle_event(
            quartz, None, quartz.kCGEventTapDisabledByTimeout, event
        )
        self.assertIs(out, event)
        self.assertTrue(quartz.reenabled)


if __name__ == "__main__":
    unittest.main()
