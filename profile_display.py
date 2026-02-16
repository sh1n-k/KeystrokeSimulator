from typing import Iterable


FAVORITE_PREFIX = "⭐ "
QUICK_PROFILE_NAME = "Quick"


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
