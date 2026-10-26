from __future__ import annotations

import hashlib
import json
import math
import textwrap
from pathlib import Path
from typing import TypeAlias

from PIL import Image, ImageDraw, ImageFont
from loguru import logger

from app.domain.event_graph_layout import (
    GROUP_BG_PAD,
    MARGIN,
    NODE_H,
    NODE_W,
    TITLE_GAP,
    FloatPoint,
    GraphNode,
    Point,
    bezier_point,
    bezier_tangent,
    build_graph,
    calc_control_point,
    compute_edge_offsets,
    infer_condition_groups,
    layout_graph,
)
from app.domain.models import ProfileModel
from app.ui import tokens as theme

RGB: TypeAlias = tuple[int, int, int]
Box: TypeAlias = tuple[int, int, int, int]
FontLike: TypeAlias = ImageFont.ImageFont | ImageFont.FreeTypeFont


def _rgb(hex_color: str) -> RGB:
    value = hex_color.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )


# App palette in RGB form, derived from app/ui/tokens.py.
BACKGROUND = _rgb(theme.SURFACE_PAPER)
PANEL_BG = _rgb(theme.SURFACE_PANEL)
TEXT_COLOR = _rgb(theme.INK_PRIMARY)
TEXT_COLOR_FADE = _rgb(theme.INK_MUTED)
EDGE_TRUE = _rgb(theme.SIGNAL_BASE)
EDGE_FALSE = _rgb(theme.COND_INACTIVE_FG)
EDGE_UNKNOWN = _rgb(theme.INK_MUTED)
BORDER_COLOR = _rgb(theme.INK_SECONDARY)
DIVIDER_COLOR = _rgb(theme.SURFACE_DIVIDER)
MISSING_FILL = _rgb(theme.SURFACE_SUNKEN)

# Legend
LEGEND_TOP_PAD = 20
LEGEND_ITEM_H = 26
LEGEND_SWATCH_W = 30
LEGEND_ROW_GAP = 6
LEGEND_FONT_SIZE = 14

# Group backgrounds
GROUP_BG_ALPHA = 45
GROUP_BG_RADIUS = 14
GROUP_LABEL_PAD = 4

# Bezier
BEZIER_SEGMENTS = 32

# Badges
BADGE_R = 8
BADGE_OFFSET_Y = -4

BADGE_COLOR_MISSING = (220, 160, 40)
BADGE_COLOR_DISABLED = (160, 160, 160)
BADGE_COLOR_CONDITION = (80, 140, 200)

PALETTE = [
    (244, 206, 201),
    (203, 222, 244),
    (203, 235, 205),
    (242, 231, 194),
    (226, 211, 242),
    (236, 218, 203),
    (210, 232, 240),
    (240, 214, 230),
]


def ensure_profile_graph_image(
    profile: ProfileModel,
    profile_name: str,
    cache_dir: Path,
    force: bool = False,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_filename(profile_name) or "profile"
    img_path = cache_dir / f"{safe_name}.png"
    meta_path = cache_dir / f"{safe_name}.json"

    hash_val = _profile_hash(profile)
    if not force and img_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("hash") == hash_val:
                return img_path
        except Exception as exc:
            logger.debug(f"Profile graph cache metadata ignored: {exc}")

    image = render_profile_graph(profile, profile_name)
    image.save(img_path)

    meta = {
        "hash": hash_val,
        "profile": profile_name,
        "event_count": len(profile.event_list),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return img_path


def render_profile_graph(profile: ProfileModel, profile_name: str) -> Image.Image:
    nodes, edges = build_graph(profile)
    infer_condition_groups(nodes, edges)
    positions, width, height = layout_graph(nodes, edges)

    font = _load_font(14)
    font_small = _load_font(12)
    font_legend = _load_font(LEGEND_FONT_SIZE)

    # Use actual content bottom instead of padded height for legend placement
    content_bottom = MARGIN + TITLE_GAP
    if positions:
        content_bottom = max(y + NODE_H for _, y in positions.values()) + MARGIN
    content_bottom = max(content_bottom, MARGIN + TITLE_GAP + NODE_H + MARGIN)

    legend_h = _calc_legend_height(nodes)
    total_h = max(height, content_bottom + legend_h)

    img = Image.new("RGBA", (width, total_h), color=BACKGROUND)

    # Z1: Group backgrounds (semi-transparent, drawn first)
    _draw_group_backgrounds(img, nodes, positions, font_small)

    draw = ImageDraw.Draw(img)

    # Title gets a calmer panel-tone background pill so it reads as the
    # graph header rather than floating ink on the canvas.
    title = f"Profile: {profile_name} ({len(profile.event_list)} events)"
    t_bbox = draw.textbbox((0, 0), title, font=font)
    tw = t_bbox[2] - t_bbox[0]
    th = t_bbox[3] - t_bbox[1]
    pad_x, pad_y = 10, 6
    draw.rounded_rectangle(
        [MARGIN - pad_x, MARGIN - pad_y - 8, MARGIN + tw + pad_x, MARGIN + th + pad_y - 8],
        radius=8,
        fill=PANEL_BG,
        outline=DIVIDER_COLOR,
        width=1,
    )
    draw.text((MARGIN, MARGIN - 8), title, fill=TEXT_COLOR, font=font)

    # Z2: Edges (bezier curves)
    edge_offsets = compute_edge_offsets(edges, positions)
    for edge in edges:
        if edge.src not in positions or edge.dst not in positions:
            continue
        offset = edge_offsets.get((edge.src, edge.dst), 0.0)
        _draw_edge(draw, positions[edge.src], positions[edge.dst], edge.state, font_small, offset)

    # Z3: Nodes (with badges)
    for node in nodes:
        if node.node_id not in positions:
            continue
        _draw_node(draw, node, positions[node.node_id], font)

    # Z4: Legend at bottom
    _draw_legend(draw, nodes, content_bottom, width, font, font_legend)

    return img


def _draw_node(
    draw: ImageDraw.ImageDraw,
    node: GraphNode,
    pos: Point,
    font: FontLike,
) -> None:
    x, y = pos
    x2, y2 = x + NODE_W, y + NODE_H

    fill = _group_color(node.group_id) if not node.missing else MISSING_FILL
    if not node.use_event:
        fill = _fade_color(fill, BACKGROUND, 0.35)

    draw.rounded_rectangle([x, y, x2, y2], radius=10, fill=fill, outline=BORDER_COLOR, width=2)

    if not node.execute_action:
        _draw_dashed_rect(draw, (x, y, x2, y2), BORDER_COLOR)

    lines = _wrap_label(node.label, _label_wrap_width(), 2)
    text_color = TEXT_COLOR if node.use_event else TEXT_COLOR_FADE

    line_height = _font_line_height(font)
    total_h = len(lines) * line_height
    ty = y + (NODE_H - total_h) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        tx = x + (NODE_W - text_w) // 2
        draw.text((tx, ty), line, fill=text_color, font=font)
        ty += line_height

    _draw_node_badges(draw, node, pos)


def _draw_node_badges(
    draw: ImageDraw.ImageDraw,
    node: GraphNode,
    pos: Point,
) -> None:
    badges: list[tuple[str, RGB]] = []
    if node.missing:
        badges.append(("warn", BADGE_COLOR_MISSING))
    if not node.use_event and not node.missing:
        badges.append(("off", BADGE_COLOR_DISABLED))
    if not node.execute_action and not node.missing:
        badges.append(("eye", BADGE_COLOR_CONDITION))

    if not badges:
        return

    x, y = pos
    bx = x + NODE_W - BADGE_R - 2
    by = y + BADGE_OFFSET_Y
    for i, (badge_type, color) in enumerate(badges):
        cx = bx - i * (BADGE_R * 2 + 3)
        cy = by
        _draw_badge(draw, cx, cy, BADGE_R, badge_type, color)


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    badge_type: str,
    bg_color: RGB,
) -> None:
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=bg_color,
        outline=(255, 255, 255),
        width=1,
    )
    white = (255, 255, 255)

    if badge_type == "warn":
        draw.line([(cx, cy - 4), (cx, cy + 1)], fill=white, width=2)
        draw.ellipse([cx - 1, cy + 3, cx + 1, cy + 5], fill=white)
    elif badge_type == "off":
        r2 = int(radius * 0.6)
        draw.line([(cx - r2, cy - r2), (cx + r2, cy + r2)], fill=white, width=2)
    elif badge_type == "eye":
        draw.arc(
            [cx - 5, cy - 4, cx + 5, cy + 4],
            start=200, end=340, fill=white, width=1,
        )
        draw.arc(
            [cx - 5, cy - 4, cx + 5, cy + 4],
            start=20, end=160, fill=white, width=1,
        )
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=white)


def _draw_edge(
    draw: ImageDraw.ImageDraw,
    src_pos: Point,
    dst_pos: Point,
    state: bool | None,
    font_small: FontLike,
    offset: float = 0.0,
) -> None:
    sx, sy = src_pos
    tx, ty = dst_pos

    if sy == ty:
        start = (sx + NODE_W, sy + NODE_H // 2)
        end = (tx, ty + NODE_H // 2)
    else:
        start = (sx + NODE_W // 2, sy + NODE_H)
        end = (tx + NODE_W // 2, ty)

    if state is True:
        color = EDGE_TRUE
        label = "Active"
    elif state is False:
        color = EDGE_FALSE
        label = "Inactive"
    else:
        color = EDGE_UNKNOWN
        label = ""

    control = calc_control_point(start, end, offset)
    mid = _draw_bezier_arrow(draw, start, end, control, color)

    if label:
        mx = int(mid[0]) + 4
        my = int(mid[1]) - 8
        bbox = draw.textbbox((0, 0), label, font=font_small)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad = 2
        draw.rectangle(
            [mx - pad, my - pad, mx + tw + pad, my + th + pad],
            fill=BACKGROUND,
        )
        draw.text((mx, my), label, fill=color, font=font_small)


def _draw_arrow(draw: ImageDraw.ImageDraw, start: Point, end: Point, color: RGB) -> None:
    draw.line([start, end], fill=color, width=2)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head_len = 10
    head_w = 6

    left = (
        end[0] - head_len * math.cos(angle) + head_w * math.sin(angle),
        end[1] - head_len * math.sin(angle) - head_w * math.cos(angle),
    )
    right = (
        end[0] - head_len * math.cos(angle) - head_w * math.sin(angle),
        end[1] - head_len * math.sin(angle) + head_w * math.cos(angle),
    )
    draw.polygon([end, left, right], fill=color)


def _draw_bezier_arrow(
    draw: ImageDraw.ImageDraw,
    start: Point,
    end: Point,
    control: FloatPoint,
    color: RGB,
) -> FloatPoint:
    points: list[FloatPoint] = []
    for i in range(BEZIER_SEGMENTS + 1):
        t = i / BEZIER_SEGMENTS
        points.append(bezier_point(t, start, control, end))

    total_len = 0.0
    for i in range(1, len(points)):
        dx = points[i][0] - points[i - 1][0]
        dy = points[i][1] - points[i - 1][1]
        total_len += math.sqrt(dx * dx + dy * dy)

    head_len = 10
    trim_len = max(0, total_len - head_len)
    trimmed: list[FloatPoint] = [points[0]]
    accum = 0.0
    for i in range(1, len(points)):
        dx = points[i][0] - points[i - 1][0]
        dy = points[i][1] - points[i - 1][1]
        seg = math.sqrt(dx * dx + dy * dy)
        if accum + seg >= trim_len:
            trimmed.append(points[i])
            break
        accum += seg
        trimmed.append(points[i])

    if len(trimmed) >= 2:
        draw.line([(int(p[0]), int(p[1])) for p in trimmed], fill=color, width=2)

    tangent = bezier_tangent(1.0, start, control, end)
    angle = math.atan2(tangent[1], tangent[0])
    head_w = 6
    left = (
        end[0] - head_len * math.cos(angle) + head_w * math.sin(angle),
        end[1] - head_len * math.sin(angle) - head_w * math.cos(angle),
    )
    right = (
        end[0] - head_len * math.cos(angle) - head_w * math.sin(angle),
        end[1] - head_len * math.sin(angle) + head_w * math.cos(angle),
    )
    draw.polygon([end, left, right], fill=color)

    mid = bezier_point(0.5, start, control, end)
    return mid


def _draw_dashed_rect(
    draw: ImageDraw.ImageDraw,
    box: Box,
    color: RGB,
    dash: int = 6,
    gap: int = 4,
) -> None:
    x1, y1, x2, y2 = box
    _draw_dashed_line(draw, (x1, y1), (x2, y1), color, dash, gap)
    _draw_dashed_line(draw, (x1, y2), (x2, y2), color, dash, gap)
    _draw_dashed_line(draw, (x1, y1), (x1, y2), color, dash, gap)
    _draw_dashed_line(draw, (x2, y1), (x2, y2), color, dash, gap)


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: Point,
    end: Point,
    color: RGB,
    dash: int,
    gap: int,
) -> None:
    x1, y1 = start
    x2, y2 = end

    if x1 == x2:
        length = abs(y2 - y1)
        step = dash + gap
        y = min(y1, y2)
        while y < min(y1, y2) + length:
            y_end = min(y + dash, min(y1, y2) + length)
            draw.line([(x1, y), (x1, y_end)], fill=color, width=2)
            y += step
    else:
        length = abs(x2 - x1)
        step = dash + gap
        x = min(x1, x2)
        while x < min(x1, x2) + length:
            x_end = min(x + dash, min(x1, x2) + length)
            draw.line([(x, y1), (x_end, y1)], fill=color, width=2)
            x += step


def _compute_group_bounds(
    nodes: list[GraphNode],
    positions: dict[str, Point],
    font_small: FontLike,
) -> dict[str, Box]:
    bounds: dict[str, list[int]] = {}
    for node in nodes:
        if not node.group_id or node.node_id not in positions:
            continue
        gid = node.group_id
        x, y = positions[node.node_id]
        if gid not in bounds:
            bounds[gid] = [x, y, x + NODE_W, y + NODE_H]
        else:
            b = bounds[gid]
            b[0] = min(b[0], x)
            b[1] = min(b[1], y)
            b[2] = max(b[2], x + NODE_W)
            b[3] = max(b[3], y + NODE_H)

    label_h = _font_line_height(font_small)
    result: dict[str, Box] = {}
    for gid, b in bounds.items():
        result[gid] = (
            b[0] - GROUP_BG_PAD,
            b[1] - GROUP_BG_PAD - label_h - 2,
            b[2] + GROUP_BG_PAD,
            b[3] + GROUP_BG_PAD,
        )
    return result


def _draw_group_backgrounds(
    img: Image.Image,
    nodes: list[GraphNode],
    positions: dict[str, Point],
    font_small: FontLike,
) -> None:
    bounds = _compute_group_bounds(nodes, positions, font_small)
    if not bounds:
        return

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")

    for gid, (x1, y1, x2, y2) in bounds.items():
        color = _group_color(gid)
        fill = (*color, GROUP_BG_ALPHA)
        border = (
            max(0, color[0] - 30),
            max(0, color[1] - 30),
            max(0, color[2] - 30),
            GROUP_BG_ALPHA + 50,
        )
        overlay_draw.rounded_rectangle(
            [x1, y1, x2, y2],
            radius=GROUP_BG_RADIUS,
            fill=fill,
            outline=border,
            width=1,
        )
        overlay_draw.text(
            (x1 + GROUP_LABEL_PAD, y1 + 2),
            gid,
            fill=(*TEXT_COLOR, 200),
            font=font_small,
        )

    composited = Image.alpha_composite(img, overlay)
    img.paste(composited)


def _group_color(group_id: str | None) -> RGB:
    if not group_id:
        return (220, 220, 220)
    digest = hashlib.md5(group_id.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(PALETTE)
    return PALETTE[idx]


def _fade_color(color: RGB, bg: RGB, alpha: float) -> RGB:
    return (
        int(color[0] * alpha + bg[0] * (1 - alpha)),
        int(color[1] * alpha + bg[1] * (1 - alpha)),
        int(color[2] * alpha + bg[2] * (1 - alpha)),
    )


def _wrap_label(text: str, width: int, max_lines: int) -> list[str]:
    lines = textwrap.wrap(text, width=width)
    if not lines:
        return [""]
    if len(lines) <= max_lines:
        return lines
    trimmed = lines[:max_lines]
    trimmed[-1] = trimmed[-1][:-3] + "..." if len(trimmed[-1]) > 3 else trimmed[-1] + "..."
    return trimmed


def _label_wrap_width() -> int:
    return max(12, min(20, int(NODE_W / 12)))


def _font_line_height(font: FontLike) -> int:
    try:
        if isinstance(font, ImageFont.FreeTypeFont):
            ascent, descent = font.getmetrics()
            return ascent + descent + 2
    except Exception:
        pass
    bbox = font.getbbox("Ag")
    return int(bbox[3] - bbox[1]) + 2


def _sanitize_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return safe.strip("_")


# Bumping this string invalidates previously cached graph PNGs so changes
# to the rendering palette take effect on the next render.
RENDER_VERSION = "ws-v2"


def _profile_hash(profile: ProfileModel) -> str:
    events_payload: list[dict[str, object]] = []
    payload = {
        "render_version": RENDER_VERSION,
        "events": events_payload,
    }
    for idx, evt in enumerate(profile.event_list):
        events_payload.append(
            {
                "idx": idx,
                "name": evt.event_name,
                "group": evt.group_id,
                "priority": evt.priority,
                "use_event": evt.use_event,
                "execute_action": evt.execute_action,
                "conditions": evt.conditions,
            }
        )
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _calc_legend_height(
    nodes: list[GraphNode],
) -> int:
    groups = sorted(set(n.group_id for n in nodes if n.group_id))
    edge_rows = 3
    node_rows = 4
    badge_rows = 4
    group_rows = max(0, len(groups))
    col_left = edge_rows
    col_mid = node_rows + badge_rows
    col_right = group_rows
    max_rows = max(col_left, col_mid, col_right, 1)
    return LEGEND_TOP_PAD + 44 + max_rows * (LEGEND_ITEM_H + LEGEND_ROW_GAP) + MARGIN


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    nodes: list[GraphNode],
    legend_y: int,
    canvas_width: int,
    font: FontLike,
    font_legend: FontLike,
) -> None:
    # Card-style legend on the workstation panel tone — matches Settings /
    # Editor cards instead of the previous bare horizontal divider.
    card_pad = 14
    card_h = _calc_legend_height(nodes) - MARGIN
    draw.rounded_rectangle(
        [
            MARGIN - card_pad,
            legend_y - card_pad // 2,
            canvas_width - MARGIN + card_pad,
            legend_y + card_h,
        ],
        radius=10,
        fill=PANEL_BG,
        outline=DIVIDER_COLOR,
        width=1,
    )
    draw.text((MARGIN, legend_y + 6), "Legend", fill=TEXT_COLOR, font=font)

    col_width = max(200, (canvas_width - 2 * MARGIN) // 3)
    header_y = legend_y + 26
    y_start = legend_y + 44
    item_step = LEGEND_ITEM_H + LEGEND_ROW_GAP

    # Column 1: Edge types
    col_x = MARGIN
    draw.text((col_x, header_y), "Edges", fill=TEXT_COLOR_FADE, font=font_legend)
    edge_items = [
        (EDGE_TRUE, "Active (활성)"),
        (EDGE_FALSE, "Inactive (비활성)"),
        (EDGE_UNKNOWN, "Unknown (알 수 없음)"),
    ]
    for i, (color, label) in enumerate(edge_items):
        ey = y_start + i * item_step + LEGEND_ITEM_H // 2
        _draw_arrow(draw, (col_x, ey), (col_x + LEGEND_SWATCH_W, ey), color)
        draw.text(
            (col_x + LEGEND_SWATCH_W + 8, y_start + i * item_step + 2),
            label,
            fill=TEXT_COLOR,
            font=font_legend,
        )

    # Column 2: Node styles + badges
    col_x = MARGIN + col_width
    draw.text((col_x, header_y), "Nodes", fill=TEXT_COLOR_FADE, font=font_legend)

    node_style_items = [
        ("solid", "Normal (일반)"),
        ("dashed", "Signal (신호)"),
        ("faded", "Disabled (사용 안 함)"),
        ("missing", "Missing ref (참조 누락)"),
    ]
    for i, (style, label) in enumerate(node_style_items):
        iy = y_start + i * item_step
        sx, sy = col_x, iy + 2
        sw, sh = 26, 16
        if style == "solid":
            fill = PALETTE[1]
            draw.rounded_rectangle(
                [sx, sy, sx + sw, sy + sh], radius=4, fill=fill, outline=BORDER_COLOR, width=1,
            )
        elif style == "dashed":
            fill = PALETTE[1]
            draw.rounded_rectangle(
                [sx, sy, sx + sw, sy + sh], radius=4, fill=fill, outline=BACKGROUND, width=1,
            )
            _draw_dashed_rect(draw, (sx, sy, sx + sw, sy + sh), BORDER_COLOR, dash=3, gap=2)
        elif style == "faded":
            fill = _fade_color(PALETTE[1], BACKGROUND, 0.35)
            draw.rounded_rectangle(
                [sx, sy, sx + sw, sy + sh], radius=4, fill=fill, outline=BORDER_COLOR, width=1,
            )
        elif style == "missing":
            draw.rounded_rectangle(
                [sx, sy, sx + sw, sy + sh], radius=4, fill=MISSING_FILL, outline=BORDER_COLOR, width=1,
            )
        draw.text((col_x + sw + 6, iy + 2), label, fill=TEXT_COLOR, font=font_legend)

    badge_items = [
        ("warn", BADGE_COLOR_MISSING, "Missing reference (참조 누락)"),
        ("off", BADGE_COLOR_DISABLED, "Disabled event (비활성 이벤트)"),
        ("eye", BADGE_COLOR_CONDITION, "Signal (신호)"),
    ]
    badge_y_start = y_start + len(node_style_items) * item_step
    for i, (btype, bcolor, blabel) in enumerate(badge_items):
        iy = badge_y_start + i * item_step
        bcx = col_x + 7
        bcy = iy + LEGEND_ITEM_H // 2
        _draw_badge(draw, bcx, bcy, 7, btype, bcolor)
        draw.text((col_x + 20, iy + 2), blabel, fill=TEXT_COLOR, font=font_legend)

    # Column 3: Group colors
    groups = sorted(set(n.group_id for n in nodes if n.group_id))
    if groups:
        col_x = MARGIN + col_width * 2
        draw.text((col_x, header_y), "Groups", fill=TEXT_COLOR_FADE, font=font_legend)
        for i, gid in enumerate(groups):
            iy = y_start + i * item_step
            gcolor = _group_color(gid)
            draw.rounded_rectangle(
                [col_x, iy + 2, col_x + 26, iy + 18],
                radius=4,
                fill=gcolor,
                outline=BORDER_COLOR,
                width=1,
            )
            draw.text((col_x + 32, iy + 2), gid, fill=TEXT_COLOR, font=font_legend)


def _load_font(size: int) -> FontLike:
    # Korean / multilingual fallback chain — macOS, Windows, Linux paths.
    candidates = [
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/AppleGothic.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        # Windows Korean font fallbacks
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/gulim.ttc",
        # Linux Korean fallbacks (Noto family)
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()
