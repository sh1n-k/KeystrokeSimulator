import unittest

from app.ui.input_listener_session import InputListenerSession


class FakeRoot:
    def __init__(self) -> None:
        self.callback = None
        self.cancelled = None
        self.after_calls = 0

    def after(self, _delay: int, callback):
        self.after_calls += 1
        self.callback = callback
        return f"after-{self.after_calls}"

    def after_cancel(self, after_id: str) -> None:
        self.cancelled = after_id


class FakeListener:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class TestInputListenerSession(unittest.TestCase):
    def test_posted_action_runs_only_when_tk_pump_drains(self) -> None:
        root = FakeRoot()
        session = InputListenerSession(root)
        calls = []
        session.start()

        session.post(lambda: calls.append("handled"))
        self.assertEqual(calls, [])
        assert root.callback is not None
        root.callback()

        self.assertEqual(calls, ["handled"])

    def test_stop_stops_owned_listeners_and_cancels_pump(self) -> None:
        root = FakeRoot()
        session = InputListenerSession(root)
        listener = FakeListener()
        session.start()
        session.add(listener)

        session.stop()

        self.assertTrue(listener.started)
        self.assertTrue(listener.stopped)
        self.assertEqual(root.cancelled, "after-1")

    def test_action_that_stops_session_does_not_restart_pump(self) -> None:
        root = FakeRoot()
        session = InputListenerSession(root)
        session.start()
        session.post(session.stop)
        assert root.callback is not None

        root.callback()

        self.assertEqual(root.after_calls, 1)

    def test_action_can_restart_session_without_duplicate_pump(self) -> None:
        root = FakeRoot()
        session = InputListenerSession(root)
        session.start()

        def restart() -> None:
            session.stop()
            session.start()

        session.post(restart)
        assert root.callback is not None
        root.callback()

        self.assertEqual(root.after_calls, 2)


if __name__ == "__main__":
    unittest.main()
