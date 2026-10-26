"""이벤트 편집 규칙: 실행 불가 사유, 캡처 적용·지우기, 영역 크기 보정. UI 툴킷과 무관하다."""

from __future__ import annotations

from app.domain.capture_geometry import CaptureResult
from app.domain.models import EventModel
from app.domain.profile_events import event_has_screen
from app.domain.validation import MIN_REGION_SIZE, region_limits
from app.utils.i18n import txt


def event_issues(event: EventModel) -> list[str]:
    """실행되지 않는 이유. 비어 있으면 실행할 수 있다."""
    issues: list[str] = []
    if event.execute_action:
        if not (event.key_to_enter or "").strip():
            issues.append(txt("No input key: this rule cannot run.", "키 없음: 이 규칙은 실행되지 않습니다."))
        if not event_has_screen(event) and not event.conditions:
            issues.append(
                txt(
                    "Add a condition or capture a screen trigger.",
                    "조건을 추가하거나 화면 트리거를 캡처하세요.",
                )
            )
    elif not event_has_screen(event):
        issues.append(
            txt("A signal needs a screen. Capture one.", "신호에는 화면이 필요합니다. 캡처하세요.")
        )
    if event.match_mode == "region" and event.held_screenshot is None:
        issues.append(txt("Region mode needs a capture.", "영역 모드에는 캡처본이 필요합니다."))
    return issues


def capture_from_event(event: EventModel) -> CaptureResult | None:
    if (
        event.latest_position is None
        or event.clicked_position is None
        or event.held_screenshot is None
        or event.ref_pixel_value is None
    ):
        return None
    return CaptureResult(
        position=event.latest_position,
        capture_size=event.capture_size or event.held_screenshot.size,
        image=event.held_screenshot,
        pixel=event.clicked_position,
        color=event.ref_pixel_value,
    )


def apply_capture(event: EventModel, result: CaptureResult) -> None:
    event.latest_position = result.position
    event.clicked_position = result.pixel
    event.held_screenshot = result.image
    event.ref_pixel_value = result.color
    event.capture_size = result.capture_size
    clamp_region(event)


def clear_capture(event: EventModel) -> None:
    event.latest_position = None
    event.clicked_position = None
    event.held_screenshot = None
    event.ref_pixel_value = None
    event.match_mode = "pixel"
    event.invert_match = False
    event.region_size = None


def clamp_region(event: EventModel) -> None:
    """영역 크기를 캡처본 안으로 줄인다. 캡처가 없으면 그대로 둔다."""
    if event.match_mode != "region" or event.held_screenshot is None:
        return
    if event.clicked_position is None:
        return
    max_w, max_h = region_limits(event.held_screenshot.size, event.clicked_position)
    w, h = event.region_size or (100, 100)
    event.region_size = (
        max(min(MIN_REGION_SIZE, max_w), min(w, max_w)),
        max(min(MIN_REGION_SIZE, max_h), min(h, max_h)),
    )
