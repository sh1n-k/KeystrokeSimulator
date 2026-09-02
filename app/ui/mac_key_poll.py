"""Background macOS key-state poller for Option+Shift / runtime toggle.

Runs chord detection on a dedicated thread (not Tk after, not pynput). Only
posts rare side-effect callbacks to InputListenerSession so the Tk action
queue cannot fill with 60+ samples/sec and stall after several toggles.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

from loguru import logger

from app.utils.keys import KeyUtils


class PostsActions(Protocol):
    def post(self, action: Callable[[], object]) -> None: ...


EnabledProvider = Callable[[], bool]
RuntimeKeyProvider = Callable[[], str | None]
VoidCallback = Callable[[], None]


class MacKeyPollListener:
    """InputListener-compatible background poller (start/stop)."""

    def __init__(
        self,
        session: PostsActions,
        *,
        interval_ms: int = 15,
        hold_seconds: float = 0.03,
        debounce_seconds: float = 0.2,
        runtime_debounce_seconds: float = 0.25,
        start_stop_enabled: EnabledProvider | None = None,
        runtime_toggle_enabled: EnabledProvider | None = None,
        runtime_key_provider: RuntimeKeyProvider | None = None,
        on_start_stop: VoidCallback | None = None,
        on_runtime_toggle: VoidCallback | None = None,
    ) -> None:
        self._session = session
        self._interval_s = max(0.005, float(interval_ms) / 1000.0)
        self._hold_seconds = max(0.0, float(hold_seconds))
        self._debounce_seconds = max(0.0, float(debounce_seconds))
        self._runtime_debounce_seconds = max(0.0, float(runtime_debounce_seconds))
        self._start_stop_enabled = start_stop_enabled
        self._runtime_toggle_enabled = runtime_toggle_enabled
        self._runtime_key_provider = runtime_key_provider
        self._on_start_stop = on_start_stop
        self._on_runtime_toggle = on_runtime_toggle

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Chord state (background thread only).
        self._chord_since: float | None = None
        self._latched = False
        self._last_start_stop_time = 0.0
        self._runtime_was_down = False
        self._last_runtime_time = 0.0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._reset_chord_state()
        self._thread = threading.Thread(
            target=self._run,
            name="mac-key-poll",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._reset_chord_state()

    def _reset_chord_state(self) -> None:
        self._chord_since = None
        self._latched = False
        self._runtime_was_down = False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("mac key poll tick failed")
            if self._stop.wait(self._interval_s):
                break

    def _tick(self) -> None:
        now = time.time()
        # physical_only: ignore sticky modifier flags that outlive key-up and
        # would otherwise keep the chord latched (swallowed later toggles).
        option_down = KeyUtils.mod_key_pressed("alt", physical_only=True)
        shift_down = KeyUtils.mod_key_pressed("shift", physical_only=True)
        self._update_start_stop_chord(now, option_down, shift_down)

        runtime_key = (
            self._runtime_key_provider() if self._runtime_key_provider else None
        )
        runtime_down = bool(runtime_key and KeyUtils.key_pressed(runtime_key))
        self._update_runtime_toggle(now, runtime_down)

    def _update_start_stop_chord(
        self, now: float, option_down: bool, shift_down: bool
    ) -> None:
        enabled = True
        if self._start_stop_enabled is not None:
            try:
                enabled = bool(self._start_stop_enabled())
            except Exception:
                logger.exception("mac start/stop enabled check failed")
                enabled = False
        if not enabled or self._on_start_stop is None:
            self._chord_since = None
            self._latched = False
            return

        both_down = option_down and shift_down
        # Re-arm as soon as the chord breaks (either key up). Requiring both
        # keys fully up swallowed the next press when one modifier was still
        # held or OS state lagged on a single key.
        if not both_down:
            self._chord_since = None
            self._latched = False
            return

        if self._latched:
            return

        if self._chord_since is None:
            self._chord_since = now
            return

        if now - self._chord_since < self._hold_seconds:
            return
        if now - self._last_start_stop_time < self._debounce_seconds:
            return

        self._last_start_stop_time = now
        self._latched = True
        self._chord_since = None
        self._session.post(self._safe_start_stop)

    def _update_runtime_toggle(self, now: float, runtime_down: bool) -> None:
        if self._on_runtime_toggle is None:
            self._runtime_was_down = False
            return

        enabled = True
        if self._runtime_toggle_enabled is not None:
            try:
                enabled = bool(self._runtime_toggle_enabled())
            except Exception:
                logger.exception("mac runtime toggle enabled check failed")
                enabled = False

        pressed = enabled and runtime_down
        if (
            pressed
            and not self._runtime_was_down
            and now - self._last_runtime_time >= self._runtime_debounce_seconds
        ):
            self._last_runtime_time = now
            self._session.post(self._safe_runtime_toggle)
        self._runtime_was_down = pressed

    def _safe_start_stop(self) -> None:
        try:
            if self._on_start_stop is not None:
                self._on_start_stop()
        except Exception:
            logger.exception("mac start/stop callback failed")

    def _safe_runtime_toggle(self) -> None:
        try:
            if self._on_runtime_toggle is not None:
                self._on_runtime_toggle()
        except Exception:
            logger.exception("mac runtime toggle callback failed")
