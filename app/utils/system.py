import ctypes
import importlib
import os
import platform
import subprocess
from typing import Any, ClassVar

from loguru import logger

OS_NAME = platform.system().lower()
IS_WIN = OS_NAME == "windows"
IS_MAC = OS_NAME == "darwin"
ProcessInfo = tuple[str, int, list[str] | None]


def _platform_module(name: str) -> Any:
    return importlib.import_module(name)


def windows_windll() -> Any:
    return ctypes.__dict__["windll"]


def quartz_symbol(name: str) -> Any:
    return getattr(_platform_module("Quartz"), name)


class MonitorUtils:
    @staticmethod
    def get_primary_size() -> tuple[int, int]:
        if IS_MAC:
            appkit = _platform_module("AppKit")
            frame = appkit.NSScreen.screens()[0].frame()
            return int(frame.size.width), int(frame.size.height)
        if IS_WIN:
            try:
                windows_windll().shcore.SetProcessDpiAwareness(2)
            except OSError:
                pass
            win32api = _platform_module("win32api")
            return win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
        raise RuntimeError(f"Unsupported platform: {OS_NAME}")


class PermissionUtils:
    _MACOS_PERMISSION_SETTING_URLS: ClassVar[dict[str, str]] = {
        "screen": (
            "x-apple.systempreferences:"
            "com.apple.preference.security?Privacy_ScreenCapture"
        ),
        "accessibility": (
            "x-apple.systempreferences:"
            "com.apple.preference.security?Privacy_Accessibility"
        ),
    }

    @staticmethod
    def has_screen_capture_access() -> bool:
        if not IS_MAC:
            return True
        try:
            return bool(quartz_symbol("CGPreflightScreenCaptureAccess")())
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

    @staticmethod
    def open_macos_permission_settings(permission: str) -> bool:
        if not IS_MAC:
            return False

        url = PermissionUtils._MACOS_PERMISSION_SETTING_URLS.get(permission)
        if url is None:
            return False

        try:
            subprocess.Popen(["open", url])
        except OSError as exc:
            logger.warning(f"Failed to open macOS permission settings: {exc}")
            return False
        return True


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
