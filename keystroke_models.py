from dataclasses import dataclass, field, fields
from PIL import Image


@dataclass
class UserSettings:
    start_stop_key: str = "`"
    key_pressed_time_min: int = 95
    key_pressed_time_max: int = 135
    delay_between_loop_min: int = 100
    delay_between_loop_max: int = 150
    cluster_epsilon_value: int = 20
    max_key_count: int | None = 10
    toggle_start_stop_mac: bool = True
    use_alt_shift_hotkey: bool = False

    def is_start_stop_key_enabled(self) -> bool:
        return self.start_stop_key != "DISABLED"


@dataclass
class EventModel:
    event_name: str | None = None
    latest_position: tuple | None = None
    clicked_position: tuple | None = None
    latest_screenshot: Image.Image | None = None
    held_screenshot: Image.Image | None = None
    ref_pixel_value: tuple | None = None
    key_to_enter: str | None = None
    press_duration_ms: float | None = None
    randomization_ms: float | None = None
    independent_thread: bool | None = False
    use_event: bool = True

    def __iter__(self):
        # fields(self)는 메타데이터이므로 __dict__ 유무와 관계없이 안전하게 동작
        return ((f, getattr(self, f.name)) for f in fields(self))


@dataclass
class ProfileModel:
    name: str | None = None
    # TypeError 방지: None 대신 빈 리스트를 기본값으로 설정 (field 사용)
    event_list: list[EventModel] = field(default_factory=list)
    modification_keys: dict | None = None
    favorite: bool = False

    def __iter__(self):
        return iter(self.event_list)
