import hashlib
import json
import math
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

from keystroke_models import ProfileModel


BACKGROUND = (248, 247, 242)
TEXT_COLOR = (30, 30, 30)
TEXT_COLOR_FADE = (120, 120, 120)
EDGE_TRUE = (80, 160, 90)
EDGE_FALSE = (190, 80, 80)
EDGE_UNKNOWN = (120, 120, 120)
BORDER_COLOR = (60, 60, 60)
MISSING_FILL = (230, 230, 230)

NODE_W = 200
NODE_H = 60
X_GAP = 28
Y_GAP = 56
MARGIN = 32
TITLE_GAP = 26
TARGET_WIDTH = 1200

# Legend
LEGEND_TOP_PAD = 20
LEGEND_ITEM_H = 22
LEGEND_SWATCH_W = 30
LEGEND_COL_GAP = 24
LEGEND_ROW_GAP = 6

# Group backgrounds
GROUP_BG_ALPHA = 45
GROUP_BG_PAD = 12
GROUP_BG_RADIUS = 14
GROUP_LABEL_PAD = 4

# Bezier
BEZIER_SEGMENTS = 32

# Badges
BADGE_R = 8
BADGE_OFFSET_X = NODE_W - 6
BADGE_OFFSET_Y = -4

BADGE_COLOR_THREAD = (100, 80, 180)
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


@dataclass
class GraphNode:
    node_id: str
    name: str
    label: str
    group_id: str | None
    use_event: bool
    execute_action: bool
    independent_thread: bool
    missing: bool = False


@dataclass
class GraphEdge:
    src: str
    dst: str
    state: bool | None


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
        except Exception:
            pass

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
    nodes, edges = _build_graph(profile)
    positions, width, height = _layout_graph(nodes, edges)

    font = _load_font(14)
    font_small = _load_font(12)

    # Use actual content bottom instead of padded height for legend placement
    content_bottom = MARGIN + TITLE_GAP
    if positions:
        content_bottom = max(y + NODE_H for _, y in positions.values()) + MARGIN
    content_bottom = max(content_bottom, MARGIN + TITLE_GAP + NODE_H + MARGIN)

    legend_h = _calc_legend_height(nodes, font_small)
    total_h = max(height, content_bottom + legend_h)

    img = Image.new("RGBA", (width, total_h), color=BACKGROUND)

    # Z1: Group backgrounds (semi-transparent, drawn first)
    _draw_group_backgrounds(img, nodes, positions, font_small)

    draw = ImageDraw.Draw(img)

    title = f"Profile: {profile_name} ({len(profile.event_list)} events)"
    draw.text((MARGIN, MARGIN - 8), title, fill=TEXT_COLOR, font=font)

    # Z2: Edges (bezier curves)
    edge_offsets = _compute_edge_offsets(edges, positions)
    for edge in edges:
        if edge.src not in positions or edge.dst not in positions:
            continue
        offset = edge_offsets.get((edge.src, edge.dst), 0.0)
        _draw_edge(draw, positions[edge.src], positions[edge.dst], edge.state, font_small, offset)

    # Z3: Nodes (with badges)
    for node in nodes:
        if node.node_id not in positions:
            continue
        _draw_node(draw, node, positions[node.node_id], font, font_small)

    # Z4: Legend at bottom
    _draw_legend(draw, img, nodes, content_bottom, width, font, font_small)

    return img


def _build_graph(profile: ProfileModel) -> Tuple[List[GraphNode], List[GraphEdge]]:
    nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []
    name_map: Dict[str, List[str]] = {}

    for idx, evt in enumerate(profile.event_list):
        raw_name = (evt.event_name or f"Event_{idx + 1}").strip()
        name = raw_name if raw_name else f"Event_{idx + 1}"
        label = name
        node_id = f"evt_{idx}"
        node = GraphNode(
            node_id=node_id,
            name=name,
            label=label,
            group_id=getattr(evt, "group_id", None),
            use_event=getattr(evt, "use_event", True),
            execute_action=getattr(evt, "execute_action", True),
            independent_thread=getattr(evt, "independent_thread", False),
            missing=False,
        )
        nodes.append(node)
        name_map.setdefault(name, []).append(node_id)

    missing_nodes: Dict[str, GraphNode] = {}

    for idx, evt in enumerate(profile.event_list):
        tgt_id = f"evt_{idx}"
        conditions = getattr(evt, "conditions", {}) or {}
        for cond_name, state in conditions.items():
            cond_name = str(cond_name)
            if cond_name in name_map:
                for src_id in name_map[cond_name]:
                    edges.append(GraphEdge(src=src_id, dst=tgt_id, state=state))
            else:
                missing = missing_nodes.get(cond_name)
                if not missing:
                    missing_id = f"missing_{len(missing_nodes)}"
                    missing = GraphNode(
                        node_id=missing_id,
                        name=cond_name,
                        label=f"[MISSING] {cond_name}",
                        group_id=None,
                        use_event=False,
                        execute_action=False,
                        independent_thread=False,
                        missing=True,
                    )
                    missing_nodes[cond_name] = missing
                edges.append(GraphEdge(src=missing.node_id, dst=tgt_id, state=state))

    nodes.extend(missing_nodes.values())
    return nodes, edges


def _build_layers(
    nodes: List[GraphNode],
    edges: List[GraphEdge],
    order_map: Dict[str, int] | None = None,
) -> List[List[str]]:
    node_ids = [n.node_id for n in nodes]
    incoming = {n_id: 0 for n_id in node_ids}
    adjacency: Dict[str, List[str]] = {n_id: [] for n_id in node_ids}

    for edge in edges:
        if edge.src in adjacency and edge.dst in incoming:
            adjacency[edge.src].append(edge.dst)
            incoming[edge.dst] += 1

    if order_map is None:
        order_map = _build_order_map(node_ids, edges)

    layers: List[List[str]] = []
    visited = set()

    while True:
        layer = [
            n_id for n_id in node_ids if incoming[n_id] == 0 and n_id not in visited
        ]
        if not layer:
            break
        layer.sort(key=lambda n_id: order_map.get(n_id, 0))
        layers.append(layer)
        for n_id in layer:
            visited.add(n_id)
            for dst in adjacency.get(n_id, []):
                incoming[dst] -= 1

    remaining = [n_id for n_id in node_ids if n_id not in visited]
    if remaining:
        remaining.sort(key=lambda n_id: order_map.get(n_id, 0))
        layers.append(remaining)

    return layers


def _optimize_layer_order(
    layers: List[List[str]],
    edges: List[GraphEdge],
    base_order: Dict[str, int],
    iterations: int = 2,
) -> List[List[str]]:
    if len(layers) < 2:
        return layers

    incoming_map: Dict[str, List[str]] = {}
    outgoing_map: Dict[str, List[str]] = {}
    for edge in edges:
        incoming_map.setdefault(edge.dst, []).append(edge.src)
        outgoing_map.setdefault(edge.src, []).append(edge.dst)

    def layer_index_map() -> Dict[str, int]:
        index = {}
        for layer in layers:
            for i, node_id in enumerate(layer):
                index[node_id] = i
        return index

    def avg_neighbor_pos(node_id: str, neighbors: List[str], pos_map: Dict[str, int]):
        positions = [pos_map[n] for n in neighbors if n in pos_map]
        if not positions:
            return None
        return sum(positions) / len(positions)

    for _ in range(iterations):
        prev_index = layer_index_map()
        for i in range(1, len(layers)):
            pos_map = {n_id: idx for idx, n_id in enumerate(layers[i - 1])}

            def key(n_id: str):
                bary = avg_neighbor_pos(n_id, incoming_map.get(n_id, []), pos_map)
                if bary is None:
                    return (base_order.get(n_id, 0), base_order.get(n_id, 0))
                return (bary, base_order.get(n_id, 0))

            layers[i] = sorted(layers[i], key=key)

        next_index = layer_index_map()
        for i in range(len(layers) - 2, -1, -1):
            pos_map = {n_id: idx for idx, n_id in enumerate(layers[i + 1])}

            def key(n_id: str):
                bary = avg_neighbor_pos(n_id, outgoing_map.get(n_id, []), pos_map)
                if bary is None:
                    return (base_order.get(n_id, 0), base_order.get(n_id, 0))
                return (bary, base_order.get(n_id, 0))

            layers[i] = sorted(layers[i], key=key)

    return layers


@dataclass
class ComponentLayout:
    node_ids: List[str]
    layers: List[List[str]]
    width: int
    height: int


def _layout_graph(
    nodes: List[GraphNode], edges: List[GraphEdge]
) -> Tuple[Dict[str, Tuple[int, int]], int, int]:
    node_ids = [n.node_id for n in nodes]
    if not node_ids:
        return {}, 640, 480

    order_map = _build_order_map(node_ids, edges)
    levels = _assign_levels(node_ids, edges)
    components = _build_components(node_ids, edges)

    layouts: List[ComponentLayout] = []
    max_cols = _calc_max_cols()
    max_comp_width = 0

    for comp in components:
        comp_layers = _layers_for_component(comp, levels)
        comp_layers = _optimize_layer_order(comp_layers, edges, order_map, iterations=3)
        comp_layers = _wrap_layers(comp_layers, max_cols)
        comp_width, comp_height = _calc_component_size(comp_layers)
        max_comp_width = max(max_comp_width, comp_width)
        layouts.append(
            ComponentLayout(
                node_ids=comp,
                layers=comp_layers,
                width=comp_width,
                height=comp_height,
            )
        )

    layouts.sort(key=lambda c: (-c.height, -c.width))

    max_row_width = max(TARGET_WIDTH, max_comp_width + MARGIN * 2)
    positions, total_w, total_h = _pack_components(layouts, max_row_width)

    total_w = max(640, total_w + MARGIN)
    total_h = max(480, total_h + MARGIN)
    return positions, total_w, total_h


def _layers_for_component(comp: List[str], levels: Dict[str, int]) -> List[List[str]]:
    max_level = 0
    for node_id in comp:
        max_level = max(max_level, levels.get(node_id, 0))

    buckets: List[List[str]] = [[] for _ in range(max_level + 1)]
    for node_id in comp:
        lvl = levels.get(node_id, 0)
        buckets[lvl].append(node_id)

    return [layer for layer in buckets if layer]


def _calc_component_size(layers: List[List[str]]) -> Tuple[int, int]:
    if not layers:
        return NODE_W, NODE_H
    max_nodes_in_row = max(len(layer) for layer in layers)
    width = max_nodes_in_row * NODE_W + max(0, max_nodes_in_row - 1) * X_GAP
    height = len(layers) * NODE_H + max(0, len(layers) - 1) * Y_GAP
    return width, height


def _pack_components(
    components: List[ComponentLayout], max_width: int
) -> Tuple[Dict[str, Tuple[int, int]], int, int]:
    positions: Dict[str, Tuple[int, int]] = {}
    x = MARGIN
    y = MARGIN + TITLE_GAP
    row_h = 0
    max_x = 0

    for comp in components:
        if x > MARGIN and x + comp.width > max_width - MARGIN:
            x = MARGIN
            y += row_h + Y_GAP
            row_h = 0

        local_positions = _layout_component_positions(comp.layers, comp.width)
        for node_id, (lx, ly) in local_positions.items():
            positions[node_id] = (x + lx, y + ly)

        x += comp.width + X_GAP * 2
        row_h = max(row_h, comp.height)
        max_x = max(max_x, x)

    total_w = max_x
    total_h = y + row_h + MARGIN
    return positions, total_w, total_h


def _layout_component_positions(
    layers: List[List[str]], comp_width: int
) -> Dict[str, Tuple[int, int]]:
    positions: Dict[str, Tuple[int, int]] = {}
    y = 0
    for layer in layers:
        row_width = len(layer) * NODE_W + max(0, len(layer) - 1) * X_GAP
        start_x = max(0, (comp_width - row_width) // 2)
        x = start_x
        for node_id in layer:
            positions[node_id] = (x, y)
            x += NODE_W + X_GAP
        y += NODE_H + Y_GAP
    return positions


def _assign_levels(node_ids: List[str], edges: List[GraphEdge]) -> Dict[str, int]:
    incoming = {n_id: 0 for n_id in node_ids}
    adjacency: Dict[str, List[str]] = {n_id: [] for n_id in node_ids}

    for edge in edges:
        if edge.src in adjacency and edge.dst in incoming:
            adjacency[edge.src].append(edge.dst)
            incoming[edge.dst] += 1

    queue = [n_id for n_id in node_ids if incoming[n_id] == 0]
    levels = {n_id: 0 for n_id in node_ids}

    while queue:
        node = queue.pop(0)
        for nxt in adjacency.get(node, []):
            levels[nxt] = max(levels.get(nxt, 0), levels[node] + 1)
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)

    if any(incoming[n_id] > 0 for n_id in node_ids):
        max_level = max(levels.values(), default=0)
        for n_id in node_ids:
            if incoming[n_id] > 0:
                levels[n_id] = max_level + 1

    return levels


def _build_components(node_ids: List[str], edges: List[GraphEdge]) -> List[List[str]]:
    adjacency: Dict[str, List[str]] = {n_id: [] for n_id in node_ids}
    for edge in edges:
        if edge.src in adjacency and edge.dst in adjacency:
            adjacency[edge.src].append(edge.dst)
            adjacency[edge.dst].append(edge.src)

    visited = set()
    components: List[List[str]] = []

    for node in node_ids:
        if node in visited:
            continue
        stack = [node]
        visited.add(node)
        comp = []
        while stack:
            current = stack.pop()
            comp.append(current)
            for nb in adjacency[current]:
                if nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        components.append(comp)

    return components


def _build_order_map(node_ids: List[str], edges: List[GraphEdge]) -> Dict[str, int]:
    base_index = {n_id: idx for idx, n_id in enumerate(node_ids)}
    adjacency: Dict[str, List[str]] = {n_id: [] for n_id in node_ids}
    for edge in edges:
        if edge.src in adjacency and edge.dst in adjacency:
            adjacency[edge.src].append(edge.dst)
            adjacency[edge.dst].append(edge.src)

    order: List[str] = []
    visited = set()

    for start in node_ids:
        if start in visited:
            continue
        queue = [start]
        visited.add(start)
        while queue:
            current = queue.pop(0)
            order.append(current)
            neighbors = sorted(adjacency[current], key=lambda n_id: base_index[n_id])
            for nb in neighbors:
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)

    return {n_id: idx for idx, n_id in enumerate(order)}


def _wrap_layers(layers: List[List[str]], max_cols: int) -> List[List[str]]:
    wrapped: List[List[str]] = []
    for layer in layers:
        if not layer:
            continue
        for i in range(0, len(layer), max_cols):
            wrapped.append(layer[i : i + max_cols])
    return wrapped


def _calc_max_cols() -> int:
    usable = max(320, TARGET_WIDTH - MARGIN * 2)
    cols = (usable + X_GAP) // (NODE_W + X_GAP)
    return max(3, min(8, int(cols)))


def _layout_positions(layers: List[List[str]], canvas_width: int) -> Dict[str, Tuple[int, int]]:
    positions: Dict[str, Tuple[int, int]] = {}
    y = MARGIN + TITLE_GAP

    for layer in layers:
        row_width = len(layer) * NODE_W + max(0, len(layer) - 1) * X_GAP
        start_x = max(MARGIN, (canvas_width - row_width) // 2)
        x = start_x
        for node_id in layer:
            positions[node_id] = (x, y)
            x += NODE_W + X_GAP
        y += NODE_H + Y_GAP

    return positions


def _draw_node(
    draw: ImageDraw.ImageDraw,
    node: GraphNode,
    pos: Tuple[int, int],
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
):
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

    _draw_node_badges(draw, node, pos, font_small)


def _draw_node_badges(
    draw: ImageDraw.ImageDraw,
    node: GraphNode,
    pos: Tuple[int, int],
    font_small: ImageFont.ImageFont,
) -> None:
    badges: List[Tuple[str, Tuple[int, int, int]]] = []
    if node.independent_thread:
        badges.append(("thread", BADGE_COLOR_THREAD))
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
    bg_color: Tuple[int, int, int],
) -> None:
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=bg_color,
        outline=(255, 255, 255),
        width=1,
    )
    white = (255, 255, 255)

    if badge_type == "thread":
        draw.line([(cx - 3, cy - 4), (cx - 3, cy + 4)], fill=white, width=2)
        draw.line([(cx + 3, cy - 4), (cx + 3, cy + 4)], fill=white, width=2)
    elif badge_type == "warn":
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
    src_pos: Tuple[int, int],
    dst_pos: Tuple[int, int],
    state: bool | None,
    font_small: ImageFont.ImageFont,
    offset: float = 0.0,
):
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

    control = _calc_control_point(start, end, offset)
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


def _draw_arrow(draw: ImageDraw.ImageDraw, start, end, color):
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


def _bezier_point(
    t: float,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
) -> Tuple[float, float]:
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
    return (x, y)


def _bezier_tangent(
    t: float,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
) -> Tuple[float, float]:
    dx = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
    dy = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
    return (dx, dy)


def _calc_control_point(
    start: Tuple[int, int],
    end: Tuple[int, int],
    offset: float,
) -> Tuple[float, float]:
    mx = (start[0] + end[0]) / 2.0
    my = (start[1] + end[1]) / 2.0
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-6:
        return (mx + offset, my)
    px = -dy / length
    py = dx / length
    return (mx + px * offset, my + py * offset)


def _compute_edge_offsets(
    edges: List[GraphEdge],
    positions: Dict[str, Tuple[int, int]],
) -> Dict[Tuple[str, str], float]:
    dst_groups: Dict[str, List[Tuple[str, str]]] = {}
    for edge in edges:
        if edge.src not in positions or edge.dst not in positions:
            continue
        dst_groups.setdefault(edge.dst, []).append((edge.src, edge.dst))

    offsets: Dict[Tuple[str, str], float] = {}
    spread = 20.0
    for dst, pairs in dst_groups.items():
        n = len(pairs)
        for i, pair in enumerate(pairs):
            if n == 1:
                offsets[pair] = 0.0
            else:
                offsets[pair] = (i - (n - 1) / 2.0) * spread
    return offsets


def _draw_bezier_arrow(
    draw: ImageDraw.ImageDraw,
    start: Tuple[int, int],
    end: Tuple[int, int],
    control: Tuple[float, float],
    color: Tuple[int, int, int],
) -> Tuple[float, float]:
    points = []
    for i in range(BEZIER_SEGMENTS + 1):
        t = i / BEZIER_SEGMENTS
        points.append(_bezier_point(t, start, control, end))

    total_len = 0.0
    for i in range(1, len(points)):
        dx = points[i][0] - points[i - 1][0]
        dy = points[i][1] - points[i - 1][1]
        total_len += math.sqrt(dx * dx + dy * dy)

    head_len = 10
    trim_len = max(0, total_len - head_len)
    trimmed = [points[0]]
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

    tangent = _bezier_tangent(1.0, start, control, end)
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

    mid = _bezier_point(0.5, start, control, end)
    return mid


def _draw_dashed_rect(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    color,
    dash: int = 6,
    gap: int = 4,
):
    x1, y1, x2, y2 = box
    _draw_dashed_line(draw, (x1, y1), (x2, y1), color, dash, gap)
    _draw_dashed_line(draw, (x1, y2), (x2, y2), color, dash, gap)
    _draw_dashed_line(draw, (x1, y1), (x1, y2), color, dash, gap)
    _draw_dashed_line(draw, (x2, y1), (x2, y2), color, dash, gap)


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: Tuple[int, int],
    end: Tuple[int, int],
    color,
    dash: int,
    gap: int,
):
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
    nodes: List[GraphNode],
    positions: Dict[str, Tuple[int, int]],
    font_small: ImageFont.ImageFont,
) -> Dict[str, Tuple[int, int, int, int]]:
    bounds: Dict[str, List[int]] = {}
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
    result: Dict[str, Tuple[int, int, int, int]] = {}
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
    nodes: List[GraphNode],
    positions: Dict[str, Tuple[int, int]],
    font_small: ImageFont.ImageFont,
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


def _group_color(group_id: str | None) -> Tuple[int, int, int]:
    if not group_id:
        return (220, 220, 220)
    digest = hashlib.md5(group_id.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(PALETTE)
    return PALETTE[idx]


def _fade_color(color: Tuple[int, int, int], bg: Tuple[int, int, int], alpha: float):
    return tuple(int(color[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


def _wrap_label(text: str, width: int, max_lines: int) -> List[str]:
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


def _font_line_height(font: ImageFont.ImageFont) -> int:
    try:
        ascent, descent = font.getmetrics()
        return ascent + descent + 2
    except Exception:
        bbox = font.getbbox("Ag")
        return (bbox[3] - bbox[1]) + 2


def _sanitize_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return safe.strip("_")


def _profile_hash(profile: ProfileModel) -> str:
    payload = []
    for idx, evt in enumerate(profile.event_list):
        payload.append(
            {
                "idx": idx,
                "name": evt.event_name,
                "group": getattr(evt, "group_id", None),
                "priority": getattr(evt, "priority", 0),
                "use_event": getattr(evt, "use_event", True),
                "execute_action": getattr(evt, "execute_action", True),
                "independent_thread": getattr(evt, "independent_thread", False),
                "conditions": getattr(evt, "conditions", {}) or {},
            }
        )
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _calc_legend_height(
    nodes: List[GraphNode],
    font_small: ImageFont.ImageFont,
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
    img: Image.Image,
    nodes: List[GraphNode],
    legend_y: int,
    canvas_width: int,
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> None:
    draw.line(
        [(MARGIN, legend_y), (canvas_width - MARGIN, legend_y)],
        fill=(200, 200, 200),
        width=1,
    )
    draw.text((MARGIN, legend_y + 6), "Legend", fill=TEXT_COLOR, font=font)

    col_width = max(200, (canvas_width - 2 * MARGIN) // 3)
    header_y = legend_y + 26
    y_start = legend_y + 44
    item_step = LEGEND_ITEM_H + LEGEND_ROW_GAP

    # Column 1: Edge types
    col_x = MARGIN
    draw.text((col_x, header_y), "Edges", fill=TEXT_COLOR_FADE, font=font_small)
    edge_items = [
        (EDGE_TRUE, "Active"),
        (EDGE_FALSE, "Inactive"),
        (EDGE_UNKNOWN, "Unknown"),
    ]
    for i, (color, label) in enumerate(edge_items):
        ey = y_start + i * item_step + LEGEND_ITEM_H // 2
        _draw_arrow(draw, (col_x, ey), (col_x + LEGEND_SWATCH_W, ey), color)
        draw.text(
            (col_x + LEGEND_SWATCH_W + 8, y_start + i * item_step + 2),
            label,
            fill=TEXT_COLOR,
            font=font_small,
        )

    # Column 2: Node styles + badges
    col_x = MARGIN + col_width
    draw.text((col_x, header_y), "Nodes", fill=TEXT_COLOR_FADE, font=font_small)

    node_style_items = [
        ("solid", "Normal"),
        ("dashed", "Condition-only"),
        ("faded", "Disabled"),
        ("missing", "Missing ref"),
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
        draw.text((col_x + sw + 6, iy + 2), label, fill=TEXT_COLOR, font=font_small)

    badge_items = [
        ("thread", BADGE_COLOR_THREAD, "Independent thread"),
        ("warn", BADGE_COLOR_MISSING, "Missing reference"),
        ("off", BADGE_COLOR_DISABLED, "Disabled event"),
        ("eye", BADGE_COLOR_CONDITION, "Condition-only"),
    ]
    badge_y_start = y_start + len(node_style_items) * item_step
    for i, (btype, bcolor, blabel) in enumerate(badge_items):
        iy = badge_y_start + i * item_step
        bcx = col_x + 7
        bcy = iy + LEGEND_ITEM_H // 2
        _draw_badge(draw, bcx, bcy, 7, btype, bcolor)
        draw.text((col_x + 20, iy + 2), blabel, fill=TEXT_COLOR, font=font_small)

    # Column 3: Group colors
    groups = sorted(set(n.group_id for n in nodes if n.group_id))
    if groups:
        col_x = MARGIN + col_width * 2
        draw.text((col_x, header_y), "Groups", fill=TEXT_COLOR_FADE, font=font_small)
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
            draw.text((col_x + 32, iy + 2), gid, fill=TEXT_COLOR, font=font_small)


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/AppleGothic.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()
