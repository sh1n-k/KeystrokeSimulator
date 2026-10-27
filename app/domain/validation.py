from collections.abc import Iterable, Mapping

from app.domain.models import EventModel

MIN_PRESS_DURATION_MS = 50
MIN_RANDOMIZATION_MS = 30
MIN_REGION_SIZE = 20
MAX_REGION_SIZE = 1000


def normalized_event_name(name: object) -> str:
    return str(name or "").strip()


def find_duplicate_event_names(events: Iterable[EventModel]) -> list[str]:
    counts: dict[str, int] = {}
    for evt in events:
        name = normalized_event_name(getattr(evt, "event_name", None))
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return sorted(name for name, count in counts.items() if count > 1)


def event_name_taken(
    events: Iterable[EventModel], name: str, *, ignore: EventModel | None = None
) -> bool:
    target = normalized_event_name(name)
    return any(
        evt is not ignore and normalized_event_name(evt.event_name) == target
        for evt in events
    )


def find_condition_cycle(
    events: Iterable[EventModel], name: str, conditions: Mapping[str, bool]
) -> list[str] | None:
    """`name`의 조건을 `conditions`로 바꿨을 때 생기는 순환 경로. 없으면 None."""
    graph: dict[str, list[str]] = {
        e.event_name: list(e.conditions) for e in events if e.event_name
    }
    graph[name] = list(conditions)

    visited: set[str] = set()
    on_path: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        visited.add(node)
        on_path.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                found = dfs(neighbor)
                if found is not None:
                    return found
            elif neighbor in on_path:
                return path[path.index(neighbor) :] + [neighbor]
        path.pop()
        on_path.remove(node)
        return None

    for node in graph:
        if node not in visited:
            found = dfs(node)
            if found is not None:
                return found
    return None


def condition_cycle_if_added(
    events: Iterable[EventModel], target: EventModel, candidate: str
) -> list[str] | None:
    """`target`에 `candidate` 조건을 더하면 생기는 순환 경로."""
    conditions = dict(target.conditions)
    conditions[candidate] = True
    return find_condition_cycle(events, target.event_name or "", conditions)


def max_region_dimension(center: int, total: int) -> int:
    """중심에서 캡처본 안에 들어가는 가장 큰 영역 한 변(최대 1000)."""
    if total <= 0:
        return 0
    size = min(MAX_REGION_SIZE, total)
    while size > 0:
        if center - size // 2 >= 0 and center + size // 2 + (size % 2) <= total:
            return size
        size -= 1
    return 0


def region_limits(
    image_size: tuple[int, int], pixel: tuple[int, int]
) -> tuple[int, int]:
    return (
        max_region_dimension(pixel[0], image_size[0]),
        max_region_dimension(pixel[1], image_size[1]),
    )


def timing_is_valid(duration_ms: int | None, randomization_ms: int | None) -> bool:
    """비워 둔 값은 전역 설정을 쓴다. 기존 편집기와 같은 규칙: 랜덤은 지속
    시간을 함께 지정했을 때만 검사한다."""
    if duration_ms and duration_ms < MIN_PRESS_DURATION_MS:
        return False
    return not (
        duration_ms and randomization_ms and randomization_ms < MIN_RANDOMIZATION_MS
    )


def settings_number_entry_valid(value: str) -> bool:
    """설정 창 숫자 칸: 빈 값 또는 앞자리 0 없는 0~999."""
    return value == "" or (
        value.isdigit()
        and not (value.startswith("0") and len(value) > 1)
        and int(value) < 1000
    )


START_STOP_SYMBOL_KEYS = frozenset("`[];',./-=\"")


def start_stop_key_valid(key: str) -> bool:
    """시작/중지 키로 받을 수 있는 키 이름(대문자). 영숫자·기호 한 글자 또는 F키."""
    return (len(key) == 1 and (key.isalnum() or key in START_STOP_SYMBOL_KEYS)) or (
        key.startswith("F") and key[1:].isdigit()
    )
