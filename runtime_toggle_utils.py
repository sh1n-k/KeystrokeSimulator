import platform
from typing import Iterable

from i18n import txt
from keystroke_models import EventModel, ProfileModel
from keystroke_utils import KeyUtils


WHEEL_UP_TRIGGER = "W_UP"
WHEEL_DOWN_TRIGGER = "W_DN"
MOUSE_BUTTON_3_TRIGGER = "MB_3"
MOUSE_BUTTON_4_TRIGGER = "MB_4"
MOUSE_TRIGGER_TOKENS = (
    WHEEL_UP_TRIGGER,
    WHEEL_DOWN_TRIGGER,
    MOUSE_BUTTON_3_TRIGGER,
    MOUSE_BUTTON_4_TRIGGER,
)
RUNTIME_TOGGLE_DEBOUNCE_SECONDS = 0.25
RUNTIME_TOGGLE_SCROLL_GESTURE_SECONDS = 0.75


_RUNTIME_TOGGLE_CAPTURE_ALIASES = {
    "GRAVE": "`",
    "QUOTELEFT": "`",
    "ASCIITILDE": "`",
    "DEAD_GRAVE": "`",
    "~": "`",
    "BACKSLASH": "\\",
    "YEN": "\\",
    "WON": "\\",
    "KOREAN_WON": "\\",
    "₩": "\\",
    "￦": "\\",
}

_RUNTIME_TOGGLE_HANGUL_2SET_ALIASES = {
    "ㅂ": "Q",
    "ㅃ": "Q",
    "ㅈ": "W",
    "ㅉ": "W",
    "ㄷ": "E",
    "ㄸ": "E",
    "ㄱ": "R",
    "ㄲ": "R",
    "ㅅ": "T",
    "ㅆ": "T",
    "ㅛ": "Y",
    "ㅕ": "U",
    "ㅑ": "I",
    "ㅐ": "O",
    "ㅒ": "O",
    "ㅔ": "P",
    "ㅖ": "P",
    "ㅁ": "A",
    "ㄴ": "S",
    "ㅇ": "D",
    "ㄹ": "F",
    "ㅎ": "G",
    "ㅗ": "H",
    "ㅓ": "J",
    "ㅏ": "K",
    "ㅣ": "L",
    "ㅋ": "Z",
    "ㅌ": "X",
    "ㅊ": "C",
    "ㅍ": "V",
    "ㅠ": "B",
    "ㅜ": "N",
    "ㅡ": "M",
}


def _canonical_key_name(key_name: str | None) -> str | None:
    if not key_name:
        return None

    raw = str(key_name).strip()
    if not raw:
        return None

    key_names = KeyUtils.get_key_name_list()
    if raw in key_names:
        return raw

    upper = raw.upper()
    if upper in key_names:
        return upper

    lower = raw.lower()
    for name in key_names:
        if name.lower() == lower:
            return name
    return None


def normalize_runtime_toggle_trigger(trigger: str | None) -> str | None:
    if not trigger:
        return None

    raw = str(trigger).strip()
    if not raw:
        return None

    upper = raw.upper()
    if upper in MOUSE_TRIGGER_TOKENS:
        return upper

    return _canonical_key_name(raw)


def is_supported_runtime_toggle_trigger(trigger: str | None) -> bool:
    return normalize_runtime_toggle_trigger(trigger) is not None


def is_keyboard_runtime_toggle_trigger(trigger: str | None) -> bool:
    normalized = normalize_runtime_toggle_trigger(trigger)
    return bool(normalized) and normalized not in MOUSE_TRIGGER_TOKENS


def is_wheel_runtime_toggle_trigger(trigger: str | None) -> bool:
    return normalize_runtime_toggle_trigger(trigger) in {
        WHEEL_UP_TRIGGER,
        WHEEL_DOWN_TRIGGER,
    }


def is_mouse_button_runtime_toggle_trigger(trigger: str | None) -> bool:
    return normalize_runtime_toggle_trigger(trigger) in {
        MOUSE_BUTTON_3_TRIGGER,
        MOUSE_BUTTON_4_TRIGGER,
    }


def display_runtime_toggle_trigger(trigger: str | None) -> str:
    normalized = normalize_runtime_toggle_trigger(trigger)
    if normalized == WHEEL_UP_TRIGGER:
        return txt("Mouse wheel up", "마우스 휠 위")
    if normalized == WHEEL_DOWN_TRIGGER:
        return txt("Mouse wheel down", "마우스 휠 아래")
    if normalized == MOUSE_BUTTON_3_TRIGGER:
        return txt("Mouse Button 3", "마우스 버튼 3")
    if normalized == MOUSE_BUTTON_4_TRIGGER:
        return txt("Mouse Button 4", "마우스 버튼 4")
    return normalized or (str(trigger).strip() if trigger else "")


def runtime_toggle_trigger_options() -> list[tuple[str, str]]:
    options = [(name, name) for name in KeyUtils.get_key_name_list()]
    options.extend(
        [
            (txt("Mouse wheel up", "마우스 휠 위"), WHEEL_UP_TRIGGER),
            (txt("Mouse wheel down", "마우스 휠 아래"), WHEEL_DOWN_TRIGGER),
            (txt("Mouse Button 3", "마우스 버튼 3"), MOUSE_BUTTON_3_TRIGGER),
            (txt("Mouse Button 4", "마우스 버튼 4"), MOUSE_BUTTON_4_TRIGGER),
        ]
    )
    return options


def normalize_runtime_toggle_capture_key(
    keysym: str | None,
    char: str | None = None,
    keycode: int | None = None,
) -> str | None:
    keycode_name = KeyUtils.get_key_name_for_keycode(keycode)
    if keycode_name:
        return keycode_name

    for raw in (keysym, char, (char or "").upper() if char else None):
        if raw:
            hangul_alias = _RUNTIME_TOGGLE_HANGUL_2SET_ALIASES.get(str(raw).strip())
            if hangul_alias:
                return hangul_alias
            aliased = _RUNTIME_TOGGLE_CAPTURE_ALIASES.get(str(raw).strip().upper())
            if aliased:
                return aliased
        normalized = normalize_runtime_toggle_trigger(raw)
        if normalized:
            return normalized
    return None


def normalize_runtime_toggle_listener_key(key) -> str:
    vk = getattr(key, "vk", None)
    keycode_name = KeyUtils.get_key_name_for_keycode(vk)
    if keycode_name:
        return keycode_name.upper()

    char = getattr(key, "char", None)
    normalized = normalize_runtime_toggle_capture_key(None, char)
    if normalized:
        return normalized.upper()

    raw_name = str(key).replace("Key.", "").replace("'", "")
    normalized = normalize_runtime_toggle_capture_key(raw_name, raw_name)
    if normalized:
        return normalized.upper()

    return raw_name.upper()


def normalize_runtime_toggle_wheel_event(
    delta: int | None = None, num: int | None = None
) -> str | None:
    if delta:
        return WHEEL_UP_TRIGGER if delta > 0 else WHEEL_DOWN_TRIGGER
    if num == 4:
        return WHEEL_UP_TRIGGER
    if num == 5:
        return WHEEL_DOWN_TRIGGER
    return None


def runtime_toggle_member_count(events: Iterable[EventModel]) -> int:
    return sum(1 for evt in events if getattr(evt, "runtime_toggle_member", False))


def active_runtime_toggle_events(events: Iterable[EventModel]) -> list[EventModel]:
    return [evt for evt in events if getattr(evt, "use_event", True)]


def _resolve_start_stop_trigger(settings, os_name: str | None = None) -> str | None:
    if settings is None:
        return None

    os_name = os_name or platform.system()
    if os_name == "Darwin" and getattr(settings, "toggle_start_stop_mac", False):
        return "ALT_SHIFT_MAC"
    if os_name == "Windows" and getattr(settings, "use_alt_shift_hotkey", False):
        return "ALT_SHIFT_WIN"

    start_stop_key = getattr(settings, "start_stop_key", None) or ""
    if not start_stop_key or start_stop_key == "DISABLED":
        return None
    return normalize_runtime_toggle_trigger(start_stop_key)


def collect_runtime_toggle_validation_errors(
    profile: ProfileModel,
    events: Iterable[EventModel],
    settings=None,
    os_name: str | None = None,
) -> list[str]:
    if not getattr(profile, "runtime_toggle_enabled", False):
        return []

    errors: list[str] = []
    active_events = active_runtime_toggle_events(events)
    trigger_raw = (getattr(profile, "runtime_toggle_key", None) or "").strip()
    trigger = normalize_runtime_toggle_trigger(trigger_raw)

    if not trigger_raw:
        errors.append(
            txt(
                "Runtime Event Group toggle trigger is missing.",
                "실행 중 추가 이벤트 묶음의 토글 트리거가 비어 있습니다.",
            )
        )
    elif not trigger:
        errors.append(
            txt(
                "Runtime Event Group toggle trigger is invalid: {trigger}",
                "실행 중 추가 이벤트 묶음의 토글 트리거가 올바르지 않습니다: {trigger}",
                trigger=trigger_raw,
            )
        )

    if runtime_toggle_member_count(active_events) == 0:
        errors.append(
            txt(
                "Runtime Event Group has no selected events.",
                "실행 중 추가 이벤트 묶음에 선택된 이벤트가 없습니다.",
            )
        )

    if not trigger:
        return errors

    start_stop_trigger = _resolve_start_stop_trigger(settings, os_name=os_name)
    if start_stop_trigger == "ALT_SHIFT_MAC" and trigger in {"Option", "Shift"}:
        errors.append(
            txt(
                "Runtime Event Group toggle trigger conflicts with Start/Stop: {trigger}",
                "실행 중 추가 이벤트 묶음의 토글 트리거가 시작/중지와 충돌합니다: {trigger}",
                trigger=display_runtime_toggle_trigger(trigger),
            )
        )
    elif start_stop_trigger == "ALT_SHIFT_WIN" and trigger in {"Alt", "Shift"}:
        errors.append(
            txt(
                "Runtime Event Group toggle trigger conflicts with Start/Stop: {trigger}",
                "실행 중 추가 이벤트 묶음의 토글 트리거가 시작/중지와 충돌합니다: {trigger}",
                trigger=display_runtime_toggle_trigger(trigger),
            )
        )
    elif start_stop_trigger and start_stop_trigger == trigger:
        errors.append(
            txt(
                "Runtime Event Group toggle trigger conflicts with Start/Stop: {trigger}",
                "실행 중 추가 이벤트 묶음의 토글 트리거가 시작/중지와 충돌합니다: {trigger}",
                trigger=display_runtime_toggle_trigger(trigger),
            )
        )

    if is_keyboard_runtime_toggle_trigger(trigger):
        conflicting_events = sorted(
            {
                (
                    getattr(evt, "event_name", None) or txt("Unnamed", "이름 없음")
                ).strip()
                for evt in active_events
                if getattr(evt, "execute_action", True)
                and normalize_runtime_toggle_trigger(getattr(evt, "key_to_enter", None))
                == trigger
            }
        )
        if conflicting_events:
            errors.append(
                txt(
                    "Runtime Event Group toggle trigger conflicts with event input key '{trigger}'. Events: {names}",
                    "실행 중 추가 이벤트 묶음의 토글 트리거가 이벤트 입력 키 '{trigger}' 와 충돌합니다. 이벤트: {names}",
                    trigger=display_runtime_toggle_trigger(trigger),
                    names=", ".join(conflicting_events),
                )
            )

    return errors
