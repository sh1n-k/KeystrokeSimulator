"""캡처 박스·미리보기·돋보기·HUD 위치 계산과 적용한 캡처 결과. UI 툴킷과 무관하다."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from app.domain.models import ColorTuple, Position

MIN_CAPTURE_SIZE = 50
MAX_CAPTURE_SIZE = 1000

PREVIEW_MAX = 200
MAGNIFIER_ZOOM = 8
MAGNIFIER_SPAN = 11  # 원본 픽셀 수(홀수라 가운데 픽셀이 있다)
HUD_MARGIN = 16

# (left, top, width, height) in screen coordinates.
Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class CaptureResult:
    """적용한 캡처. position은 캡처 박스의 왼쪽 위(화면 좌표)다."""

    position: Position
    capture_size: Position
    image: Image.Image
    pixel: Position
    color: ColorTuple


def capture_rect(position: Position, size: Position) -> Rect:
    """캡처 박스. `ScreenshotCapturer._capture_group`처럼 좌표가 왼쪽 위다."""
    return (position[0], position[1], size[0], size[1])


def rects_overlap(a: Rect, b: Rect) -> bool:
    return not (
        a[0] + a[2] <= b[0]
        or b[0] + b[2] <= a[0]
        or a[1] + a[3] <= b[1]
        or b[1] + b[3] <= a[1]
    )


def preview_size(image_size: Position) -> Position:
    """1:1로 보여주되 긴 변을 PREVIEW_MAX로 제한한다."""
    w, h = image_size
    scale = min(1.0, PREVIEW_MAX / max(1, w), PREVIEW_MAX / max(1, h))
    return (max(1, int(w * scale)), max(1, int(h * scale)))


def display_to_image(
    point: Position, display_size: Position, image_size: Position
) -> Position | None:
    dw, dh = display_size
    if dw <= 0 or dh <= 0:
        return None
    x = int(point[0] * image_size[0] / dw)
    y = int(point[1] * image_size[1] / dh)
    if not (0 <= x < image_size[0] and 0 <= y < image_size[1]):
        return None
    return (x, y)


def magnifier_to_image(
    point: Position, center: Position, image_size: Position
) -> Position | None:
    """돋보기 좌표를 원본 픽셀 좌표로 바꾼다. 원본 밖이면 None."""
    half = MAGNIFIER_SPAN // 2
    x = center[0] - half + point[0] // MAGNIFIER_ZOOM
    y = center[1] - half + point[1] // MAGNIFIER_ZOOM
    if not (0 <= x < image_size[0] and 0 <= y < image_size[1]):
        return None
    return (x, y)


def hud_position(
    hud: Rect, box: Rect, screen: Position, margin: int = HUD_MARGIN
) -> Position | None:
    """HUD가 캡처 박스와 겹치면 박스 반대편 화면 모서리 위치. 안 겹치면 None."""
    if not rects_overlap(hud, box):
        return None
    _, _, w, h = hud
    sw, sh = screen
    near_x, far_x = margin, sw - w - margin
    near_y, far_y = margin, sh - h - margin
    box_cx, box_cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    xs = (near_x, far_x) if box_cx > sw / 2 else (far_x, near_x)
    ys = (near_y, far_y) if box_cy > sh / 2 else (far_y, near_y)
    candidates = [(xs[0], ys[0]), (xs[0], ys[1]), (xs[1], ys[0]), (xs[1], ys[1])]
    clamped = [
        (max(0, min(x, sw - w)), max(0, min(y, sh - h))) for x, y in candidates
    ]
    for x, y in clamped:
        if not rects_overlap((x, y, w, h), box):
            return (x, y)
    return clamped[0]


def border_rects(box: Rect, thickness: int) -> list[Rect]:
    """캡처 박스 바깥쪽 테두리 4개(위, 아래, 왼쪽, 오른쪽). 박스 안은 덮지 않는다."""
    x, y, w, h = box
    t = thickness
    return [
        (x - t, y - t, w + 2 * t, t),
        (x - t, y + h, w + 2 * t, t),
        (x - t, y, t, h),
        (x + w, y, t, h),
    ]
