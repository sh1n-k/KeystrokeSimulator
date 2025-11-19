import json
import os
import sys
import platform
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict

import pygame
from loguru import logger

# OS-specific imports & Constants
OS_NAME = platform.system().lower()
IS_WIN = OS_NAME == "windows"
IS_MAC = OS_NAME == "darwin"

if IS_WIN:
    import ctypes
    import win32api
    import win32gui
    import win32process
    from win32process import GetWindowThreadProcessId, GetModuleFileNameEx
elif IS_MAC:
    import AppKit
    from Quartz import (
        kCGEventFlagMaskShift,
        kCGEventFlagMaskAlternate,
        kCGEventFlagMaskControl,
        CGEventSourceFlagsState,
        kCGEventSourceStateHIDSystemState,
    )


class WindowUtils:
    @staticmethod
    def center_window(win):
        win.update_idletasks()
        x = (win.winfo_screenwidth() - win.winfo_width()) // 2
        y = (win.winfo_screenheight() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")

    @staticmethod
    def set_window_position(win, xp=0.5, yp=0.5):
        win.update_idletasks()
        x = int((win.winfo_screenwidth() - win.winfo_width()) * xp)
        y = int((win.winfo_screenheight() - win.winfo_height()) * yp)
        win.geometry(f"+{x}+{y}")
        win.update_idletasks()


class KeyUtils:
    _KEY_MAPS = {
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
    def get_key_list(cls):
        return cls.CURRENT_KEYS

    @classmethod
    def get_key_name_list(cls):
        return list(cls.CURRENT_KEYS.keys())

    @classmethod
    def get_keycode(cls, char: str):
        return cls.CURRENT_KEYS.get(char.capitalize())

    @staticmethod
    def mod_key_pressed(key: str) -> bool:
        if IS_WIN:
            code = KeyUtils.get_keycode(key)
            return (
                (ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000 != 0)
                if code
                else False
            )
        elif IS_MAC:
            mask = {
                "shift": kCGEventFlagMaskShift,
                "alt": kCGEventFlagMaskAlternate,
                "ctrl": kCGEventFlagMaskControl,
            }.get(key.lower())
            return (
                (CGEventSourceFlagsState(kCGEventSourceStateHIDSystemState) & mask) != 0
                if mask
                else False
            )
        return False


class StateUtils:
    path = Path("./app_state.json")

    @classmethod
    def save_main_app_state(cls, **kwargs):
        try:
            data = cls.load_main_app_state()
            data.update({k: v for k, v in kwargs.items() if v})
            tmp = cls.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            tmp.replace(cls.path)
        except Exception as e:
            logger.error(f"Save state failed: {e}")

    @classmethod
    def load_main_app_state(cls) -> Dict:
        if not cls.path.exists():
            return {}
        try:
            return json.loads(cls.path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Load state failed: {e}")
            return {}


class SoundUtils:
    _sounds = {}
    _inited = False

    @classmethod
    def initialize(cls):
        if not IS_MAC:
            pygame.mixer.init()
        cls._inited = True

    @classmethod
    def play_sound(cls, file):
        if not cls._inited:
            raise RuntimeError("SoundUtils not initialized")
        if IS_MAC:
            threading.Thread(
                target=lambda: subprocess.run(
                    ["afplay", file], stderr=subprocess.DEVNULL
                ),
                daemon=True,
            ).start()
        else:
            if file not in cls._sounds:
                cls._sounds[file] = pygame.mixer.Sound(file)
            cls._sounds[file].play()


class ProcessCollector:
    @staticmethod
    def get():
        return ProcessCollector._get_mac() if IS_MAC else ProcessCollector._get_win()

    @staticmethod
    def _get_mac():
        return [
            (app.localizedName(), app.processIdentifier(), None)
            for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
            if app.activationPolicy() == 0
        ]

    @staticmethod
    def _get_win():
        procs, wins = {}, {}

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                _, pid = GetWindowThreadProcessId(hwnd)
                if pid not in procs:
                    try:
                        h = win32api.OpenProcess(0x1000, False, pid)
                        procs[pid] = os.path.basename(GetModuleFileNameEx(h, 0)).split(
                            "."
                        )[0]
                        wins[pid] = [win32gui.GetWindowText(hwnd)]
                        win32api.CloseHandle(h)
                    except Exception:
                        pass
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
                if not (hwnd := win32gui.GetForegroundWindow()):
                    return False
                return pid == GetWindowThreadProcessId(hwnd)[1]
            elif IS_MAC:
                app = AppKit.NSWorkspace.sharedWorkspace().activeApplication()
                return app and app.get("NSApplicationProcessIdentifier") == pid
        except Exception:
            pass
        return False
