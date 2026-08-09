import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.utils.exception_hooks import install_exception_hooks


class TestExceptionHooks(unittest.TestCase):
    def tearDown(self):
        sys.excepthook = sys.__excepthook__
        threading.excepthook = threading.__excepthook__

    def test_install_sets_sys_thread_and_tk_hooks(self):
        root = SimpleNamespace()

        install_exception_hooks(root)

        self.assertIsNot(sys.excepthook, sys.__excepthook__)
        self.assertIsNot(threading.excepthook, threading.__excepthook__)
        self.assertTrue(callable(root.report_callback_exception))

    def test_sys_hook_logs_regular_exception(self):
        install_exception_hooks()
        exc = RuntimeError("boom")

        with patch("app.utils.exception_hooks.logger") as mock_logger:
            mock_logger.opt.return_value = mock_logger
            sys.excepthook(RuntimeError, exc, None)

        mock_logger.opt.assert_called_once()
        mock_logger.error.assert_called_once_with("Unhandled exception")

    def test_thread_hook_logs_regular_exception(self):
        install_exception_hooks()
        exc = RuntimeError("boom")
        args = SimpleNamespace(
            exc_type=RuntimeError,
            exc_value=exc,
            exc_traceback=None,
            thread=MagicMock(name="worker"),
        )
        args.thread.name = "worker"

        with patch("app.utils.exception_hooks.logger") as mock_logger:
            mock_logger.opt.return_value = mock_logger
            threading.excepthook(args)

        mock_logger.opt.assert_called_once()
        mock_logger.error.assert_called_once_with(
            "Unhandled thread exception in worker"
        )

    def test_keyboard_interrupt_delegates_to_default_sys_hook(self):
        install_exception_hooks()

        with patch("sys.__excepthook__") as mock_default:
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

        mock_default.assert_called_once()


if __name__ == "__main__":
    unittest.main()
