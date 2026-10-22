from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from app.core.models import EventModel, ProfileModel


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


# ---------------------------------------------------------------------------
# Filtering — the workspace search box and the 'no key' badge.
# ---------------------------------------------------------------------------


def event_needs_attention(event: EventModel) -> bool:
    """A rule without an input key cannot run. Single source of truth for the
    'no key' badge and counts."""
    return bool(getattr(event, "execute_action", True)) and not (
        event.key_to_enter or ""
    ).strip()


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


# ---------------------------------------------------------------------------
# Workspace list — signals / rules sections and order-as-priority.
# ---------------------------------------------------------------------------

SectionKind = Literal["signal", "group", "ungrouped"]


@dataclass(frozen=True)
class EventSection:
    """한 묶음. 신호(`execute_action=False`), 그룹별 규칙, 그룹 없는 규칙."""

    kind: SectionKind
    group: str
    events: tuple[EventModel, ...]


def event_group(event: EventModel) -> str:
    return (event.group_id or "").strip()


def display_order_key(event: EventModel) -> tuple[int, str]:
    """processor `_select_by_group_priority`와 같은 (priority, name) 순서."""
    return (int(event.priority or 0), (event.event_name or "").strip())


def build_event_sections(events: Iterable[EventModel]) -> list[EventSection]:
    signals: list[EventModel] = []
    groups: dict[str, list[EventModel]] = {}
    ungrouped: list[EventModel] = []
    for event in events:
        if not event.execute_action:
            signals.append(event)
        elif group := event_group(event):
            groups.setdefault(group, []).append(event)
        else:
            ungrouped.append(event)
    sections: list[EventSection] = []
    if signals:
        sections.append(
            EventSection("signal", "", tuple(sorted(signals, key=display_order_key)))
        )
    for group in sorted(groups, key=lambda g: (g.casefold(), g)):
        sections.append(
            EventSection(
                "group", group, tuple(sorted(groups[group], key=display_order_key))
            )
        )
    if ungrouped:
        sections.append(
            EventSection(
                "ungrouped", "", tuple(sorted(ungrouped, key=display_order_key))
            )
        )
    return sections


def write_section_order(ordered: Iterable[EventModel]) -> bool:
    """목록 순서를 우선순위로 쓴다(묶음 안에서 0부터). 바뀐 값이 있으면 True."""
    changed = False
    for index, event in enumerate(ordered):
        if event.priority != index:
            event.priority = index
            changed = True
    return changed


def move_in_section(
    section: Iterable[EventModel], moved: EventModel, target_index: int
) -> list[EventModel]:
    """`moved`를 묶음 안의 `target_index` 위치로 옮긴 새 순서."""
    order = [event for event in section if event is not moved]
    target_index = max(0, min(target_index, len(order)))
    order.insert(target_index, moved)
    return order


def sort_sections_by_name(events: Iterable[EventModel]) -> bool:
    """각 묶음을 이름순으로 한 번 정렬해 우선순위로 쓴다."""
    changed = False
    for section in build_event_sections(events):
        ordered = sorted(
            section.events,
            key=lambda e: ((e.event_name or "").casefold(), e.event_name or ""),
        )
        changed = write_section_order(ordered) or changed
    return changed


def referenced_event_names(events: Iterable[EventModel]) -> set[str]:
    """다른 이벤트의 조건으로 쓰이는 이벤트 이름."""
    names: set[str] = set()
    for event in events:
        names.update(event.conditions)
    return names


def event_has_screen(event: EventModel) -> bool:
    return event.latest_position is not None and event.clicked_position is not None


def copy_event_name(base_name: str, events: Iterable[EventModel]) -> str:
    return next_available_event_name(
        base_name, {e.event_name or "" for e in events}
    )


def apply_target_to_same_area(
    events: Iterable[EventModel], source: EventModel
) -> int:
    """같은 캡처 위치의 다른 이벤트에 대상 픽셀·매칭 방식을 옮긴다."""
    if source.latest_position is None or source.clicked_position is None:
        return 0
    count = 0
    for event in events:
        if (
            event is source
            or event.latest_position != source.latest_position
            or event.held_screenshot is None
        ):
            continue
        image = event.held_screenshot
        x, y = source.clicked_position
        if not (0 <= x < image.width and 0 <= y < image.height):
            continue
        pixel = image.getpixel((x, y))
        if isinstance(pixel, tuple):
            channels = cast(tuple[int | float, ...], pixel)
            color: tuple[int, ...] = tuple(int(c) for c in channels)
        else:
            color = (int(cast(int | float, pixel)),) * 3
        event.clicked_position = source.clicked_position
        event.ref_pixel_value = color
        event.match_mode = source.match_mode
        event.region_size = source.region_size
        count += 1
    return count


# ---------------------------------------------------------------------------
# Autosave dirty detection.
# ---------------------------------------------------------------------------

# EventModel fields that participate in profile dirty/autosave detection.
# When adding a field to EventModel, include it here and in event_fingerprint.
EVENT_DIRTY_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "event_name",
        "use_event",
        "capture_size",
        "latest_position",
        "clicked_position",
        "ref_pixel_value",
        "key_to_enter",
        "press_duration_ms",
        "randomization_ms",
        "match_mode",
        "invert_match",
        "region_size",
        "execute_action",
        "group_id",
        "priority",
        "conditions",
        "runtime_toggle_member",
        "held_screenshot",
    }
)


def _image_identity(img: object) -> tuple[object, ...] | None:
    if img is None:
        return None
    image = cast(Any, img)
    return (id(img), image.size, image.mode)


def event_fingerprint(evt: EventModel) -> tuple[object, ...]:
    return (
        evt.event_name,
        bool(evt.use_event),
        evt.capture_size,
        evt.latest_position,
        evt.clicked_position,
        evt.ref_pixel_value,
        evt.key_to_enter,
        evt.press_duration_ms,
        evt.randomization_ms,
        evt.match_mode,
        bool(evt.invert_match),
        evt.region_size,
        bool(evt.execute_action),
        evt.group_id,
        int(evt.priority or 0),
        tuple(sorted(dict(evt.conditions or {}).items())),
        bool(evt.runtime_toggle_member),
        _image_identity(evt.held_screenshot),
    )


def profile_fingerprint(
    profile: ProfileModel, profile_name: str, favorite: bool
) -> tuple[object, ...]:
    return (
        profile_name,
        bool(favorite),
        bool(profile.runtime_toggle_enabled),
        profile.runtime_toggle_key,
        tuple(event_fingerprint(evt) for evt in (profile.event_list or [])),
    )


def snapshot_events(events: Iterable[EventModel]) -> list[EventModel]:
    """되돌리기용 얕은 복사. 이미지는 바꾸지 않고 교체만 하므로 공유한다."""
    return [replace(event, conditions=dict(event.conditions)) for event in events]
