import threading
import unittest
from collections.abc import Callable
from unittest.mock import MagicMock, patch

from tests.qt_support import qt_app

from app.platform.input_router import Dispatcher, InputRouter
from app.ui.dispatcher import QtDispatcher


class FakeListener:
    def __init__(self, log: list[str] | None = None) -> None:
        self.started = False
        self.stopped = False
        self.log = log

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        if self.log is not None:
            self.log.append("listener.stop")


class FakeDispatcher:
    """Runs posted actions when the test calls `run_pending` (the "main thread")."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.active = False
        self.pending: list[Callable[[], object]] = []
        self.log = log if log is not None else []
        self._lock = threading.Lock()

    def start(self) -> None:
        self.active = True
        self.log.append("dispatcher.start")

    def post(self, action: Callable[[], object]) -> None:
        with self._lock:
            if self.active:
                self.pending.append(action)

    def stop(self) -> None:
        self.active = False
        with self._lock:
            self.pending.clear()
        self.log.append("dispatcher.stop")

    def run_pending(self) -> None:
        with self._lock:
            actions, self.pending = self.pending, []
        for action in actions:
            action()


class TestQtDispatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.app = qt_app()
        self.dispatcher = QtDispatcher()
        self.addCleanup(self.dispatcher.stop)

    def drain(self) -> None:
        self.app.processEvents()

    def test_satisfies_dispatcher_protocol(self) -> None:
        dispatcher: Dispatcher = self.dispatcher
        self.assertTrue(callable(dispatcher.post))

    def test_posted_action_runs_only_when_event_loop_drains(self) -> None:
        calls: list[str] = []
        self.dispatcher.start()
        self.dispatcher.post(lambda: calls.append("handled"))
        self.assertEqual(calls, [])

        self.drain()

        self.assertEqual(calls, ["handled"])

    def test_post_before_start_is_dropped(self) -> None:
        calls: list[str] = []
        self.dispatcher.post(lambda: calls.append("early"))
        self.dispatcher.start()
        self.drain()
        self.assertEqual(calls, [])

    def test_actions_run_in_post_order_and_errors_do_not_stop_drain(self) -> None:
        self.dispatcher.start()
        calls: list[int] = []

        def boom() -> None:
            raise RuntimeError("boom")

        self.dispatcher.post(lambda: calls.append(1))
        self.dispatcher.post(boom)
        self.dispatcher.post(lambda: calls.append(2))
        with patch("app.ui.dispatcher.logger") as logger:
            self.drain()
        self.assertEqual(calls, [1, 2])
        logger.exception.assert_called_once()

    def test_stop_discards_pending_actions_even_after_restart(self) -> None:
        calls: list[str] = []
        self.dispatcher.start()
        self.dispatcher.post(lambda: calls.append("pending"))

        self.dispatcher.stop()
        self.dispatcher.start()
        self.drain()

        self.assertEqual(calls, [])

    def test_post_from_worker_thread_runs_on_main_thread(self) -> None:
        self.dispatcher.start()
        ran_on: list[int] = []
        worker = threading.Thread(
            target=lambda: self.dispatcher.post(
                lambda: ran_on.append(threading.get_ident())
            )
        )
        worker.start()
        worker.join()
        self.assertEqual(ran_on, [])

        self.drain()

        self.assertEqual(ran_on, [threading.get_ident()])

    def test_action_that_stops_router_drops_later_actions(self) -> None:
        router = InputRouter(self.dispatcher)
        self.addCleanup(router.stop)
        listener = FakeListener()
        calls: list[str] = []
        router.start()
        router.add(listener)
        router.post(router.stop)
        router.post(lambda: calls.append("late"))

        self.drain()

        self.assertTrue(listener.stopped)
        self.assertEqual(calls, [])


class TestInputRouter(unittest.TestCase):
    def _router(self, log: list[str] | None = None) -> tuple[FakeDispatcher, InputRouter]:
        dispatcher = FakeDispatcher(log)
        router = InputRouter(dispatcher)
        self.addCleanup(router.stop)
        return dispatcher, router

    def test_post_goes_through_dispatcher(self) -> None:
        dispatcher, router = self._router()
        calls: list[str] = []
        router.start()
        router.post(lambda: calls.append("handled"))
        self.assertEqual(calls, [])

        dispatcher.run_pending()

        self.assertEqual(calls, ["handled"])

    def test_post_from_listener_thread_runs_on_dispatcher_turn(self) -> None:
        dispatcher, router = self._router()
        router.start()
        ran_on: list[int] = []
        worker = threading.Thread(
            target=lambda: router.post(lambda: ran_on.append(threading.get_ident()))
        )
        worker.start()
        worker.join()
        self.assertEqual(ran_on, [])

        dispatcher.run_pending()

        self.assertEqual(ran_on, [threading.get_ident()])

    def test_add_starts_listener_unless_already_started(self) -> None:
        _dispatcher, router = self._router()
        fresh = FakeListener()
        running = FakeListener()

        self.assertIs(router.add(fresh), fresh)
        router.add(running, started=True)

        self.assertTrue(fresh.started)
        self.assertFalse(running.started)

    def test_stop_drops_pending_then_stops_listeners(self) -> None:
        log: list[str] = []
        dispatcher, router = self._router(log)
        calls: list[str] = []
        router.start()
        router.add(FakeListener(log))
        router.post(lambda: calls.append("late"))

        router.stop()
        dispatcher.run_pending()

        self.assertEqual(calls, [])
        self.assertEqual(log, ["dispatcher.start", "dispatcher.stop", "listener.stop"])

    def test_stop_continues_when_listener_stop_fails(self) -> None:
        _dispatcher, router = self._router()
        broken = MagicMock()
        broken.stop.side_effect = RuntimeError("boom")
        ok = FakeListener()
        router.add(broken, started=True)
        router.add(ok, started=True)

        router.stop()

        self.assertTrue(ok.stopped)

    @patch("app.platform.input_router.ResponsivenessActivity")
    def test_responsiveness_begin_end(self, mock_activity_cls) -> None:
        activity = MagicMock()
        mock_activity_cls.return_value = activity
        _dispatcher, router = self._router()
        router.begin_responsiveness()
        router.begin_responsiveness()  # idempotent
        activity.begin.assert_called_once()
        router.end_responsiveness()
        activity.end.assert_called_once()

    @patch("app.platform.input_router.ResponsivenessActivity")
    def test_stop_ends_responsiveness(self, mock_activity_cls) -> None:
        activity = MagicMock()
        mock_activity_cls.return_value = activity
        _dispatcher, router = self._router()
        router.begin_responsiveness()

        router.stop()

        activity.end.assert_called_once()


if __name__ == "__main__":
    unittest.main()
