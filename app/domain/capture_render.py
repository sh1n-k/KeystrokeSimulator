"""캡처 미리보기 위에 그리는 PIL 렌더(대상 픽셀 표시·돋보기). UI 툴킷과 무관하다."""

from __future__ import annotations

from typing import Any, cast

from PIL import Image, ImageDraw

from app.domain.capture_geometry import MAGNIFIER_SPAN, MAGNIFIER_ZOOM
from app.domain.models import ColorTuple, Position


def render_magnifier(
    image: Image.Image,
    center: Position,
    selected: Position | None,
    *,
    pad_color: str,
) -> Image.Image:
    """center 주변 MAGNIFIER_SPAN 픽셀을 확대한다. 원본 밖은 pad_color로 채운다.
    선택 픽셀은 사각형으로 두르고 그 칸 가운데를 지나는 반전 십자선을 긋는다."""
    half = MAGNIFIER_SPAN // 2
    left, top = center[0] - half, center[1] - half
    src = Image.new("RGB", (MAGNIFIER_SPAN, MAGNIFIER_SPAN), pad_color)
    clip = (
        max(0, left),
        max(0, top),
        min(image.width, left + MAGNIFIER_SPAN),
        min(image.height, top + MAGNIFIER_SPAN),
    )
    if clip[0] < clip[2] and clip[1] < clip[3]:
        src.paste(image.convert("RGB").crop(clip), (clip[0] - left, clip[1] - top))
    size = MAGNIFIER_SPAN * MAGNIFIER_ZOOM
    zoomed = cast(
        Image.Image, cast(Any, src).resize((size, size), Image.Resampling.NEAREST)
    )
    draw = ImageDraw.Draw(zoomed)
    if selected is not None:
        sx, sy = selected[0] - left, selected[1] - top
        if 0 <= sx < MAGNIFIER_SPAN and 0 <= sy < MAGNIFIER_SPAN:
            x0, y0 = sx * MAGNIFIER_ZOOM, sy * MAGNIFIER_ZOOM
            x1, y1 = x0 + MAGNIFIER_ZOOM - 1, y0 + MAGNIFIER_ZOOM - 1
            _invert_cross(
                zoomed,
                (x0 + MAGNIFIER_ZOOM // 2, y0 + MAGNIFIER_ZOOM // 2),
                skip=(x0 - 1, y0 - 1, x1 + 1, y1 + 1),
            )
            draw.rectangle([x0 - 1, y0 - 1, x1 + 1, y1 + 1], outline="white")
            draw.rectangle([x0, y0, x1, y1], outline="black")
    return zoomed


def _invert_cross(
    image: Image.Image, center: Position, skip: tuple[int, int, int, int]
) -> None:
    """center를 지나는 가로·세로 1px 반전선. skip 사각형 안은 건드리지 않는다."""
    pixels = cast(Any, image.load())
    cx, cy = center
    sx0, sy0, sx1, sy1 = skip
    for x in range(image.width):
        if not sx0 <= x <= sx1:
            r, g, b = pixels[x, cy]
            pixels[x, cy] = (255 - r, 255 - g, 255 - b)
    for y in range(image.height):
        if not sy0 <= y <= sy1:
            r, g, b = pixels[cx, y]
            pixels[cx, y] = (255 - r, 255 - g, 255 - b)


def render_overlay(
    image: Image.Image, pixel: Position | None, region_size: Position | None = None
) -> Image.Image:
    """대상 픽셀 표시. 픽셀 모드는 반전 십자선, 영역 모드는 영역 사각형."""
    res = image.convert("RGB")  # always a copy
    if pixel is None:
        return res
    cx, cy = pixel
    w, h = res.size
    if not (0 <= cx < w and 0 <= cy < h):
        return res
    if region_size is not None:
        rw, rh = region_size[0] // 2, region_size[1] // 2
        draw = ImageDraw.Draw(res)
        draw.rectangle(
            [max(0, cx - rw), max(0, cy - rh), min(w, cx + rw), min(h, cy + rh)],
            outline="yellow",
            width=2,
        )
        return res
    pixels = cast(Any, res.load())
    for x in range(w):
        r, g, b = pixels[x, cy]
        pixels[x, cy] = (255 - r, 255 - g, 255 - b)
    for y in range(h):
        if y == cy:
            continue
        r, g, b = pixels[cx, y]
        pixels[cx, y] = (255 - r, 255 - g, 255 - b)
    return res


def color_hex(color: ColorTuple) -> str:
    r, g, b = (int(c) for c in color[:3])
    return f"#{r:02x}{g:02x}{b:02x}"
