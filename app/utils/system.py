import json
import os
import platform
import ast
import sys
import threading
import ctypes
import importlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Protocol, cast

from loguru import logger

OS_NAME = platform.system().lower()
IS_WIN = OS_NAME == "windows"
IS_MAC = OS_NAME == "darwin"
ProcessInfo = tuple[str, int, list[str] | None]


class TkExceptionReporter(Protocol):
    report_callback_exception: Callable[
        [type[BaseException], BaseException, TracebackType | None], None
    ]


class WindowLike(Protocol):
    def update_idletasks(self) -> None: ...
    def winfo_screenwidth(self) -> int: ...
    def winfo_screenheight(self) -> int: ...
    def winfo_width(self) -> int: ...
    def winfo_height(self) -> int: ...
    def geometry(self, new_geometry: str) -> object: ...


def _platform_module(name: str) -> Any:
    return importlib.import_module(name)


def _windows_windll() -> Any:
    return ctypes.__dict__["windll"]


def _quartz_symbol(name: str) -> Any:
    return _platform_module("Quartz").__dict__[name]


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


class WindowUtils:
    @staticmethod
    def center_window(win: object) -> None:
        window = cast(WindowLike, win)
        window.update_idletasks()
        x = (window.winfo_screenwidth() - window.winfo_width()) // 2
        y = (window.winfo_screenheight() - window.winfo_height()) // 2
        window.geometry(f"+{x}+{y}")

    @staticmethod
    def set_window_position(win: object, xp: float = 0.5, yp: float = 0.5) -> None:
        window = cast(WindowLike, win)
        window.update_idletasks()
        x = int((window.winfo_screenwidth() - window.winfo_width()) * xp)
        y = int((window.winfo_screenheight() - window.winfo_height()) * yp)
        window.geometry(f"+{x}+{y}")
        window.update_idletasks()


class MonitorUtils:
    @staticmethod
    def get_primary_size() -> tuple[int, int]:
        if IS_MAC:
            appkit = _platform_module("AppKit")
            frame = appkit.NSScreen.screens()[0].frame()
            return int(frame.size.width), int(frame.size.height)
        if IS_WIN:
            try:
                _windows_windll().shcore.SetProcessDpiAwareness(2)
            except OSError:
                pass
            win32api = _platform_module("win32api")
            return win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
        raise RuntimeError(f"Unsupported platform: {OS_NAME}")


class KeyUtils:
    _KEY_MAPS: ClassVar[dict[str, dict[str, int]]] = {
        "darwin": {
            "1": 18,
            "2": 19,
            "3": 20,
            "4": 21,
            "5": 23,
            "6": 22,
            "7": 26,
            "8": 28,
            "9": 25,
            "0": 29,
            "=": 24,
            "-": 27,
            "[": 33,
            "]": 30,
            "\\": 42,
            ";": 41,
            "'": 39,
            "`": 50,
            ",": 43,
            ".": 47,
            "/": 44,
            "A": 0,
            "B": 11,
            "C": 8,
            "D": 2,
            "E": 14,
            "F": 3,
            "G": 5,
            "H": 4,
            "I": 34,
            "J": 38,
            "K": 40,
            "L": 37,
            "M": 46,
            "N": 45,
            "O": 31,
            "P": 35,
            "Q": 12,
            "R": 15,
            "S": 1,
            "T": 17,
            "U": 32,
            "V": 9,
            "W": 13,
            "X": 7,
            "Y": 16,
            "Z": 6,
            "Space": 49,
            "Tab": 48,
            "Esc": 53,
            "Enter": 36,
            "Backspace": 51,
            "F1": 122,
            "F2": 120,
            "F3": 99,
            "F4": 118,
            "F5": 96,
            "F6": 97,
            "F7": 98,
            "F8": 100,
            "F9": 101,
            "F10": 109,
            "F11": 103,
            "F12": 111,
            "Control": 59,
            "Command": 55,
            "Option": 58,
            "Shift": 56,
        },
        "windows": {
            "1": 0x31,
            "2": 0x32,
            "3": 0x33,
            "4": 0x34,
            "5": 0x35,
            "6": 0x36,
            "7": 0x37,
            "8": 0x38,
            "9": 0x39,
            "0": 0x30,
            "=": 0xBB,
            "-": 0xBD,
            "[": 0xDB,
            "]": 0xDD,
            "\\": 0xDC,
            ";": 0xBA,
            "'": 0xDE,
            ",": 0xBC,
            ".": 0xBE,
            "/": 0xBF,
            "A": 0x41,
            "B": 0x42,
            "C": 0x43,
            "D": 0x44,
            "E": 0x45,
            "F": 0x46,
            "G": 0x47,
            "H": 0x48,
            "I": 0x49,
            "J": 0x4A,
            "K": 0x4B,
            "L": 0x4C,
            "M": 0x4D,
            "N": 0x4E,
            "O": 0x4F,
            "P": 0x50,
            "Q": 0x51,
            "R": 0x52,
            "S": 0x53,
            "T": 0x54,
            "U": 0x55,
            "V": 0x56,
            "W": 0x57,
            "X": 0x58,
            "Y": 0x59,
            "Z": 0x5A,
            "Space": 0x20,
            "Tab": 0x09,
            "Esc": 0x1B,
            "F1": 0x70,
            "F2": 0x71,
            "F3": 0x72,
            "F4": 0x73,
            "F5": 0x74,
            "F6": 0x75,
            "F7": 0x76,
            "F8": 0x77,
            "F9": 0x78,
            "F10": 0x79,
            "F11": 0x7A,
            "F12": 0x7B,
            "Left": 0x25,
            "Up": 0x26,
            "Right": 0x27,
            "Down": 0x28,
            "Delete": 0x2E,
            "Backspace": 0x08,
            "Home": 0x24,
            "End": 0x23,
            "Pageup": 0x21,
            "Pagedown": 0x22,
            "Insert": 0x2D,
            "Shift": 0x10,
            "Alt": 0x12,
            "Ctrl": 0x11,
        },
    }
    CURRENT_KEYS = _KEY_MAPS.get(OS_NAME, {})

    @classmethod
    def get_key_list(cls) -> dict[str, int]:
        return cls.CURRENT_KEYS

    @classmethod
    def get_key_name_list(cls) -> list[str]:
        return list(cls.CURRENT_KEYS.keys())

    @classmethod
    def get_key_name_for_keycode(cls, code: int | None) -> str | None:
        if code is None:
            return None

        for name, mapped_code in cls.CURRENT_KEYS.items():
            if mapped_code == code:
                return name
        return None

    @classmethod
    def get_keycode(cls, char: str) -> int | None:
        return cls.CURRENT_KEYS.get(char.capitalize())

    @staticmethod
    def mod_key_pressed(key: str) -> bool:
        if IS_WIN:
            code = KeyUtils.get_keycode(key)
            return (
                (_windows_windll().user32.GetAsyncKeyState(code) & 0x8000 != 0)
                if code
                else False
            )
        elif IS_MAC:
            mask_shift = _quartz_symbol("kCGEventFlagMaskShift")
            mask_alt = _quartz_symbol("kCGEventFlagMaskAlternate")
            mask_control = _quartz_symbol("kCGEventFlagMaskControl")
            mask = {
                "shift": mask_shift,
                "alt": mask_alt,
                "ctrl": mask_control,
            }.get(key.lower())
            event_source_flags_state = _quartz_symbol("CGEventSourceFlagsState")
            hid_system_state = _quartz_symbol("kCGEventSourceStateHIDSystemState")
            return (
                (event_source_flags_state(hid_system_state) & mask) != 0
                if mask
                else False
            )
        return False

    @staticmethod
    def key_pressed(key_name: str | None) -> bool:
        if not key_name:
            return False

        code = KeyUtils.get_keycode(key_name)
        if code is None:
            return False

        if IS_WIN:
            return bool(_windows_windll().user32.GetAsyncKeyState(code) & 0x8000)
        elif IS_MAC:
            key_state = _quartz_symbol("CGEventSourceKeyState")
            hid_system_state = _quartz_symbol("kCGEventSourceStateHIDSystemState")
            return bool(key_state(hid_system_state, code))
        return False


class StateUtils:
    path = Path("./app_state.json")

    @classmethod
    def save_main_app_state(cls, **kwargs: object) -> None:
        try:
            data = cls.load_main_app_state()
            data.update({k: v for k, v in kwargs.items() if v is not None})
            tmp = cls.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            tmp.replace(cls.path)
        except Exception as e:
            logger.error(f"Save state failed: {e}")

    @classmethod
    def load_main_app_state(cls) -> dict[str, object]:
        if not cls.path.exists():
            return {}
        try:
            data: object = json.loads(cls.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.error(
                    f"Load state failed: expected object, got {type(data).__name__}"
                )
                return {}
            raw_data = cast(Mapping[object, object], data)
            return {str(k): v for k, v in raw_data.items()}
        except Exception as e:
            logger.error(f"Load state failed: {e}")
            return {}

    @staticmethod
    def parse_slash_int_pair(raw: object) -> tuple[int, int] | None:
        if raw is None:
            return None
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            seq = cast(Sequence[object], raw)
            if len(seq) < 2:
                return None
            first, second = seq[0], seq[1]
            if not isinstance(first, (int, float, str)) or not isinstance(
                second, (int, float, str)
            ):
                return None
            try:
                return (int(first), int(second))
            except (TypeError, ValueError, OverflowError):
                return None
        if not isinstance(raw, str):
            return None
        parts = raw.split("/", 1)
        if len(parts) != 2:
            return None
        try:
            return (int(parts[0]), int(parts[1]))
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def parse_position_tuple(raw: object) -> tuple[int, int] | None:
        if raw is None:
            return None
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            seq = cast(Sequence[object], raw)
            if len(seq) < 2:
                return None
            first, second = seq[0], seq[1]
            if not isinstance(first, (int, float, str)) or not isinstance(
                second, (int, float, str)
            ):
                return None
            try:
                return (int(first), int(second))
            except (TypeError, ValueError, OverflowError):
                return None
        if not isinstance(raw, str):
            return None
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return None
        if not isinstance(parsed, Sequence) or isinstance(
            parsed, (str, bytes, bytearray)
        ):
            return None
        seq = cast(Sequence[object], parsed)
        if len(seq) < 2:
            return None
        first, second = seq[0], seq[1]
        if not isinstance(first, (int, float, str)) or not isinstance(
            second, (int, float, str)
        ):
            return None
        try:
            return (int(first), int(second))
        except (TypeError, ValueError, OverflowError):
            return None


class PermissionUtils:
    @staticmethod
    def has_screen_capture_access() -> bool:
        if not IS_MAC:
            return True
        try:
            return bool(_quartz_symbol("CGPreflightScreenCaptureAccess")())
        except Exception:
            return False

    @staticmethod
    def has_accessibility_access() -> bool:
        if not IS_MAC:
            return True
        try:
            application_services = _platform_module("ApplicationServices")
            return bool(application_services.AXIsProcessTrusted())
        except Exception:
            return False

    @staticmethod
    def missing_macos_permissions() -> list[str]:
        if not IS_MAC:
            return []

        missing: list[str] = []
        if not PermissionUtils.has_screen_capture_access():
            missing.append("screen")
        if not PermissionUtils.has_accessibility_access():
            missing.append("accessibility")
        return missing


class ProcessCollector:
    @staticmethod
    def get() -> list[ProcessInfo]:
        return ProcessCollector._get_mac() if IS_MAC else ProcessCollector._get_win()

    @staticmethod
    def _get_mac() -> list[ProcessInfo]:
        appkit = _platform_module("AppKit")
        return [
            (str(app.localizedName() or ""), int(app.processIdentifier()), None)
            for app in appkit.NSWorkspace.sharedWorkspace().runningApplications()
            if app.activationPolicy() == 0
        ]

    @staticmethod
    def _get_win() -> list[ProcessInfo]:
        win32api = _platform_module("win32api")
        win32gui = _platform_module("win32gui")
        win32process = _platform_module("win32process")
        procs: dict[int, str] = {}
        wins: dict[int, list[str]] = {}

        def cb(hwnd: int, _extra: object) -> bool:
            if win32gui.IsWindowVisible(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in procs:
                    try:
                        h = win32api.OpenProcess(0x1000, False, pid)
                        module_path = win32process.GetModuleFileNameEx(h, 0)
                        procs[pid] = os.path.basename(str(module_path)).split(".")[0]
                        wins[pid] = [win32gui.GetWindowText(hwnd)]
                        win32api.CloseHandle(h)
                    except Exception as exc:
                        logger.debug(f"Window process lookup failed for pid {pid}: {exc}")
                elif (t := win32gui.GetWindowText(hwnd)) not in wins[pid]:
                    wins[pid].append(t)
            return True

        win32gui.EnumWindows(cb, None)
        return [(name, pid, wins[pid]) for pid, name in procs.items()]


class ProcessUtils:
    @staticmethod
    def is_process_active(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            if IS_WIN:
                win32gui = _platform_module("win32gui")
                win32process = _platform_module("win32process")
                if not (hwnd := win32gui.GetForegroundWindow()):
                    return False
                return bool(pid == win32process.GetWindowThreadProcessId(hwnd)[1])
            elif IS_MAC:
                appkit = _platform_module("AppKit")
                app = appkit.NSWorkspace.sharedWorkspace().activeApplication()
                return bool(app and app.get("NSApplicationProcessIdentifier") == pid)
        except Exception as exc:
            logger.debug(f"Active process check failed for pid {pid}: {exc}")
        return False
