import json
import logging
import os
import platform
from pathlib import Path
from typing import Optional, Dict

import pygame


class WindowUtils:
    @staticmethod
    def _get_screen_dimensions(window):
        return window.winfo_screenwidth(), window.winfo_screenheight()

    @staticmethod
    def _calculate_window_size(
        window, screen_width, screen_height, width_percent, height_percent
    ):
        window.update_idletasks()
        return (
            width_percent * screen_width if width_percent else window.winfo_width(),
            height_percent * screen_height if height_percent else window.winfo_height(),
        )

    @staticmethod
    def center_window(window):
        window.update_idletasks()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        window_width = window.winfo_width()
        window_height = window.winfo_height()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        window.geometry(f"+{x}+{y}")

    @staticmethod
    def set_window_position(window, x_percent=0.5, y_percent=0.5):
        screen_width, screen_height = WindowUtils._get_screen_dimensions(window)
        window_width, window_height = WindowUtils._calculate_window_size(
            window, screen_width, screen_height, None, None
        )
        x = int((screen_width - window_width) * x_percent)
        y = int((screen_height - window_height) * y_percent)
        window.geometry(f"+{x}+{y}")
        window.update_idletasks()


class KeyUtils:
    key_codes = {
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
            "a": 0,
            "b": 11,
            "c": 8,
            "d": 2,
            "e": 14,
            "f": 3,
            "g": 5,
            "h": 4,
            "i": 34,
            "j": 38,
            "k": 40,
            "l": 37,
            "m": 46,
            "n": 45,
            "o": 31,
            "p": 35,
            "q": 12,
            "r": 15,
            "s": 1,
            "t": 17,
            "u": 32,
            "v": 9,
            "w": 13,
            "x": 7,
            "y": 16,
            "z": 6,
            ",": 43,
            ".": 47,
            "/": 44,
            ";": 41,
            "'": 39,
            "`": 50,
            "f1": 122,
            "f2": 120,
            "f3": 99,
            "f4": 118,
            "f5": 96,
            "f6": 97,
            "f7": 98,
            "f8": 100,
            "f9": 101,
            "f10": 109,
            "f11": 103,
            "f12": 111,
            "control": 59,
            "space": 49,
            "command": 55,
            "option": 58,
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
            "a": 0x41,
            "b": 0x42,
            "c": 0x43,
            "d": 0x44,
            "e": 0x45,
            "f": 0x46,
            "g": 0x47,
            "h": 0x48,
            "i": 0x49,
            "j": 0x4A,
            "k": 0x4B,
            "l": 0x4C,
            "m": 0x4D,
            "n": 0x4E,
            "o": 0x4F,
            "p": 0x50,
            "q": 0x51,
            "r": 0x52,
            "s": 0x53,
            "t": 0x54,
            "u": 0x55,
            "v": 0x56,
            "w": 0x57,
            "x": 0x58,
            "y": 0x59,
            "z": 0x5A,
            ",": 0xBC,
            ".": 0xBE,
            "/": 0xBF,
            ";": 0xBA,
            "'": 0xDE,
            "f1": 0x70,
            "f2": 0x71,
            "f3": 0x72,
            "f4": 0x73,
            "f5": 0x74,
            "f6": 0x75,
            "f7": 0x76,
            "f8": 0x77,
            "f9": 0x78,
            "f10": 0x79,
            "f11": 0x7A,
            "f12": 0x7B,
            "space": 0x20,
            "tab": 0x09,
            "left": 0x25,
            "up": 0x26,
            "right": 0x27,
            "down": 0x28,
            "delete": 0x2E,
            "backspace": 0x08,
            "home": 0x24,
            "end": 0x23,
            "pageup": 0x21,
            "pagedown": 0x22,
            "insert": 0x2D,
            "esc": 0x1B,
            "volumeup": 0xAF,
            "volumedown": 0xAE,
            "mute": 0xAD,
        },
    }

    @staticmethod
    def get_key_list():
        return KeyUtils.key_codes[platform.system().lower()]

    @staticmethod
    def get_key_name_list():
        return list(KeyUtils.key_codes[platform.system().lower()].keys())

    @staticmethod
    def get_keycode(character):
        return KeyUtils.get_key_list().get(character.lower())

    @staticmethod
    def sort_key_codes():
        return sorted(KeyUtils.get_key_list().keys())


class StateUtils:
    state_file_path = Path("./app_state.json")

    @staticmethod
    def save_main_app_state(**kwargs):
        try:
            state = StateUtils.load_main_app_state() or {}
            updated = False

            for key, value in kwargs.items():
                if value:
                    state[key] = value
                    updated = True

            if updated:
                temp_file_path = StateUtils.state_file_path.with_suffix(".tmp")
                with open(temp_file_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False)
                os.replace(temp_file_path, StateUtils.state_file_path)
        except Exception as e:
            logging.error(f"Failed to save state file: {e}")

    @staticmethod
    def load_main_app_state() -> Optional[Dict]:
        if not StateUtils.state_file_path.exists():
            return {}
        try:
            with open(StateUtils.state_file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load state file: {e}")
            return {}


class SoundUtils:
    _initialized = False

    @classmethod
    def play_sound(cls, sound_file):
        if not cls._initialized:
            pygame.mixer.init()
            cls._initialized = True

        pygame.mixer.Sound(sound_file).play()
