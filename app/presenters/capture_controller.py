"""캡처 HUD의 상태와 동작. UI 툴킷과 무관하다.

단일 모드는 이벤트 하나의 화면을 고르고, 연속 모드는 Quick 프로필 뒤에 자동
번호로 계속 추가한다. ALT를 누르는 동안 캡처 박스가 포인터를 따라가지만 CTRL로
고정하기 전까지는 적용되지 않는다. 키 상태·포인터·권한 조회는 주입받는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from PIL import Image

from app.domain.capture_geometry import (
    MAX_CAPTURE_SIZE,
    MIN_CAPTURE_SIZE,
    CaptureResult,
    Rect,
    capture_rect,
    display_to_image,
    hud_position,
    magnifier_to_image,
    preview_size,
)
from app.domain.capture_render import render_magnifier, render_overlay
from app.domain.models import ColorTuple, Position
from app.engine.capture_session import CaptureBackend, CaptureSession
from app.platform.keys import KeyUtils
from app.platform.system import PermissionUtils
from app.presenters.quick_capture import append_quick_event
from app.storage.app_state import StateUtils
from app.storage.profile_storage import ensure_quick_profile
from app.utils.i18n import txt

HudMode = Literal["single", "continuous"]
# 상태 문구의 의미 색. UI가 실제 색으로 바꾼다.
Tone = Literal["muted", "warn", "ready", "accent"]

KEY_POLL_MS = 100
CAPTURE_POLL_MS = 50
# 키 폴링 100ms 기준 3초. 권한 조회는 호출당 10ms 이상이다.
PERMISSION_POLL_TICKS = 30
HUD_POS_STATE_KEY = "capture_hud_pos"


@dataclass(frozen=True)
class TickUpdate:
    """키 폴링 한 번으로 바뀐 화면 범위."""

    render: bool = False
    info: bool = False
    status: bool = False


def permission_message() -> str | None:
    missing = PermissionUtils.missing_macos_permissions()
    if not missing:
        return None
    labels: list[str] = []
    if "screen" in missing:
        labels.append(txt("Screen Recording", "화면 기록"))
    if "accessibility" in missing:
        labels.append(txt("Accessibility", "손쉬운 사용"))
    return txt(
        "macOS permission required: {missing}.",
        "macOS 권한 필요: {missing}.",
        missing=", ".join(labels),
    )


def _alt_pressed() -> bool:
    return KeyUtils.mod_key_pressed("alt")


def _ctrl_pressed() -> bool:
    return KeyUtils.mod_key_pressed("ctrl")


def clamp_capture_size(width: int, height: int) -> Position:
    return (
        max(MIN_CAPTURE_SIZE, min(MAX_CAPTURE_SIZE, int(width))),
        max(MIN_CAPTURE_SIZE, min(MAX_CAPTURE_SIZE, int(height))),
    )


class CaptureController:
    def __init__(
        self,
        *,
        mode: HudMode,
        pointer: Callable[[], Position],
        capturer: CaptureBackend | None = None,
        profiles_dir: Path | None = None,
        region_size: Position | None = None,
        capture_size: Position = (100, 100),
        on_apply: Callable[[CaptureResult], None] | None = None,
        append_quick: Callable[[CaptureResult], str | None] | None = None,
        close: Callable[[], object] | None = None,
        alt_pressed: Callable[[], bool] = _alt_pressed,
        ctrl_pressed: Callable[[], bool] = _ctrl_pressed,
        permission: Callable[[], str | None] = permission_message,
    ) -> None:
        self.mode: HudMode = mode
        self.profiles_dir = profiles_dir
        self.region_size = region_size
        self.on_apply = on_apply
        # 연속 모드: 열린 작업 공간이 Quick을 들고 있으면 그쪽에 붙인다.
        self.append_quick = append_quick
        self._close = close
        self._pointer = pointer
        self._alt_pressed = alt_pressed
        self._ctrl_pressed = ctrl_pressed
        self._permission = permission
        self.saved_count = 0
        self.alt_down = False
        self._ctrl_was_pressed = False
        self._held_size: Position | None = None
        self.mag_center: Position | None = None
        self.feedback: tuple[str, Tone] | None = None
        self.permission_message = permission()
        self._permission_ticks = PERMISSION_POLL_TICKS
        self.pointer_state_key = "event_pointer" if mode == "single" else "quick_ptr"

        if mode == "continuous" and profiles_dir is not None:
            ensure_quick_profile(profiles_dir)
        self.session = CaptureSession(capturer)
        self._capture_size = self.session.set_capture_size(*capture_size)

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self.session.start()

    def stop(self) -> None:
        self.session.stop()

    def restore(self, initial: CaptureResult) -> None:
        """기존 캡처본과 대상 픽셀을 그대로 보여 준다(편집기의 "캡처…")."""
        self._capture_size = self.session.set_capture_size(*initial.capture_size)
        self.session.set_position(initial.position, force=True)
        self.session.restore(
            latest_position=initial.position,
            held_image=initial.image.copy(),
            selected_position=initial.pixel,
            reference_color=initial.color,
        )
        self._held_size = initial.capture_size
        self.mag_center = initial.pixel

    def load_state(self, *, restore_pointer: bool) -> Position | None:
        """저장한 HUD 위치를 돌려주고, 원하면 마지막 캡처 박스 위치를 복원한다."""
        state = StateUtils.load_main_app_state() or {}
        if restore_pointer and (ptr := state.get(self.pointer_state_key)):
            point = StateUtils.parse_position_tuple(ptr)
            if point is not None:
                self.session.set_position(point)
        return StateUtils.parse_slash_int_pair(state.get(HUD_POS_STATE_KEY))

    def save_state(self, hud_pos: Position | None) -> None:
        values: dict[str, object] = {
            self.pointer_state_key: str(self.session.current_position())
        }
        if hud_pos is not None:
            values[HUD_POS_STATE_KEY] = f"{hud_pos[0]}/{hud_pos[1]}"
        StateUtils.save_main_app_state(**values)

    # -- state ----------------------------------------------------------------

    @property
    def capture_size(self) -> Position:
        return self._capture_size

    def set_capture_size(self, width: int, height: int) -> Position:
        self._capture_size = self.session.set_capture_size(
            *clamp_capture_size(width, height)
        )
        return self._capture_size

    def box(self) -> Rect:
        return capture_rect(self.session.current_position(), self._capture_size)

    def moved_off_hold(self) -> bool:
        """고정한 뒤 ALT나 좌표 입력으로 위치를 옮겨, 새 위치가 아직 고정되지 않았다."""
        held = self.session.held_position
        return held is not None and held != self.session.current_position()

    def shows_live(self) -> bool:
        return (
            self.alt_down
            or self.session.held_image is None
            or self.moved_off_hold()
        )

    def is_ready(self) -> bool:
        snap = self.session.snapshot()
        return bool(
            snap.held_image is not None
            and snap.held_position is not None
            and snap.selected_position is not None
            and snap.reference_color is not None
        )

    def result(self) -> CaptureResult | None:
        snap = self.session.snapshot()
        if (
            snap.held_image is None
            or snap.held_position is None
            or snap.selected_position is None
            or snap.reference_color is None
        ):
            return None
        return CaptureResult(
            position=snap.held_position,
            capture_size=self._held_size or self._capture_size,
            image=snap.held_image.copy(),
            pixel=snap.selected_position,
            color=snap.reference_color,
        )

    # -- actions --------------------------------------------------------------

    def capture(self) -> None:
        """현재 실시간 프레임을 고정한다. 고른 픽셀은 새 캡처본 안이면 유지한다."""
        session = self.session
        if session.latest_image is None or not session.hold():
            self.feedback = (
                txt(
                    "Move the mouse with ALT until the preview follows it.",
                    "ALT를 누른 채 마우스를 움직여 미리보기가 따라오게 하세요.",
                ),
                "warn",
            )
            return
        self._held_size = self._capture_size
        self.feedback = None
        held = session.held_image
        selected = session.selected_position
        if held is not None and selected is not None:
            if not session.select(selected, held.size):
                session.selected_position = None
                session.reference_color = None
        self.mag_center = session.selected_position

    def recapture(self) -> None:
        self.session.clear_hold()
        self._held_size = None
        self.feedback = None
        self.mag_center = None

    def apply(self) -> None:
        # 옮긴 위치를 고정하지 않았으면 예전 캡처본을 조용히 저장하지 않는다.
        result = None if self.moved_off_hold() else self.result()
        if result is None:
            self.feedback = (
                txt(
                    "Freeze the preview with CTRL and click the target pixel first.",
                    "먼저 CTRL로 고정하고 대상 픽셀을 클릭하세요.",
                ),
                "warn",
            )
            return
        if self.mode == "single":
            if self.on_apply is not None:
                self.on_apply(result)
            if self._close is not None:
                self._close()
            return
        if self.profiles_dir is None:
            return
        name = self.append_quick(result) if self.append_quick is not None else None
        if name is None:
            name = append_quick_event(self.profiles_dir, result)
        self.saved_count += 1
        self.session.clear_hold()
        self._held_size = None
        self.mag_center = None
        self.feedback = (
            txt(
                "Saved Quick event '{name}'. Move to the next target.",
                "Quick 이벤트 '{name}'을 저장했습니다. 다음 대상으로 옮기세요.",
                name=name,
            ),
            "ready",
        )

    def on_ctrl(self) -> None:
        session = self.session
        # 연속 모드에서 대상을 고른 뒤 다시 누른 CTRL은 적용이다. 새 프레임을
        # 찍지 않고 대상을 고른 캡처본을 그대로 저장한다.
        if (
            self.mode == "continuous"
            and self.is_ready()
            and session.held_position == session.current_position()
        ):
            self.apply()
            return
        self.capture()

    def select(self, pixel: Position) -> bool:
        held = self.session.held_image
        if held is None or not self.session.select(pixel, held.size):
            return False
        self.feedback = None
        return True

    def click_preview(self, point: Position, display_size: Position) -> bool:
        held = self.session.held_image
        if held is None or self.shows_live():
            return False
        pixel = display_to_image(point, display_size, held.size)
        if pixel is None:
            return False
        self.mag_center = pixel
        return self.select(pixel)

    def click_magnifier(self, point: Position) -> bool:
        held = self.session.held_image
        if held is None or self.shows_live() or self.mag_center is None:
            return False
        # 드래그 중에는 돋보기 중심을 움직이지 않는다. 움직이면 커서 아래
        # 픽셀이 계속 바뀐다.
        pixel = magnifier_to_image(point, self.mag_center, held.size)
        return pixel is not None and self.select(pixel)

    def hover_preview(self, point: Position, display_size: Position) -> bool:
        """돋보기 중심을 포인터 아래로 옮긴다. 바뀌었으면 True."""
        img = self.displayed_image()
        if img is None:
            return False
        pixel = display_to_image(point, display_size, img.size)
        if pixel is None or pixel == self.mag_center:
            return False
        self.mag_center = pixel
        return True

    def leave_preview(self) -> bool:
        selected = self.session.selected_position
        if selected is None or selected == self.mag_center:
            return False
        self.mag_center = selected
        return True

    def set_box_position(self, position: Position) -> None:
        self.session.set_position(position)

    def set_pixel(self, pixel: Position) -> bool:
        if pixel == self.session.selected_position:
            return False
        self.mag_center = pixel
        return self.select(pixel)

    # -- polling --------------------------------------------------------------

    def tick(self, *, text_focus: bool) -> TickUpdate:
        """100ms 키 폴링. 텍스트 입력 중이면 CTRL을 캡처로 받지 않는다."""
        render = info = status = False
        alt = self._alt_pressed()
        if alt:
            self.session.set_position(self._pointer())
            info = True
        if alt != self.alt_down:
            self.alt_down = alt
            if alt:
                self.feedback = None
            render = True

        ctrl = self._ctrl_pressed()
        if ctrl and not self._ctrl_was_pressed and not text_focus:
            self.on_ctrl()
            render = True
        self._ctrl_was_pressed = ctrl

        self._permission_ticks -= 1
        if self._permission_ticks <= 0:
            self._permission_ticks = PERMISSION_POLL_TICKS
            message = self._permission()
            if message != self.permission_message:
                self.permission_message = message
                status = True
        return TickUpdate(render=render, info=info, status=status)

    def hud_target(self, hud: Rect, screen: Position) -> Position | None:
        """HUD가 캡처 박스와 겹치면 옮겨 갈 위치."""
        return hud_position(hud, self.box(), screen)

    # -- view data ------------------------------------------------------------

    def displayed_image(self) -> Image.Image | None:
        session = self.session
        return session.latest_image if self.shows_live() else session.held_image

    def preview(self) -> tuple[Image.Image | None, Position]:
        """미리보기 이미지(대상 표시 포함)와 표시 크기. 프레임이 없으면 None."""
        img = self.displayed_image()
        if img is None:
            return None, preview_size(self._capture_size)
        if not self.shows_live():
            img = render_overlay(img, self.session.selected_position, self.region_size)
        size = preview_size(img.size)
        if size != img.size:
            img = cast(
                Image.Image, cast(Any, img).resize(size, Image.Resampling.LANCZOS)
            )
        return img, size

    def magnifier(self, pad_color: str) -> Image.Image | None:
        img = self.displayed_image()
        if img is None:
            return None
        center = self.mag_center or (img.width // 2, img.height // 2)
        selected = None if self.shows_live() else self.session.selected_position
        return render_magnifier(img, center, selected, pad_color=pad_color)

    def info(self) -> tuple[ColorTuple | None, Position]:
        """기준색과 화면 좌표(고른 픽셀, 없으면 캡처 박스 왼쪽 위)."""
        snap = self.session.snapshot()
        if snap.held_position is not None and snap.selected_position is not None:
            point = (
                snap.held_position[0] + snap.selected_position[0],
                snap.held_position[1] + snap.selected_position[1],
            )
        else:
            point = self.session.current_position()
        return snap.reference_color, point

    def title(self) -> str:
        return txt(
            "Quick Add · {count} saved",
            "빠른 추가 · {count}개 저장",
            count=self.saved_count,
        )

    def status(self) -> tuple[str, Tone]:
        if self.permission_message:
            return self.permission_message, "warn"
        if self.feedback is not None:
            return self.feedback
        snap = self.session.snapshot()
        if snap.latest_image is None:
            return (
                txt(
                    "Hold ALT and move the mouse over the target.",
                    "ALT를 누른 채 대상 위로 마우스를 옮기세요.",
                ),
                "muted",
            )
        if snap.held_image is None or self.moved_off_hold():
            return (
                txt("Press CTRL to freeze this area.", "CTRL로 이 영역을 고정하세요."),
                "muted",
            )
        if snap.selected_position is None:
            return (
                txt(
                    "Click the capture or magnifier to pick the target pixel.",
                    "캡처본이나 돋보기를 클릭해 대상 픽셀을 고르세요.",
                ),
                "muted",
            )
        if self.mode == "continuous":
            return (
                txt(
                    "Press CTRL again (or Apply) to save to Quick.",
                    "CTRL을 한 번 더 누르거나 적용하면 Quick에 저장합니다.",
                ),
                "accent",
            )
        return (
            txt("Press Apply (Enter) to use this capture.", "적용(Enter)을 누르세요."),
            "accent",
        )
