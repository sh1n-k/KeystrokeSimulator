import sys
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Protocol, cast

from loguru import logger


class TkExceptionReporter(Protocol):
    report_callback_exception: Callable[
        [type[BaseException], BaseException, TracebackType | None], None
    ]


def _log_unhandled_exception(
    message: str,
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: TracebackType | None,
) -> None:
    logger.opt(exception=(exc_type, exc_value, traceback)).error(message)


def _handle_sys_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, traceback)
        return
    _log_unhandled_exception("Unhandled exception", exc_type, exc_value, traceback)


def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
    if issubclass(args.exc_type, KeyboardInterrupt):
        threading.__excepthook__(args)
        return
    if args.exc_value is None:
        logger.error("Unhandled thread exception without exception value")
        return
    thread_name = args.thread.name if args.thread else "unknown"
    _log_unhandled_exception(
        f"Unhandled thread exception in {thread_name}",
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
    )


def _handle_tk_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: TracebackType | None,
) -> None:
    _log_unhandled_exception(
        "Unhandled Tk callback exception", exc_type, exc_value, traceback
    )


def install_exception_hooks(root: object | None = None) -> None:
    sys.excepthook = _handle_sys_exception
    threading.excepthook = _handle_thread_exception
    if root is not None:
        tk_root = cast(TkExceptionReporter, root)
        tk_root.report_callback_exception = _handle_tk_exception
