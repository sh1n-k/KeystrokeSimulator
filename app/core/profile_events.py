from __future__ import annotations

from dataclasses import replace

from app.core.models import EventModel

KeySortOrder = tuple[int, int, str]
EventSortKey = tuple[object, ...]

SPECIAL_KEYS_ORDER: dict[str, int] = {
    "SPACE": 0,
    "TAB": 1,
    "ENTER": 2,
    "RETURN": 2,
    "BACKSPACE": 3,
    "DELETE": 4,
    "INSERT": 5,
    "HOME": 6,
    "END": 7,
    "PAGEUP": 8,
    "PAGEDOWN": 9,
    "UP": 10,
    "DOWN": 11,
    "LEFT": 12,
    "RIGHT": 13,
    "ESC": 14,
    "ESCAPE": 14,
}


def clone_event(event: EventModel, *, event_name: str | None = None) -> EventModel:
    """Clone an event while keeping mutable payloads independent."""
    return replace(
        event,
        event_name=event.event_name if event_name is None else event_name,
        held_screenshot=(
            event.held_screenshot.copy() if event.held_screenshot is not None else None
        ),
        conditions=dict(event.conditions),
    )


def rename_condition_references(
    events: list[EventModel], old_name: str, new_name: str
) -> None:
    for event in events:
        if old_name in event.conditions:
            event.conditions[new_name] = event.conditions.pop(old_name)


def remove_condition_references(events: list[EventModel], removed_name: str) -> None:
    for event in events:
        event.conditions.pop(removed_name, None)


def event_type_sort_order(event: EventModel) -> int:
    return 0 if not event.execute_action else 1


def key_sort_order(key: str | None) -> KeySortOrder:
    if not key:
        return (99, 0, "")

    base_key = key.split("+")[-1].strip().upper()
    if len(base_key) == 1 and base_key.isdigit():
        return (0, int(base_key), base_key)
    if len(base_key) == 1 and base_key.isalpha():
        return (1, ord(base_key), base_key)
    if base_key.startswith("F") and len(base_key) <= 3:
        try:
            function_number = int(base_key[1:])
        except ValueError:
            pass
        else:
            if 1 <= function_number <= 12:
                return (2, function_number, base_key)
    if base_key in SPECIAL_KEYS_ORDER:
        return (3, SPECIAL_KEYS_ORDER[base_key], base_key)
    return (4, ord(base_key[0]) if base_key else 999, base_key)


def event_name_sort_key(event: EventModel) -> EventSortKey:
    name = event.event_name or ""
    return (event_type_sort_order(event), name.casefold(), name)


def event_key_sort_key(event: EventModel) -> EventSortKey:
    name = event.event_name or ""
    type_order = event_type_sort_order(event)
    if type_order == 0:
        return (type_order, 0, name.casefold(), name)
    return (
        type_order,
        1,
        *key_sort_order(event.key_to_enter),
        name.casefold(),
        name,
    )
