from __future__ import annotations

import queue
import selectors
import socket
import threading
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger

from app.utils.system import ResponsivenessActivity


class InputListener(Protocol):
    def start(self) -> object: ...
    def stop(self) -> object: ...


class TkScheduler(Protocol):
    def after(self, ms: int, func: Callable[[], object], /) -> str: ...
    def after_cancel(self, after_id: str, /) -> object: ...
    # Optional on some Tk builds; file type is platform-specific (socket fd).
    def createfilehandler(
        self, file: Any, mask: int, func: Callable[..., object], /
    ) -> Any: ...
    def deletefilehandler(self, file: Any, /) -> Any: ...


class InputListenerSession:
    """Own global listeners and marshal their actions onto the Tk thread.

    Hotkey posts use a socketpair filehandler wake on macOS so the Tk loop is
    kicked even when the window is backgrounded (cause 2), with after(0) as
    fallback. Optional ResponsivenessActivity reduces App Nap timer coalescing.
    """

    def __init__(self, root: TkScheduler, interval_ms: int = 10) -> None:
        self.root = root
        # Idle pump cadence; posts also request an immediate wake.
        self.interval_ms = interval_ms
        self._actions: queue.SimpleQueue[Callable[[], object]] = queue.SimpleQueue()
        self._listeners: list[InputListener] = []
        self._after_id: str | None = None
        self._active = False
        self._draining = False
        self._kick_lock = threading.Lock()
        self._kick_scheduled = False
        self._wake_r: socket.socket | None = None
        self._wake_w: socket.socket | None = None
        self._filehandler_installed = False
        self._responsiveness = ResponsivenessActivity()
        self._responsiveness_held = False

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._ensure_wake_pipe()
        if not self._draining:
            self._drain()

    def begin_responsiveness(self) -> None:
        """Keep process timers responsive while macOS hotkeys are armed."""
        if self._responsiveness_held:
            return
        self._responsiveness.begin()
        self._responsiveness_held = True

    def end_responsiveness(self) -> None:
        if not self._responsiveness_held:
            return
        self._responsiveness_held = False
        self._responsiveness.end()

    def add(self, listener: InputListener, *, started: bool = False) -> InputListener:
        self._listeners.append(listener)
        if not started:
            listener.start()
        return listener

    def post(self, action: Callable[[], object]) -> None:
        if not self._active:
            return
        self._actions.put(action)
        # Prefer socket wake (works when backgrounded); also schedule after(0).
        self._wake()
        self._schedule_kick()

    def _ensure_wake_pipe(self) -> None:
        if self._wake_r is not None:
            return
        # Socketpair + createfilehandler is the reliable bg wake on macOS/Unix.
        # Skip on platforms without the Tk hook.
        if not hasattr(self.root, "createfilehandler"):
            return
        try:
            wake_r, wake_w = socket.socketpair()
            wake_r.setblocking(False)
            wake_w.setblocking(False)
            self._wake_r = wake_r
            self._wake_w = wake_w
            # tk.READABLE == 1 on Tk; use selectors.EVENT_READ value (1) as mask.
            mask = getattr(self.root, "READABLE", selectors.EVENT_READ)
            self.root.createfilehandler(wake_r, mask, self._on_wake_readable)
            self._filehandler_installed = True
        except Exception:
            logger.debug("InputListenerSession wake pipe unavailable", exc_info=True)
            self._cleanup_wake_pipe()

    def _cleanup_wake_pipe(self) -> None:
        wake_r = self._wake_r
        wake_w = self._wake_w
        self._wake_r = None
        self._wake_w = None
        if self._filehandler_installed and wake_r is not None:
            try:
                self.root.deletefilehandler(wake_r)
            except Exception:
                pass
        self._filehandler_installed = False
        for sock in (wake_r, wake_w):
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def _wake(self) -> None:
        wake_w = self._wake_w
        if wake_w is None:
            return
        try:
            wake_w.send(b"\0")
        except BlockingIOError:
            pass
        except Exception:
            pass

    def _on_wake_readable(self, *args: object) -> None:
        wake_r = self._wake_r
        if wake_r is not None:
            try:
                while True:
                    if not wake_r.recv(64):
                        break
            except BlockingIOError:
                pass
            except Exception:
                pass
        with self._kick_lock:
            self._kick_scheduled = False
        self._drain()

    def _schedule_kick(self) -> None:
        with self._kick_lock:
            if not self._active or self._draining or self._kick_scheduled:
                return
            self._kick_scheduled = True
        try:
            self.root.after(0, self._kicked_drain)
        except Exception:
            with self._kick_lock:
                self._kick_scheduled = False

    def _kicked_drain(self) -> None:
        with self._kick_lock:
            self._kick_scheduled = False
        self._drain()

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
        with self._kick_lock:
            self._kick_scheduled = False
        self.end_responsiveness()
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
        self._cleanup_wake_pipe()
        while True:
            try:
                self._actions.get_nowait()
            except queue.Empty:
                break
