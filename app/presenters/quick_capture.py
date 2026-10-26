"""연속 캡처(빠른 이벤트)를 Quick 프로필에 붙이는 동작. UI 툴킷과 무관하다."""

from __future__ import annotations

from pathlib import Path

from app.domain.capture_geometry import CaptureResult
from app.domain.models import EventModel
from app.domain.profile_events import next_numbered_event_name
from app.storage.profile_storage import load_profile, save_profile


def quick_event(name: str, result: CaptureResult) -> EventModel:
    return EventModel(
        event_name=name,
        capture_size=result.capture_size,
        latest_position=result.position,
        clicked_position=result.pixel,
        held_screenshot=result.image,
        ref_pixel_value=result.color,
        match_mode="pixel",
        region_size=None,
    )


def append_quick_event(profiles_dir: Path, result: CaptureResult) -> str:
    """Quick 프로필을 다시 읽어 뒤에 추가한다. 붙인 이름을 돌려준다."""
    profile = load_profile(profiles_dir, "Quick", migrate=True)
    name = next_numbered_event_name(e.event_name or "" for e in profile.event_list)
    profile.event_list.append(quick_event(name, result))
    save_profile(profiles_dir, profile, name="Quick")
    return name
