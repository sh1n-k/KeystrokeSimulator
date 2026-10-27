from collections.abc import Mapping
from typing import cast


def as_object_dict(value: object) -> dict[str, object] | None:
    """JSON 객체를 문자열 키 dict로. 객체가 아니면 None."""
    if not isinstance(value, Mapping):
        return None
    raw = cast(Mapping[object, object], value)
    return {str(key): item for key, item in raw.items()}
