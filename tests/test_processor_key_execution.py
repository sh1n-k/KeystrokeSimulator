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
            default_press_times=(0.05, 0.05),
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

    async def test_sim_key_aborts_hold_on_term_event(self):
        term = threading.Event()
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(1.0, 1.0),
            mod_keys={},
            os_type="Darwin",
            term_event=term,
        )
        handler.sim = SimpleNamespace(press=MagicMock(), release=MagicMock())
        sleep_calls = 0

        async def fake_sleep(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            term.set()

        with patch("app.core.processor.asyncio.sleep", side_effect=fake_sleep):
            await handler._sim_key("A")

        self.assertGreaterEqual(sleep_calls, 1)
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

    async def test_sim_key_honors_term_event_during_hold(self):
        term = threading.Event()
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(1.0, 1.0),
            mod_keys={},
            os_type="Darwin",
            term_event=term,
        )
        handler.sim = SimpleNamespace(press=MagicMock(), release=MagicMock())
        term.set()

        started = __import__("asyncio").get_running_loop().time()
        await handler._sim_key("A")
        elapsed = __import__("asyncio").get_running_loop().time() - started

        self.assertLess(elapsed, 0.2)
        handler.sim.press.assert_called_once_with(65)
        handler.sim.release.assert_called_once_with(65)


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

    def test_build_keybdinput_scancode_path_falls_back_when_scan_zero(self):
        with (
            patch.dict(os.environ, {"KEYSIM_WIN_SCANCODE": "1"}, clear=False),
            patch(
                "app.core.processor._windows_map_vk_to_scan", return_value=0
            ),
            patch("app.core.processor.logger.warning") as mock_warning,
        ):
            ki = processor_module._windows_build_keybdinput(0x41, key_up=False)

        self.assertEqual(ki.wVk, 0x41)
        self.assertEqual(ki.wScan, 0)
        self.assertEqual(ki.dwFlags & processor_module._KEYEVENTF_SCANCODE, 0)
        mock_warning.assert_called()

    def test_scancode_path_plus_extended_flag(self):
        with (
            patch.dict(os.environ, {"KEYSIM_WIN_SCANCODE": "1"}, clear=False),
            patch(
                "app.core.processor._windows_map_vk_to_scan", return_value=0x4B
            ),
        ):
            ki = processor_module._windows_build_keybdinput(0x25, key_up=False)

        self.assertEqual(ki.wVk, 0)
        flags = ki.dwFlags
        self.assertEqual(
            flags & processor_module._KEYEVENTF_SCANCODE,
            processor_module._KEYEVENTF_SCANCODE,
        )
        self.assertEqual(
            flags & processor_module._KEYEVENTF_EXTENDEDKEY,
            processor_module._KEYEVENTF_EXTENDEDKEY,
        )

    def test_input_struct_matches_msvc_layout(self):
        import ctypes

        self.assertEqual(
            ctypes.sizeof(processor_module._INPUT),
            processor_module._windows_expected_input_sizeof(),
        )
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(processor_module._KEYBDINPUT), 24)
            self.assertEqual(ctypes.sizeof(processor_module._MOUSEINPUT), 32)
            self.assertEqual(ctypes.sizeof(processor_module._INPUT), 40)
            self.assertEqual(processor_module._KEYBDINPUT.dwFlags.offset, 4)
            self.assertEqual(processor_module._KEYBDINPUT.dwExtraInfo.offset, 16)
            self.assertEqual(processor_module._INPUT.union.offset, 8)

    def test_configure_user32_sets_argtypes_once(self):
        import ctypes

        send = MagicMock()
        mapvk = MagicMock()
        user32 = SimpleNamespace(SendInput=send, MapVirtualKeyW=mapvk)
        windll = SimpleNamespace(user32=user32)
        processor_module._win_user32_ready = False

        with patch.dict(ctypes.__dict__, {"windll": windll}, clear=False):
            processor_module._configure_windows_input_apis()
            processor_module._configure_windows_input_apis()

        self.assertEqual(send.argtypes[0], ctypes.c_uint)
        self.assertIs(send.restype, ctypes.c_uint)
        self.assertEqual(mapvk.argtypes, [ctypes.c_uint, ctypes.c_uint])
        self.assertTrue(processor_module._win_user32_ready)
        self.assertEqual(
            send.argtypes,
            [ctypes.c_uint, ctypes.POINTER(processor_module._INPUT), ctypes.c_int],
        )
        processor_module._win_user32_ready = False

    def test_windows_send_key_invokes_sendinput_with_struct_size(self):
        import ctypes

        sent_sizes: list[int] = []
        sent_counts: list[int] = []

        def fake_send_input(n: int, _ptr: object, cb: int) -> int:
            sent_counts.append(n)
            sent_sizes.append(cb)
            return n

        fake_user32 = SimpleNamespace(
            MapVirtualKeyW=lambda _vk, _mode: 0x1E,
            SendInput=fake_send_input,
        )
        fake_windll = SimpleNamespace(user32=fake_user32)

        with (
            patch.dict(os.environ, {"KEYSIM_WIN_SCANCODE": ""}, clear=False),
            patch.dict(ctypes.__dict__, {"windll": fake_windll}, clear=False),
        ):
            processor_module._win_user32_ready = False
            processor_module._windows_send_key(0x41, key_up=False)
            processor_module._windows_send_key(0x41, key_up=True)
            processor_module._win_user32_ready = False

        self.assertEqual(sent_counts, [1, 1])
        expected = processor_module._windows_expected_input_sizeof()
        self.assertEqual(sent_sizes, [expected, expected])


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
