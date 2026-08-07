import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core import processor as processor_module
from app.core.processor import KeystrokeProcessor, ModificationKeyHandler


def _make_processor_stub() -> KeystrokeProcessor:
    proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
    proc.term_event = threading.Event()
    proc.key_codes = {"A": 65}
    proc.key_lock = threading.Lock()
    proc.state_lock = threading.Lock()
    proc.pressed_keys = set()
    proc.pressed_key_codes = {}
    proc.current_states = {}
    proc.sim = SimpleNamespace(press=MagicMock(), release=MagicMock())
    proc._calculate_press_duration = lambda _evt: 0.05
    return proc


class TestPressKeyAsync(unittest.IsolatedAsyncioTestCase):
    async def test_press_key_async_presses_and_releases(self):
        proc = _make_processor_stub()

        async def fake_wait(_end_time, _check_interval=0.02):
            return None

        proc._wait_until_async = fake_wait
        evt = {"name": "A_EVT", "key": "A"}

        await proc._press_key_async(evt)

        proc.sim.press.assert_called_once_with(65)
        proc.sim.release.assert_called_once_with(65)
        self.assertNotIn("A", proc.pressed_keys)
        self.assertNotIn("A", proc.pressed_key_codes)

    async def test_press_key_async_skips_when_terminated(self):
        proc = _make_processor_stub()
        proc.term_event.set()
        evt = {"name": "A_EVT", "key": "A"}

        await proc._press_key_async(evt)

        proc.sim.press.assert_not_called()
        proc.sim.release.assert_not_called()

    async def test_press_key_async_skips_duplicate_pressed_key(self):
        proc = _make_processor_stub()
        proc.pressed_keys.add("A")
        evt = {"name": "A_EVT", "key": "A"}

        await proc._press_key_async(evt)

        proc.sim.press.assert_not_called()
        proc.sim.release.assert_not_called()

    async def test_press_key_async_releases_even_if_wait_fails(self):
        proc = _make_processor_stub()

        async def boom_wait(_end_time, _check_interval=0.02):
            raise RuntimeError("wait failed")

        proc._wait_until_async = boom_wait
        evt = {"name": "A_EVT", "key": "A"}

        with self.assertRaises(RuntimeError):
            await proc._press_key_async(evt)

        proc.sim.press.assert_called_once_with(65)
        proc.sim.release.assert_called_once_with(65)
        self.assertNotIn("A", proc.pressed_keys)
        self.assertNotIn("A", proc.pressed_key_codes)

    async def test_press_key_async_logs_only_referenced_conditions(self):
        proc = _make_processor_stub()

        async def fake_wait(_end_time, _check_interval=0.02):
            return None

        proc._wait_until_async = fake_wait
        evt = {
            "name": "A_EVT",
            "key": "A",
            "conds": {"[조건-비활성] 채널링 중": False, "[조건] 버프 준비": True},
        }
        state_snapshot = {
            "[조건-비활성] 채널링 중": False,
            "[조건] 버프 준비": True,
            "무관한 조건": True,
        }

        with patch("app.core.processor.logger.debug") as mock_debug:
            await proc._press_key_async(evt, state_snapshot)

        mock_debug.assert_called_once()
        log_line = mock_debug.call_args[0][0]
        self.assertIn("Async Key Pressed: A", log_line)
        self.assertIn("[조건-비활성] 채널링 중=False", log_line)
        self.assertIn("[조건] 버프 준비=True", log_line)
        self.assertNotIn("무관한 조건", log_line)

    async def test_press_key_async_allows_zero_keycode(self):
        """Darwin 'A' is keycode 0; must not be treated as missing."""
        proc = _make_processor_stub()
        proc.key_codes = {"A": 0}

        async def fake_wait(_end_time, _check_interval=0.02):
            return None

        proc._wait_until_async = fake_wait
        evt = {"name": "A_EVT", "key": "A"}

        await proc._press_key_async(evt)

        proc.sim.press.assert_called_once_with(0)
        proc.sim.release.assert_called_once_with(0)
        self.assertNotIn("A", proc.pressed_keys)
        self.assertNotIn("A", proc.pressed_key_codes)

    async def test_press_key_async_keeps_tracking_if_release_fails(self):
        proc = _make_processor_stub()

        async def fake_wait(_end_time, _check_interval=0.02):
            return None

        proc._wait_until_async = fake_wait
        proc.sim.release.side_effect = RuntimeError("release boom")
        evt = {"name": "A_EVT", "key": "A"}

        await proc._press_key_async(evt)

        proc.sim.press.assert_called_once_with(65)
        proc.sim.release.assert_called_once_with(65)
        self.assertIn("A", proc.pressed_keys)
        self.assertEqual(proc.pressed_key_codes.get("A"), 65)


class TestForceRelease(unittest.TestCase):
    def test_force_release_clears_tracked_keys(self):
        proc = _make_processor_stub()
        proc.pressed_keys = {"A", "B"}
        proc.pressed_key_codes = {"A": 65, "B": 66}

        proc._force_release_pressed_keys()

        self.assertEqual(proc.sim.release.call_count, 2)
        proc.sim.release.assert_any_call(65)
        proc.sim.release.assert_any_call(66)
        self.assertEqual(proc.pressed_keys, set())
        self.assertEqual(proc.pressed_key_codes, {})

    def test_stop_force_releases_after_join(self):
        proc = _make_processor_stub()
        proc.main_thread = MagicMock()
        proc.main_thread.is_alive.return_value = False
        proc.pressed_keys = {"A"}
        proc.pressed_key_codes = {"A": 65}

        KeystrokeProcessor.stop(proc)

        proc.sim.release.assert_called_once_with(65)
        self.assertEqual(proc.pressed_keys, set())

    def test_force_release_retains_tracking_if_release_fails(self):
        proc = _make_processor_stub()
        proc.pressed_keys = {"A"}
        proc.pressed_key_codes = {"A": 65}
        proc.sim.release.side_effect = RuntimeError("os deny")

        proc._force_release_pressed_keys()

        proc.sim.release.assert_called_once_with(65)
        self.assertEqual(proc.pressed_keys, {"A"})
        self.assertEqual(proc.pressed_key_codes, {"A": 65})


class TestModificationKeySimRelease(unittest.IsolatedAsyncioTestCase):
    async def test_sim_key_releases_after_sleep(self):
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(0.0, 0.0),
            mod_keys={},
            os_type="Darwin",
        )
        handler.sim = SimpleNamespace(press=MagicMock(), release=MagicMock())

        with patch("app.core.processor.asyncio.sleep", return_value=None):
            await handler._sim_key("A")

        handler.sim.press.assert_called_once_with(65)
        handler.sim.release.assert_called_once_with(65)

    async def test_sim_key_releases_if_sleep_fails(self):
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(0.0, 0.0),
            mod_keys={},
            os_type="Darwin",
        )
        handler.sim = SimpleNamespace(press=MagicMock(), release=MagicMock())

        with patch(
            "app.core.processor.asyncio.sleep",
            side_effect=RuntimeError("sleep boom"),
        ):
            with self.assertRaises(RuntimeError):
                await handler._sim_key("A")

        handler.sim.press.assert_called_once_with(65)
        handler.sim.release.assert_called_once_with(65)

    async def test_sim_key_tracks_pressed_keys_for_force_release(self):
        lock = threading.Lock()
        pressed_keys: set[str] = set()
        pressed_key_codes: dict[str, int] = {}
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(0.0, 0.0),
            mod_keys={},
            os_type="Darwin",
            key_lock=lock,
            pressed_keys=pressed_keys,
            pressed_key_codes=pressed_key_codes,
        )
        handler.sim = SimpleNamespace(press=MagicMock(), release=MagicMock())

        with patch("app.core.processor.asyncio.sleep", return_value=None):
            await handler._sim_key("A")

        self.assertEqual(pressed_keys, set())
        self.assertEqual(pressed_key_codes, {})

    async def test_sim_key_keeps_tracking_when_release_fails(self):
        lock = threading.Lock()
        pressed_keys: set[str] = set()
        pressed_key_codes: dict[str, int] = {}
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(0.0, 0.0),
            mod_keys={},
            os_type="Darwin",
            key_lock=lock,
            pressed_keys=pressed_keys,
            pressed_key_codes=pressed_key_codes,
        )
        handler.sim = SimpleNamespace(
            press=MagicMock(),
            release=MagicMock(side_effect=RuntimeError("release boom")),
        )

        with patch("app.core.processor.asyncio.sleep", return_value=None):
            await handler._sim_key("A")

        self.assertEqual(pressed_keys, {"A"})
        self.assertEqual(pressed_key_codes, {"A": 65})

    async def test_sim_key_allows_zero_keycode(self):
        handler = ModificationKeyHandler(
            key_codes={"A": 0},
            default_press_times=(0.0, 0.0),
            mod_keys={},
            os_type="Darwin",
        )
        handler.sim = SimpleNamespace(press=MagicMock(), release=MagicMock())

        with patch("app.core.processor.asyncio.sleep", return_value=None):
            await handler._sim_key("A")

        handler.sim.press.assert_called_once_with(0)
        handler.sim.release.assert_called_once_with(0)


class TestWindowsSendInputHelpers(unittest.TestCase):
    def test_extended_vk_detection(self):
        self.assertTrue(processor_module._windows_is_extended_vk(0x25))  # Left
        self.assertTrue(processor_module._windows_is_extended_vk(0x2E))  # Delete
        self.assertFalse(processor_module._windows_is_extended_vk(0x41))  # A
        self.assertFalse(processor_module._windows_is_extended_vk(0x0D))  # Enter

    def test_build_keybdinput_default_uses_vk_and_scan(self):
        with (
            patch.dict(os.environ, {"KEYSIM_WIN_SCANCODE": ""}, clear=False),
            patch(
                "app.core.processor._windows_map_vk_to_scan", return_value=0x1E
            ),
        ):
            ki = processor_module._windows_build_keybdinput(0x41, key_up=False)

        self.assertEqual(ki.wVk, 0x41)
        self.assertEqual(ki.wScan, 0x1E)
        self.assertEqual(ki.dwFlags & processor_module._KEYEVENTF_SCANCODE, 0)

    def test_build_keybdinput_scancode_path_clears_vk(self):
        with (
            patch.dict(os.environ, {"KEYSIM_WIN_SCANCODE": "1"}, clear=False),
            patch(
                "app.core.processor._windows_map_vk_to_scan", return_value=0x1E
            ),
        ):
            ki = processor_module._windows_build_keybdinput(0x41, key_up=True)

        self.assertEqual(ki.wVk, 0)
        self.assertEqual(ki.wScan, 0x1E)
        self.assertEqual(
            ki.dwFlags & processor_module._KEYEVENTF_SCANCODE,
            processor_module._KEYEVENTF_SCANCODE,
        )
        self.assertEqual(
            ki.dwFlags & processor_module._KEYEVENTF_KEYUP,
            processor_module._KEYEVENTF_KEYUP,
        )

    def test_build_keybdinput_sets_extended_flag(self):
        with (
            patch.dict(os.environ, {"KEYSIM_WIN_SCANCODE": ""}, clear=False),
            patch(
                "app.core.processor._windows_map_vk_to_scan", return_value=0x4B
            ),
        ):
            ki = processor_module._windows_build_keybdinput(0x25, key_up=False)

        self.assertEqual(
            ki.dwFlags & processor_module._KEYEVENTF_EXTENDEDKEY,
            processor_module._KEYEVENTF_EXTENDEDKEY,
        )


class TestDarwinKeyEventSource(unittest.TestCase):
    def test_darwin_key_event_uses_hid_event_source(self):
        created_sources: list[object] = []
        created_events: list[tuple[object, int, bool]] = []
        posted: list[tuple[object, object]] = []
        source_token = object()
        event_token = object()

        def source_create(state: object) -> object:
            created_sources.append(state)
            return source_token

        def create_event(source: object, code: int, pressed: bool) -> object:
            created_events.append((source, code, pressed))
            return event_token

        def post_event(tap: object, event: object) -> None:
            posted.append((tap, event))

        fake_quartz = SimpleNamespace(
            CGEventSourceCreate=source_create,
            CGEventCreateKeyboardEvent=create_event,
            CGEventPost=post_event,
            kCGHIDEventTap="HID_TAP",
            kCGEventSourceStateHIDSystemState="HID_STATE",
        )

        with patch("app.core.processor.importlib.import_module", return_value=fake_quartz):
            processor_module._darwin_key_event(0, True)

        self.assertEqual(created_sources, ["HID_STATE"])
        self.assertEqual(created_events, [(source_token, 0, True)])
        self.assertEqual(posted, [("HID_TAP", event_token)])


class TestProcessorStart(unittest.TestCase):
    def test_start_only_starts_main_thread(self):
        proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
        proc.pid = None
        proc.main_thread = MagicMock()

        KeystrokeProcessor.start(proc)

        proc.main_thread.start.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
