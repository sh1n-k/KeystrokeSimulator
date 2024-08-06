from dataclasses import dataclass, fields
from typing import Optional

from PIL import Image


@dataclass
class UserSettings:
    start_stop_key: str = "`"
    key_pressed_time_min: int = 95
    key_pressed_time_max: int = 135
    delay_between_loop_min: int = 100
    delay_between_loop_max: int = 150
    start_sound: str = "start.mp3"
    stop_sound: str = "stop.mp3"


@dataclass
class EventModel:
    event_name: Optional[str] = None
    latest_position: Optional[tuple] = None
    clicked_position: Optional[tuple] = None
    latest_screenshot: Optional[Image.Image] = None
    held_screenshot: Optional[Image.Image] = None
    ref_pixel_value: Optional[tuple] = None
    key_to_enter: Optional[str] = None

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

    def __iter__(self):
        for event in self.event_list or []:
            yield event

    def __str__(self):
        event_strings = [str(event) for event in self]
        return (
            f"ProfileModel(name='{self.name}', event_list=[{', '.join(event_strings)}])"
        )


class AppState:
    def __init__(self):
        self.selected_process: Optional[str] = None
        self.selected_profile: Optional[str] = None
        self.is_simulation_running: bool = False
        # Add other state variables as needed

    def update_process(self, process: str):
        self.selected_process = process

    def update_profile(self, profile: str):
        self.selected_profile = profile

    def toggle_simulation(self):
        self.is_simulation_running = not self.is_simulation_running
