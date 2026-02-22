from dataclasses import dataclass, field, fields
from typing import Dict, Optional, Tuple
from PIL import Image


@dataclass
class UserSettings:
    language: str = "en"
    start_stop_key: str = "`"
    key_pressed_time_min: int = 95
    key_pressed_time_max: int = 135
    delay_between_loop_min: int = 100
    delay_between_loop_max: int = 150
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

    # --- Phase 1 Added Fields ---
    # 매칭 모드: 'pixel' (기본) 또는 'region'
    match_mode: str = "pixel"
    # 매칭 반전: True이면 지정 픽셀/영역이 '다를 때'를 일치로 간주
    invert_match: bool = False
    # 지역 크기: (width, height), pixel 모드일 경우 무시됨
    region_size: Tuple[int, int] | None = None
    # 키 입력 실행 여부: False일 경우 조건용으로만 사용
    execute_action: bool = True
    # 그룹 ID: 비어있으면 독립 이벤트
    group_id: str | None = None
    # 그룹 내 우선순위: 높을수록 우선 (또는 로직에 따라 정의)
    priority: int = 0
    # 조건 목록: { '다른_이벤트_이름': True/False } (True: 활성 기대, False: 비활성 기대)
    conditions: Dict[str, bool] = field(default_factory=dict)

    def __iter__(self):
        return ((f, getattr(self, f.name)) for f in fields(self))


@dataclass
class ProfileModel:
    name: str | None = None
    event_list: list[EventModel] = field(default_factory=list)
    modification_keys: dict | None = None
    favorite: bool = False

    def __iter__(self):
        return iter(self.event_list)
