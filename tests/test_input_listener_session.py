import unittest
from unittest.mock import MagicMock, patch

from app.ui.input_listener_session import InputListenerSession


class FakeRoot:
    def __init__(self) -> None:
        self.callback = None
        self.cancelled = None
        self.after_calls = 0
        self.filehandlers: list = []
        self.deleted_handlers: list = []
        self.READABLE = 1

    def after(self, _delay: int, callback):
        self.after_calls += 1
        self.callback = callback
        return f"after-{self.after_calls}"

    def after_cancel(self, after_id: str) -> None:
        self.cancelled = after_id

    def createfilehandler(self, file, mask, func):
        self.filehandlers.append((file, mask, func))

    def deletefilehandler(self, file):
        self.deleted_handlers.append(file)


class FakeListener:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class TestInputListenerSession(unittest.TestCase):
    def _session(self) -> tuple[FakeRoot, InputListenerSession]:
        root = FakeRoot()
        session = InputListenerSession(root)
        self.addCleanup(session.stop)
        return root, session

    def test_posted_action_runs_only_when_tk_pump_drains(self) -> None:
        root, session = self._session()
        calls = []
        session.start()
        # Consume idle pump schedule from start().
        assert root.callback is not None
        root.callback()

        session.post(lambda: calls.append("handled"))
        self.assertEqual(calls, [])
        # post() schedules after(0) kick.
        assert root.callback is not None
        root.callback()

        self.assertEqual(calls, ["handled"])

    def test_post_schedules_immediate_kick(self) -> None:
        root, session = self._session()
        session.start()
        start_calls = root.after_calls
        session.post(lambda: None)
        # One extra after(0) kick beyond the idle pump.
        self.assertGreaterEqual(root.after_calls, start_calls + 1)
        self.assertEqual(root.callback, session._kicked_drain)

    def test_stop_stops_owned_listeners_and_cancels_pump(self) -> None:
        root, session = self._session()
        listener = FakeListener()
        session.start()
        session.add(listener)

        session.stop()

        self.assertTrue(listener.started)
        self.assertTrue(listener.stopped)
        self.assertIsNotNone(root.cancelled)

    def test_action_that_stops_session_does_not_restart_pump(self) -> None:
        root, session = self._session()
        session.start()
        # Drain idle start schedule, then post stop via kick.
        assert root.callback is not None
        root.callback()
        session.post(session.stop)
        assert root.callback is not None
        calls_before = root.after_calls
        root.callback()
        # stop() must not schedule another idle pump.
        self.assertEqual(root.after_calls, calls_before)

    def test_action_can_restart_session_without_duplicate_pump(self) -> None:
        root, session = self._session()
        session.start()
        assert root.callback is not None
        root.callback()

        def restart() -> None:
            session.stop()
            session.start()

        session.post(restart)
        assert root.callback is not None
        root.callback()

        # restart() -> start() schedules one idle drain.
        self.assertIsNotNone(root.callback)

    def test_start_installs_wake_filehandler(self) -> None:
        root, session = self._session()
        session.start()
        self.assertEqual(len(root.filehandlers), 1)
        self.assertTrue(session._filehandler_installed)

    def test_wake_readable_drains_posted_actions(self) -> None:
        root, session = self._session()
        session.start()
        # Consume idle pump from start.
        assert root.callback is not None
        root.callback()

        calls: list[str] = []
        session.post(lambda: calls.append("via-wake"))
        # Simulate Tk filehandler callback instead of after kick.
        _file, _mask, handler = root.filehandlers[0]
        handler()
        self.assertEqual(calls, ["via-wake"])

    def test_stop_removes_filehandler(self) -> None:
        root, session = self._session()
        session.start()
        session.stop()
        self.assertEqual(len(root.deleted_handlers), 1)
        self.assertFalse(session._filehandler_installed)

    @patch("app.ui.input_listener_session.ResponsivenessActivity")
    def test_responsiveness_begin_end(self, mock_activity_cls) -> None:
        activity = MagicMock()
        mock_activity_cls.return_value = activity
        root = FakeRoot()
        session = InputListenerSession(root)
        self.addCleanup(session.stop)
        session.begin_responsiveness()
        session.begin_responsiveness()  # idempotent
        activity.begin.assert_called_once()
        session.end_responsiveness()
        activity.end.assert_called_once()


if __name__ == "__main__":
    unittest.main()
