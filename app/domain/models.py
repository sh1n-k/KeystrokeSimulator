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
    # Runtime toggle ON/OFF alert pack; independent of start/stop.
    runtime_toggle_sound_pack: str = "classic"
    runtime_toggle_sound_enabled: bool = True


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
    # 대기 동작: 선택되면 키를 누르지 않는다. 그룹에서 아래 동작이 대신 실행되지
    # 않게 막는 용도이며, 켜져 있으면 key_to_enter는 쓰지 않는다.
    wait_action: bool = False

    def is_screenless_input(self) -> bool:
        """화면 좌표 없이 조건 AND만으로 키를 실행하는 입력 이벤트인지."""
        return (
            bool(self.execute_action)
            and bool(self.conditions)
            and self.latest_position is None
            and self.clicked_position is None
        )

    def has_processor_inputs(self) -> bool:
        """processor가 로드할 입력(화면 기준 데이터, 또는 조건만 쓰는 입력)을 갖췄는지.

        실행 가능 판정의 단일 기준이다. 실행 창 시작 가능 여부(`RunController`),
        processor 로드(`KeystrokeProcessor._init_event_data`), 작업 공간 배지
        (`event_issues`)가 함께 쓴다. 사용 여부(`use_event`)와 키 유무는 보지 않는다.
        """
        if self.is_screenless_input():
            return True
        if self.latest_position is None or self.clicked_position is None:
            return False
        if (self.match_mode or "pixel") == "region":
            return self.held_screenshot is not None
        return self.ref_pixel_value is not None and len(self.ref_pixel_value) >= 3


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
