from typing import ClassVar

from app.domain.key_codes import KeyCodes
from app.platform.system import (
    IS_MAC,
    IS_WIN,
    quartz_symbol,
    windows_windll,
)


class KeyUtils(KeyCodes):
    WINDOWS_EXTENDED_KEY_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "Left",
            "Up",
            "Right",
            "Down",
            "Delete",
            "Home",
            "End",
            "Pageup",
            "Pagedown",
            "Insert",
        }
    )

    @classmethod
    def is_extended_key(cls, key_name: str | None) -> bool:
        if not key_name or not IS_WIN:
            return False
        return key_name in cls.WINDOWS_EXTENDED_KEY_NAMES

    # macOS HID keycodes: (left, right). Prefer physical key state over modifier
    # flags so Option/Shift chords match what the user is actually holding.
    _MAC_MODIFIER_KEYCODES: ClassVar[dict[str, tuple[int, ...]]] = {
        "shift": (56, 60),
        "alt": (58, 61),
        "option": (58, 61),
        "ctrl": (59, 62),
        "control": (59, 62),
    }

    @staticmethod
    def mod_key_pressed(
        key: str, os_name: str | None = None, *, physical_only: bool = False
    ) -> bool:
        """Return whether a modifier is down.

        On macOS, physical HID keycodes (left/right) are checked first. Flag-mask
        fallback is used only when physical_only=False — chord hotkeys should pass
        physical_only=True so sticky flags cannot keep a latch armed forever.

        Physical state always uses the host OS APIs. ``os_name`` only selects the
        keycode map (e.g. Windows-compat layouts).
        """
        if IS_WIN:
            code = KeyUtils.get_keycode(key, os_name=os_name)
            return (
                (windows_windll().user32.GetAsyncKeyState(code) & 0x8000 != 0)
                if code
                else False
            )
        if IS_MAC:
            codes = KeyUtils._MAC_MODIFIER_KEYCODES.get(key.lower())
            if not codes:
                return False
            key_state = quartz_symbol("CGEventSourceKeyState")
            hid_system_state = quartz_symbol("kCGEventSourceStateHIDSystemState")
            if any(bool(key_state(hid_system_state, code)) for code in codes):
                return True
            if physical_only:
                return False
            # Fallback: flag mask when key-state is unavailable/inconsistent.
            mask_shift = quartz_symbol("kCGEventFlagMaskShift")
            mask_alt = quartz_symbol("kCGEventFlagMaskAlternate")
            mask_control = quartz_symbol("kCGEventFlagMaskControl")
            mask = {
                "shift": mask_shift,
                "alt": mask_alt,
                "option": mask_alt,
                "ctrl": mask_control,
                "control": mask_control,
            }.get(key.lower())
            if mask is None:
                return False
            event_source_flags_state = quartz_symbol("CGEventSourceFlagsState")
            return (event_source_flags_state(hid_system_state) & mask) != 0
        return False

    @staticmethod
    def key_pressed(key_name: str | None, os_name: str | None = None) -> bool:
        if not key_name:
            return False

        code = KeyUtils.get_keycode(key_name, os_name=os_name)
        if code is None:
            return False

        if IS_WIN:
            return bool(windows_windll().user32.GetAsyncKeyState(code) & 0x8000)
        if IS_MAC:
            key_state = quartz_symbol("CGEventSourceKeyState")
            hid_system_state = quartz_symbol("kCGEventSourceStateHIDSystemState")
            return bool(key_state(hid_system_state, code))
        return False
