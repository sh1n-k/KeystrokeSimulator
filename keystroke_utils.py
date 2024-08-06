import json
import logging
import os
import platform
import threading
from pathlib import Path
from typing import Optional, Dict

if platform.system() == 'Windows':
    import pygame


class WindowUtils:
    @staticmethod
    def center_window(window, width_percent=None, height_percent=None):
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()

        window.update_idletasks()  # Ensure the window has calculated its size
        window_width = (
            width_percent * screen_width if width_percent else window.winfo_width()
        )
        window_height = (
            height_percent * screen_height if height_percent else window.winfo_height()
        )

        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2

        window.geometry(f"{int(window_width)}x{int(window_height)}+{x}+{y}")

    @staticmethod
    def set_window_position(window, x_percent=0.5, y_percent=0.5):
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()

        window.update_idletasks()  # Ensure the window has calculated its size
        window_width = window.winfo_width()
        window_height = window.winfo_height()

        x = int((screen_width - window_width) * x_percent)
        y = int((screen_height - window_height) * y_percent)

        window.geometry(f"+{x}+{y}")


class KeyUtils:
    cg_key_codes = {
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
        # "tab": 48,
        "space": 49,
        # "delete": 51,
        # "escape": 53,
        "command": 55,
        # "shift": 56,
        # "capslock": 57,
        "option": 58,
        # "control": 59,
        # "rightshift": 60,
        # "rightoption": 61,
        # "rightcontrol": 62,
        # "function": 63,
        # "return": 36,
        # "f13": 105,
        # "f14": 107,
        # "f15": 113,
        # "f16": 106,
        # "f17": 64,
        # "f18": 79,
        # "f19": 80,
        # "f20": 90,
        # "left": 123,
        # "right": 124,
        # "down": 125,
        # "up": 126,
        # "home": 115,
        # "pageup": 116,
        # "pagedown": 121,
        # "end": 119,
        # "forwarddelete": 117,
        # "volumeup": 72,
        # "volumedown": 73,
        # "mute": 74,
        # "help": 114
    }

    windows_key_codes = {
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
        # "shift": 0x10,
        # "enter": 0x0D,
        "Tab": 0x09,
        # "ctrl": 0x11,
        # "alt": 0x12,
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
    }

    @staticmethod
    def get_key_list():
        return (
            KeyUtils.cg_key_codes
            if platform.system() == "Darwin"
            else KeyUtils.windows_key_codes
        )

    @staticmethod
    def get_keycode(character):
        """
        Returns the CGKeyCode value for the given character.
        """
        if character.lower() in KeyUtils.get_key_list():
            return KeyUtils.get_key_list()[character.lower()]
        else:
            return None

    @staticmethod
    def sort_cg_key_codes():
        """
        Sorts the keys from the cg_key_codes dictionary in the order of numbers, then alphabetically (a-z), and finally the function keys (f1-f12).

        Args:
            cg_key_codes (dict): The dictionary containing the key-value pairs.

        Returns:
            list: The sorted list of keys.
        """
        # Extract the keys
        keys = list(KeyUtils.get_key_list().keys())

        # Sort the keys
        # keys.sort(
        #     key=lambda x: (
        #         x.isdigit() and 0 <= int(x) <= 9,  # Sort numbers 1-9 first
        #         x.isalpha() and x.islower(),  # Sort alphabetically (a-z)
        #         x.startswith("f")
        #         and x[1:].isdigit()
        #         and 1 <= int(x[1:]) <= 12,  # Sort function keys (f1-f12)
        #         not x.isdigit()
        #         and not x.isalpha()
        #         and not x.startswith("f"),  # Sort remaining special characters
        #     ),
        #     reverse=True,
        # )

        return keys


class StateUtils:
    state_file_path = Path("./app_state.json")

    @staticmethod
    def save_main_app_state(
        process: Optional[str] = None,
        profile: Optional[str] = None,
        event_position: Optional[str] = None,
        event_position_pointer: Optional[str] = None,
        quick_position: Optional[str] = None,
    ) -> None:
        try:
            state = StateUtils.load_main_app_state() or {}
            updated = False

            if process:
                state["latest_process"] = process
                updated = True
            if profile:
                state["latest_profile"] = profile
                updated = True
            if event_position:
                state["latest_position"] = event_position
                updated = True
            if event_position_pointer:
                state["latest_position_pointer"] = event_position_pointer
                updated = True
            if quick_position:
                state["latest_quick"] = quick_position
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
    @staticmethod
    def play_sound(sound_file):
        pygame.mixer.init()
        pygame.mixer.music.load(f"{sound_file}")
        pygame.mixer.music.play()

    @staticmethod
    def play(sound_file):
        if platform.system() == "Darwin":  # macOS
            import subprocess

            subprocess.Popen(["afplay", f"{sound_file}"])

        elif platform.system() == "Windows":  # Windows
            sound_thread = threading.Thread(
                target=SoundUtils.play_sound, args=(sound_file,)
            )
            sound_thread.start()

        else:
            raise NotImplementedError(
                f"Sound playback is not implemented for {platform.system()} platform."
            )
