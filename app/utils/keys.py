from typing import ClassVar

from app.utils.system import (
    IS_MAC,
    IS_WIN,
    OS_NAME,
    quartz_symbol,
    windows_windll,
)

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
                (windows_windll().user32.GetAsyncKeyState(code) & 0x8000 != 0)
                if code
                else False
            )
        elif IS_MAC:
            mask_shift = quartz_symbol("kCGEventFlagMaskShift")
            mask_alt = quartz_symbol("kCGEventFlagMaskAlternate")
            mask_control = quartz_symbol("kCGEventFlagMaskControl")
            mask = {
                "shift": mask_shift,
                "alt": mask_alt,
                "ctrl": mask_control,
            }.get(key.lower())
            event_source_flags_state = quartz_symbol("CGEventSourceFlagsState")
            hid_system_state = quartz_symbol("kCGEventSourceStateHIDSystemState")
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
            return bool(windows_windll().user32.GetAsyncKeyState(code) & 0x8000)
        elif IS_MAC:
            key_state = quartz_symbol("CGEventSourceKeyState")
            hid_system_state = quartz_symbol("kCGEventSourceStateHIDSystemState")
            return bool(key_state(hid_system_state, code))
        return False
