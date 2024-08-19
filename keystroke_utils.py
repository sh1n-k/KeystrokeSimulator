import json
import logging
import os
import platform
from pathlib import Path
import subprocess
from threading import Thread
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
            ",": 43,
            ".": 47,
            "/": 44,
            ";": 41,
            "'": 39,
            "`": 50,
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
            "Space": 49,
            "Command": 55,
            "Option": 58,
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
            ",": 0xBC,
            ".": 0xBE,
            "/": 0xBF,
            ";": 0xBA,
            "'": 0xDE,
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
            "Space": 0x20,
            "Tab": 0x09,
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
            "Esc": 0x1B,
            "VolumeUp": 0xAF,
            "VolumeDown": 0xAE,
            "Mute": 0xAD,
        },
    }

    @staticmethod
    def get_key_list():
        return KeyUtils.key_codes[platform.system().lower()]

    @staticmethod
    def get_key_name_list():
        return list(KeyUtils.key_codes[platform.system().lower()].keys())

    @staticmethod
    def get_keycode(character: str):
        return KeyUtils.get_key_list().get(character.capitalize())


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
    _play_sound_method = None
    _loaded_sounds = {}

    @staticmethod
    def _play_sound_mac(sound_file):
        def run_afplay():
            try:
                subprocess.run(["afplay", sound_file])
            except Exception as e:
                print(f"Failed to play sound on macOS: {e}")

        thread = Thread(target=run_afplay, daemon=True)
        thread.start()

    @classmethod
    def _play_sound_default(cls, sound_file):
        if sound_file not in cls._loaded_sounds:
            cls._loaded_sounds[sound_file] = pygame.mixer.Sound(sound_file)
        cls._loaded_sounds[sound_file].play()

    @classmethod
    def initialize(cls):
        if platform.system() == "Darwin":
            cls._play_sound_method = cls._play_sound_mac
        else:
            pygame.mixer.init()
            cls._play_sound_method = cls._play_sound_default

    @classmethod
    def play_sound(cls, sound_file):
        if cls._play_sound_method is None:
            raise RuntimeError(
                "SoundUtils not initialized. Call SoundUtils.initialize() first."
            )
        cls._play_sound_method(sound_file)
