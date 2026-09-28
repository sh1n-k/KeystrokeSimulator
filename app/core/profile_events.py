from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

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


def next_available_event_name(base_name: str, used_names: set[str]) -> str:
    candidate = base_name
    suffix = 2
    while candidate in used_names:
        candidate = f"{base_name} ({suffix})"
        suffix += 1
    return candidate


def next_numbered_event_name(used_names: Iterable[str]) -> str:
    """Quick 연속 캡처의 자동 이름. 기존 숫자 이름 중 가장 큰 값의 다음 번호."""
    numbers = [int(name) for name in used_names if name.isdigit()]
    return str(max(numbers, default=0) + 1)


def rename_colliding_events(
    events: list[EventModel], existing_names: Iterable[str]
) -> dict[str, str]:
    """`events`를 기존 이름과 겹치지 않게 바꾸고, `events` 안의 조건 참조를 함께 옮긴다.

    가져온 이벤트끼리의 조건은 원래 프로필의 같은 이름 이벤트를 가리키므로,
    이름이 바뀐 이벤트를 참조하던 조건도 새 이름으로 바꾼다.
    """
    existing = set(existing_names)
    reserved = existing | {event.event_name or "" for event in events}
    renamed: dict[str, str] = {}
    for event in events:
        old_name = event.event_name or ""
        if old_name not in existing:
            continue
        new_name = next_available_event_name(old_name, reserved)
        reserved.add(new_name)
        renamed[old_name] = new_name
        event.event_name = new_name
    if renamed:
        for event in events:
            event.conditions = {
                renamed.get(name, name): state
                for name, state in event.conditions.items()
            }
    return renamed


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


def _group_sort_prefix(event: EventModel) -> tuple[int, str, str]:
    group = (event.group_id or "").strip()
    return (0 if group else 1, group.casefold(), group)


def event_group_name_sort_key(event: EventModel) -> EventSortKey:
    return (*_group_sort_prefix(event), *event_name_sort_key(event))


def event_group_key_sort_key(event: EventModel) -> EventSortKey:
    return (*_group_sort_prefix(event), *event_key_sort_key(event))


# ---------------------------------------------------------------------------
# Filtering — shared by the profile manager's nav rail, search box and badges.
# ---------------------------------------------------------------------------


def event_needs_attention(event: EventModel) -> bool:
    """An action event without an input key cannot run. Single source of truth
    for the 'Attention' badge count and the attention filter."""
    return bool(getattr(event, "execute_action", True)) and not (
        event.key_to_enter or ""
    ).strip()


@dataclass(frozen=True)
class EventFilterState:
    """Which events the list should show. All fields combine with AND."""

    query: str = ""
    active_only: bool = False
    grouped_only: bool = False
    condition_only: bool = False
    attention_only: bool = False
    group_ids: frozenset[str] = field(default_factory=lambda: frozenset[str]())

    def is_active(self) -> bool:
        return bool(
            self.query.strip()
            or self.active_only
            or self.grouped_only
            or self.condition_only
            or self.attention_only
            or self.group_ids
        )


def event_matches_query(event: EventModel, query: str) -> bool:
    """Substring match over the fields visible in a row: name, key, group."""
    needle = query.strip().casefold()
    if not needle:
        return True
    haystacks = (
        event.event_name or "",
        event.key_to_enter or "",
        event.group_id or "",
    )
    return any(needle in value.casefold() for value in haystacks)


def event_matches_filter(event: EventModel, state: EventFilterState) -> bool:
    if state.active_only and not getattr(event, "use_event", True):
        return False
    if state.grouped_only and not (event.group_id or "").strip():
        return False
    if state.condition_only and getattr(event, "execute_action", True):
        return False
    if state.attention_only and not event_needs_attention(event):
        return False
    if state.group_ids and (event.group_id or "") not in state.group_ids:
        return False
    return event_matches_query(event, state.query)


def filter_event_indices(
    events: list[EventModel], state: EventFilterState
) -> list[int]:
    """Positions of the events that pass `state`, in list order."""
    return [i for i, event in enumerate(events) if event_matches_filter(event, state)]
