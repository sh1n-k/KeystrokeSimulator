from typing import Iterable

from app.core.models import EventModel, ProfileModel
from app.utils.runtime_toggle import collect_runtime_toggle_validation_errors


def normalized_event_name(name: str | None) -> str:
    return (name or "").strip()


def find_duplicate_event_names(events: Iterable[EventModel]) -> list[str]:
    counts: dict[str, int] = {}
    for evt in events:
        name = normalized_event_name(getattr(evt, "event_name", None))
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return sorted(name for name, count in counts.items() if count > 1)


def runtime_toggle_validation_errors(
    profile: ProfileModel,
    events: Iterable[EventModel],
    settings=None,
    os_name: str | None = None,
) -> list[str]:
    return collect_runtime_toggle_validation_errors(
        profile,
        events,
        settings=settings,
        os_name=os_name,
    )
