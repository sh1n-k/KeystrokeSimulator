"""macOS CGEventTap hotkeys: consume Option+Shift and optional runtime key.

Runs the tap on a dedicated CFRunLoop thread so detection is independent of the
Tk main loop. Returning None from the tap callback suppresses delivery to the
focused app (games), fixing observe-only polling "input eaten by game" behavior.

Requires Accessibility trust to create an active (filter) event tap. Callers
should fall back to MacKeyPollListener when is_active is False after start().
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger

from app.utils.keys import KeyUtils

EnabledProvider = Callable[[], bool]
RuntimeKeyProvider = Callable[[], str | None]
VoidCallback = Callable[[], None]

# HID keycodes: left/right Shift, left/right Option.
_MOD_KEYCODES = frozenset({56, 60, 58, 61})


class PostsActions(Protocol):
    def post(self, action: Callable[[], object]) -> None: ...


def _quartz() -> Any:
    import importlib

    return importlib.import_module("Quartz")


class MacHotkeyTapListener:
    """InputListener-compatible CGEventTap for start/stop chord + runtime key."""

    def __init__(
        self,
        session: PostsActions,
        *,
        debounce_seconds: float = 0.2,
        runtime_debounce_seconds: float = 0.25,
        start_stop_enabled: EnabledProvider | None = None,
        runtime_toggle_enabled: EnabledProvider | None = None,
        runtime_key_provider: RuntimeKeyProvider | None = None,
        on_start_stop: VoidCallback | None = None,
        on_runtime_toggle: VoidCallback | None = None,
    ) -> None:
        self._session = session
        self._debounce_seconds = max(0.0, float(debounce_seconds))
        self._runtime_debounce_seconds = max(0.0, float(runtime_debounce_seconds))
        self._start_stop_enabled = start_stop_enabled
        self._runtime_toggle_enabled = runtime_toggle_enabled
        self._runtime_key_provider = runtime_key_provider
        self._on_start_stop = on_start_stop
        self._on_runtime_toggle = on_runtime_toggle

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._tap: Any = None
        self._run_loop: Any = None
        # Keep callback/source alive for the tap lifetime (PyObjC GC).
        self._callback: Any = None
        self._source: Any = None
        self._active = False

        self._both_was_down = False
        self._latched = False
        # After a chord fires, swallow Option/Shift until both keys are up so the
        # focused app never sees a half-delivered modifier pair.
        self._swallow_mods_until_release = False
        self._last_start_stop_time = 0.0
        self._runtime_was_down = False
        self._last_runtime_time = 0.0
        self._lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._reset_state()
        ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="mac-hotkey-tap",
            args=(ready,),
            daemon=True,
        )
        self._thread.start()
        # Wait briefly for tap install so callers can choose a fallback.
        ready.wait(timeout=2.0)

    def stop(self) -> None:
        self._stop.set()
        self._active = False
        quartz = None
        try:
            quartz = _quartz()
        except Exception:
            pass
        run_loop = self._run_loop
        tap = self._tap
        if quartz is not None:
            try:
                if tap is not None:
                    quartz.CGEventTapEnable(tap, False)
            except Exception:
                pass
            try:
                if run_loop is not None:
                    quartz.CFRunLoopStop(run_loop)
            except Exception:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self._tap = None
        self._run_loop = None
        self._source = None
        self._callback = None
        self._reset_state()

    def _reset_state(self) -> None:
        with self._lock:
            self._both_was_down = False
            self._latched = False
            self._swallow_mods_until_release = False
            self._runtime_was_down = False

    def _run(self, ready: threading.Event) -> None:
        try:
            quartz = _quartz()
            mask = (
                quartz.CGEventMaskBit(quartz.kCGEventFlagsChanged)
                | quartz.CGEventMaskBit(quartz.kCGEventKeyDown)
                | quartz.CGEventMaskBit(quartz.kCGEventKeyUp)
            )

            # Bound method kept on self so the tap does not see a dangling ref.
            def callback(proxy: object, type_: int, event: object, refcon: object) -> object:
                return self._handle_event(quartz, proxy, type_, event)

            self._callback = callback
            # HID tap sees hardware earlier; session tap is the usual hotkey point.
            # Prefer session so we co-exist with other tools; still consumes for apps.
            tap = quartz.CGEventTapCreate(
                quartz.kCGSessionEventTap,
                quartz.kCGHeadInsertEventTap,
                quartz.kCGEventTapOptionDefault,
                mask,
                callback,
                None,
            )
            if tap is None:
                logger.warning(
                    "CGEventTapCreate returned None "
                    "(Accessibility permission required for Option+Shift consume)"
                )
                self._active = False
                ready.set()
                return

            self._tap = tap
            source = quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            if source is None:
                logger.warning("CFMachPortCreateRunLoopSource failed for hotkey tap")
                self._active = False
                ready.set()
                return
            self._source = source
            run_loop = quartz.CFRunLoopGetCurrent()
            self._run_loop = run_loop
            quartz.CFRunLoopAddSource(run_loop, source, quartz.kCFRunLoopCommonModes)
            quartz.CGEventTapEnable(tap, True)
            self._active = True
            ready.set()
            # Block until stop() calls CFRunLoopStop.
            while not self._stop.is_set():
                # 0.25s timeout so we can exit even if Stop is delayed.
                quartz.CFRunLoopRunInMode(quartz.kCFRunLoopDefaultMode, 0.25, False)
        except Exception:
            logger.exception("mac hotkey tap thread failed")
            self._active = False
            ready.set()
        finally:
            self._active = False
            try:
                quartz = _quartz()
                if self._source is not None and self._run_loop is not None:
                    quartz.CFRunLoopRemoveSource(
                        self._run_loop, self._source, quartz.kCFRunLoopCommonModes
                    )
            except Exception:
                pass

    def _handle_event(
        self, quartz: Any, proxy: object, type_: int, event: object
    ) -> object:
        # Re-enable if macOS disabled the tap (timeout / user input storm).
        if type_ in (
            quartz.kCGEventTapDisabledByTimeout,
            quartz.kCGEventTapDisabledByUserInput,
        ):
            tap = self._tap
            if tap is not None:
                try:
                    quartz.CGEventTapEnable(tap, True)
                except Exception:
                    logger.exception("failed to re-enable hotkey tap")
            return event

        try:
            return self._process_event(quartz, type_, event)
        except Exception:
            logger.exception("mac hotkey tap handle failed")
            return event

    def _process_event(self, quartz: Any, type_: int, event: object) -> object:
        now = time.time()
        keycode = int(
            quartz.CGEventGetIntegerValueField(event, quartz.kCGKeyboardEventKeycode)
        )

        option_down = KeyUtils.mod_key_pressed("alt", physical_only=True)
        shift_down = KeyUtils.mod_key_pressed("shift", physical_only=True)
        both_down = option_down and shift_down

        start_stop_enabled = self._is_start_stop_enabled()
        swallow_chord = False

        with self._lock:
            rising = both_down and not self._both_was_down
            if not both_down:
                self._latched = False
            self._both_was_down = both_down

            if not option_down and not shift_down:
                self._swallow_mods_until_release = False

            if (
                start_stop_enabled
                and self._on_start_stop is not None
                and rising
                and not self._latched
                and now - self._last_start_stop_time >= self._debounce_seconds
            ):
                self._last_start_stop_time = now
                self._latched = True
                self._swallow_mods_until_release = True
                self._session.post(self._safe_start_stop)

            # Suppress Option/Shift while chord is held, and after fire until
            # both keys release, so games do not see the hotkey (cause 1).
            if (
                start_stop_enabled
                and keycode in _MOD_KEYCODES
                and (both_down or self._swallow_mods_until_release)
                and type_
                in (
                    quartz.kCGEventFlagsChanged,
                    quartz.kCGEventKeyDown,
                    quartz.kCGEventKeyUp,
                )
            ):
                swallow_chord = True

        if swallow_chord:
            return None

        # Runtime toggle: consume matching keyDown when enabled.
        if type_ == quartz.kCGEventKeyDown and self._on_runtime_toggle is not None:
            autorepeat = int(
                quartz.CGEventGetIntegerValueField(
                    event, quartz.kCGKeyboardEventAutorepeat
                )
            )
            if not autorepeat and self._maybe_fire_runtime(now, keycode):
                return None

        return event

    def _is_start_stop_enabled(self) -> bool:
        if self._start_stop_enabled is None:
            return True
        try:
            return bool(self._start_stop_enabled())
        except Exception:
            logger.exception("mac start/stop enabled check failed")
            return False

    def _maybe_fire_runtime(self, now: float, keycode: int) -> bool:
        enabled = True
        if self._runtime_toggle_enabled is not None:
            try:
                enabled = bool(self._runtime_toggle_enabled())
            except Exception:
                logger.exception("mac runtime toggle enabled check failed")
                enabled = False
        if not enabled:
            with self._lock:
                self._runtime_was_down = False
            return False

        runtime_key = (
            self._runtime_key_provider() if self._runtime_key_provider else None
        )
        if not runtime_key:
            return False
        expected_code = KeyUtils.get_keycode(runtime_key)
        if expected_code is None or int(expected_code) != keycode:
            # Also accept name match via reverse map (case variants).
            name = KeyUtils.get_key_name_for_keycode(keycode)
            if not name or name.upper() != str(runtime_key).upper():
                return False

        with self._lock:
            if now - self._last_runtime_time < self._runtime_debounce_seconds:
                return True  # still consume while debouncing
            self._last_runtime_time = now
            self._runtime_was_down = True
        self._session.post(self._safe_runtime_toggle)
        return True

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
