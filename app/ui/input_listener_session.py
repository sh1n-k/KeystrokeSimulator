from __future__ import annotations

import queue
from collections.abc import Callable
from typing import Protocol

from loguru import logger


class InputListener(Protocol):
    def start(self) -> object: ...
    def stop(self) -> object: ...


class TkScheduler(Protocol):
    def after(self, ms: int, func: Callable[[], object], /) -> str: ...
    def after_cancel(self, after_id: str, /) -> object: ...


class InputListenerSession:
    """Own global listeners and marshal their actions onto the Tk thread."""

    def __init__(self, root: TkScheduler, interval_ms: int = 25) -> None:
        self.root = root
        self.interval_ms = interval_ms
        self._actions: queue.SimpleQueue[Callable[[], object]] = queue.SimpleQueue()
        self._listeners: list[InputListener] = []
        self._after_id: str | None = None
        self._active = False
        self._draining = False

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        if not self._draining:
            self._drain()

    def add(self, listener: InputListener) -> InputListener:
        self._listeners.append(listener)
        listener.start()
        return listener

    def post(self, action: Callable[[], object]) -> None:
        if self._active:
            self._actions.put(action)

    def _drain(self) -> None:
        if not self._active or self._draining:
            return
        self._draining = True
        self._after_id = None
        try:
            while True:
                try:
                    action = self._actions.get_nowait()
                except queue.Empty:
                    break
                try:
                    action()
                except Exception:
                    logger.exception("Input listener action failed")
        finally:
            self._draining = False
            if self._active:
                self._after_id = self.root.after(self.interval_ms, self._drain)

    def stop(self) -> None:
        self._active = False
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self._listeners.clear()
        while True:
            try:
                self._actions.get_nowait()
            except queue.Empty:
                break
