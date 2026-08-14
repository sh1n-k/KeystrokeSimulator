from dataclasses import dataclass, field
from typing import TypeAlias

from PIL import Image

Position: TypeAlias = tuple[int, int]
ColorTuple: TypeAlias = tuple[int, ...]
ModificationKeyConfig: TypeAlias = dict[str, bool | str]
ModificationKeys: TypeAlias = dict[str, ModificationKeyConfig]


@dataclass
class UserSettings:
    language: str = "en"
    start_stop_key: str = "`"
    key_pressed_time_min: int = 95
    key_pressed_time_max: int = 135
    delay_between_loop_min: int = 100
    delay_between_loop_max: int = 150
    toggle_start_stop_mac: bool = True
    use_alt_shift_hotkey: bool = False
    # Start/stop notification sound pack id (classic | soft_a | soft_b | soft_c)
    notification_sound_pack: str = "classic"


@dataclass
class EventModel:
    event_name: str | None = None
    latest_position: Position | None = None
    clicked_position: Position | None = None
    held_screenshot: Image.Image | None = None
    ref_pixel_value: ColorTuple | None = None
    key_to_enter: str | None = None
    press_duration_ms: float | None = None
    randomization_ms: float | None = None
    use_event: bool = True
    capture_size: Position = (100, 100)

    # 매칭 모드: 'pixel' (기본) 또는 'region'
    match_mode: str = "pixel"
    # 매칭 반전: True이면 지정 픽셀/영역이 '다를 때'를 일치로 간주
    invert_match: bool = False
    # 지역 크기: (width, height), pixel 모드일 경우 무시됨
    region_size: Position | None = None
    # 키 입력 실행 여부: False일 경우 조건용으로만 사용
    execute_action: bool = True
    # 그룹 ID: 비어있으면 그룹에 속하지 않음
    group_id: str | None = None
    # 그룹 내 우선순위: 낮을수록 우선
    priority: int = 0
    # 조건 목록: { '다른_이벤트_이름': True/False } (True: 활성 기대, False: 비활성 기대)
    conditions: dict[str, bool] = field(default_factory=lambda: {})
    # 토글 세트(실행 중 ON/OFF)에 포함되는지 여부
    runtime_toggle_member: bool = False

    def is_screenless_input(self) -> bool:
        """화면 좌표 없이 조건 AND만으로 키를 실행하는 입력 이벤트인지."""
        return (
            bool(self.execute_action)
            and bool(self.conditions)
            and self.latest_position is None
            and self.clicked_position is None
        )


@dataclass
class ProfileModel:
    name: str | None = None
    event_list: list[EventModel] = field(default_factory=lambda: [])
    # Deprecated: kept only for type compatibility; load/save always clear this.
    # Runtime modkeys come from modkey_sets.json.
    modification_keys: ModificationKeys | None = None
    favorite: bool = False
    runtime_toggle_enabled: bool = False
    runtime_toggle_key: str | None = None
    load_ignored_invalid_data: bool = field(default=False, repr=False, compare=False)
