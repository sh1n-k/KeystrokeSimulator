import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.processor import KeystrokeProcessor


def _make_processor_stub() -> KeystrokeProcessor:
    proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
    proc.term_event = threading.Event()
    proc.key_codes = {"A": 65}
    proc.key_lock = threading.Lock()
    proc.state_lock = threading.Lock()
    proc.pressed_keys = set()
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

    async def test_press_key_async_cleans_pressed_keys_even_if_wait_fails(self):
        proc = _make_processor_stub()

        async def boom_wait(_end_time, _check_interval=0.02):
            raise RuntimeError("wait failed")

        proc._wait_until_async = boom_wait
        evt = {"name": "A_EVT", "key": "A"}

        with self.assertRaises(RuntimeError):
            await proc._press_key_async(evt)

        self.assertNotIn("A", proc.pressed_keys)

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

        with patch("app.core.processor.logger.info") as mock_info:
            await proc._press_key_async(evt, state_snapshot)

        mock_info.assert_called_once()
        log_line = mock_info.call_args[0][0]
        self.assertIn("Async Key Pressed: A", log_line)
        self.assertIn("[조건-비활성] 채널링 중=False", log_line)
        self.assertIn("[조건] 버프 준비=True", log_line)
        self.assertNotIn("무관한 조건", log_line)


class TestPressKeySync(unittest.TestCase):
    def test_sync_press_key_presses_and_releases(self):
        proc = _make_processor_stub()
        proc._wait_until_sync = lambda _end_time, _check_interval=0.02: None
        evt = {"name": "A_EVT", "key": "A"}

        proc._sync_press_key(evt)

        proc.sim.press.assert_called_once_with(65)
        proc.sim.release.assert_called_once_with(65)
        self.assertNotIn("A", proc.pressed_keys)

    def test_sync_press_key_skips_duplicate_pressed_key(self):
        proc = _make_processor_stub()
        proc.pressed_keys.add("A")
        evt = {"name": "A_EVT", "key": "A"}

        proc._sync_press_key(evt)

        proc.sim.press.assert_not_called()
        proc.sim.release.assert_not_called()

    def test_sync_press_key_cleans_pressed_keys_on_press_error(self):
        proc = _make_processor_stub()
        proc.sim.press.side_effect = RuntimeError("press failed")
        evt = {"name": "A_EVT", "key": "A"}

        with self.assertRaises(RuntimeError):
            proc._sync_press_key(evt)

        self.assertNotIn("A", proc.pressed_keys)

    def test_sync_press_key_logs_referenced_conditions_from_current_states(self):
        proc = _make_processor_stub()
        proc._wait_until_sync = lambda _end_time, _check_interval=0.02: None
        proc.current_states = {
            "[조건-비활성] 채널링 중": False,
            "[조건] 버프 준비": True,
            "무관한 조건": True,
        }
        evt = {
            "name": "A_EVT",
            "key": "A",
            "conds": {"[조건-비활성] 채널링 중": False, "[조건] 버프 준비": True},
        }

        with patch("app.core.processor.logger.info") as mock_info:
            proc._sync_press_key(evt)

        mock_info.assert_called_once()
        log_line = mock_info.call_args[0][0]
        self.assertIn("Sync Key Pressed: A", log_line)
        self.assertIn("[조건-비활성] 채널링 중=False", log_line)
        self.assertIn("[조건] 버프 준비=True", log_line)
        self.assertNotIn("무관한 조건", log_line)


class TestProcessorStart(unittest.TestCase):
    def test_start_only_starts_main_thread(self):
        proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
        proc.pid = None
        proc.main_thread = MagicMock()

        KeystrokeProcessor.start(proc)

        proc.main_thread.start.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
