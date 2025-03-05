from dataclasses import dataclass, fields
from typing import Optional

from PIL import Image


@dataclass
class UserSettings:
    # On macOS, start_stop_key can be set to "DISABLED" to indicate the key is disabled
    start_stop_key: str = "`"
    key_pressed_time_min: int = 95
    key_pressed_time_max: int = 135
    delay_between_loop_min: int = 100
    delay_between_loop_max: int = 150
    cluster_epsilon_value: int = 20
    max_key_count: Optional[int] = 10
    start_sound: str = "start.mp3"
    stop_sound: str = "stop.mp3"
    toggle_start_stop_mac: bool = True

    def is_start_stop_key_enabled(self) -> bool:
        """Check if the start/stop key is enabled (not set to DISABLED)"""
        return self.start_stop_key != "DISABLED"


@dataclass
class EventModel:
    event_name: Optional[str] = None
    latest_position: Optional[tuple] = None
    clicked_position: Optional[tuple] = None
    latest_screenshot: Optional[Image.Image] = None
    held_screenshot: Optional[Image.Image] = None
    ref_pixel_value: Optional[tuple] = None
    key_to_enter: Optional[str] = None
    independent_thread: Optional[bool] = False
    use_event: bool = True

    def __iter__(self):
        for field in fields(self):
            yield field, getattr(self, field.name)

    def __str__(self):
        field_strings = [f"{field.name}={value}" for field, value in self]
        return f"EventModel({', '.join(field_strings)})"


@dataclass
class ProfileModel:
    name: Optional[str] = None
    event_list: Optional[list[EventModel]] = None
    modification_keys: Optional[dict] = None

    def __iter__(self):
        for event in self.event_list or []:
            yield event

    def __str__(self):
        event_strings = [str(event) for event in self]
        return (
            f"ProfileModel(name='{self.name}', event_list=[{', '.join(event_strings)}])"
        )
