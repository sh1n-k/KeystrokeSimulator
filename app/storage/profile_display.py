import sys
from collections.abc import Iterable, Mapping
from typing import cast


def get_favorite_prefix() -> str:
    return "★ " if sys.platform == "win32" else "⭐ "


FAVORITE_PREFIX = get_favorite_prefix()
QUICK_PROFILE_NAME = "Quick"

_MOD_KEY_ORDER: tuple[str, ...] = ("alt", "ctrl", "shift")
_MOD_KEYCAPS: dict[str, str] = {"alt": "⎇", "ctrl": "⌃", "shift": "⇧"}


def to_profile_display_name(
    profile_name: str,
    is_favorite: bool,
    quick_profile_name: str = QUICK_PROFILE_NAME,
) -> str:
    if profile_name == quick_profile_name or not is_favorite:
        return profile_name
    return f"{FAVORITE_PREFIX}{profile_name}"


def build_profile_display_values(
    profile_names: Iterable[str],
    favorite_names: set[str],
    quick_profile_name: str = QUICK_PROFILE_NAME,
) -> list[str]:
    return [
        to_profile_display_name(
            name,
            name in favorite_names,
            quick_profile_name=quick_profile_name,
        )
        for name in profile_names
    ]


def _as_str_object_map(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    raw = cast(Mapping[object, object], value)
    return {str(key): item for key, item in raw.items()}


def format_modification_keys_summary(
    modification_keys: Mapping[str, object] | None,
) -> str:
    """Compact one-line summary for main-window chips (e.g. ⎇ Pass · ⌃ A · ⇧ off)."""
    parts: list[str] = []
    source: Mapping[str, object] = modification_keys or {}
    for key in _MOD_KEY_ORDER:
        cap = _MOD_KEYCAPS[key]
        conf = _as_str_object_map(source.get(key))
        if conf is None:
            parts.append(f"{cap} Pass")
            continue
        enabled = bool(conf.get("enabled", True))
        if not enabled:
            parts.append(f"{cap} off")
            continue
        pass_through = bool(conf.get("pass", False))
        raw_value = conf.get("value", "Pass")
        value_text = str(raw_value if raw_value is not None else "Pass")
        value_text = value_text.replace("\n", " ").replace("\r", " ").strip() or "Pass"
        if len(value_text) > 8:
            value_text = value_text[:8]
        if pass_through or value_text == "Pass":
            parts.append(f"{cap} Pass")
        else:
            parts.append(f"{cap} {value_text}")
    return " · ".join(parts)
