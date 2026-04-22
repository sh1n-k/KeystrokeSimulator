from typing import Iterable

from app.core.models import EventModel
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
