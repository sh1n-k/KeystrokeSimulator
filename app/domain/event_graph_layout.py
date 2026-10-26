"""조건·그룹 관계 그래프의 노드·간선 구성과 배치 계산. 그리기는 app/ui/event_graph.py가 한다."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeAlias

from app.domain.models import ProfileModel

Point: TypeAlias = tuple[int, int]
FloatPoint: TypeAlias = tuple[float, float]

NODE_W = 200
NODE_H = 60
X_GAP = 28
Y_GAP = 56
MARGIN = 32
TITLE_GAP = 68
TARGET_WIDTH = 1200
# 그룹 배경 여백. 같은 줄의 다른 그룹 사이 간격 계산에도 쓴다.
GROUP_BG_PAD = 28


@dataclass
class GraphNode:
    node_id: str
    name: str
    label: str
    group_id: str | None
    use_event: bool
    execute_action: bool
    missing: bool = False


@dataclass
class GraphEdge:
    src: str
    dst: str
    state: bool | None


def build_graph(profile: ProfileModel) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    name_map: dict[str, list[str]] = {}

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
            missing=False,
        )
        nodes.append(node)
        name_map.setdefault(name, []).append(node_id)

    missing_nodes: dict[str, GraphNode] = {}

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
                        missing=True,
                    )
                    missing_nodes[cond_name] = missing
                edges.append(GraphEdge(src=missing.node_id, dst=tgt_id, state=state))

    nodes.extend(missing_nodes.values())
    return nodes, edges


def infer_condition_groups(nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
    """Infer group_id for ungrouped condition-only nodes from their edge targets."""
    node_map = {n.node_id: n for n in nodes}
    for node in nodes:
        if node.group_id or node.execute_action:
            continue
        target_groups: set[str] = set()
        has_targets = False
        for edge in edges:
            if edge.src == node.node_id:
                has_targets = True
                dst = node_map.get(edge.dst)
                if dst and dst.group_id:
                    target_groups.add(dst.group_id)
        if has_targets and len(target_groups) == 1:
            node.group_id = target_groups.pop()


def _optimize_layer_order(
    layers: list[list[str]],
    edges: list[GraphEdge],
    base_order: dict[str, int],
    iterations: int = 2,
) -> list[list[str]]:
    if len(layers) < 2:
        return layers

    incoming_map: dict[str, list[str]] = {}
    outgoing_map: dict[str, list[str]] = {}
    for edge in edges:
        incoming_map.setdefault(edge.dst, []).append(edge.src)
        outgoing_map.setdefault(edge.src, []).append(edge.dst)

    def avg_neighbor_pos(neighbors: list[str], pos_map: dict[str, int]) -> float | None:
        positions = [pos_map[n] for n in neighbors if n in pos_map]
        if not positions:
            return None
        return sum(positions) / len(positions)

    for _ in range(iterations):
        for i in range(1, len(layers)):
            pos_map = {n_id: idx for idx, n_id in enumerate(layers[i - 1])}

            def key(n_id: str, pos_map: dict[str, int] = pos_map) -> tuple[float, int]:
                bary = avg_neighbor_pos(incoming_map.get(n_id, []), pos_map)
                if bary is None:
                    order = base_order.get(n_id, 0)
                    return (float(order), order)
                return (bary, base_order.get(n_id, 0))

            layers[i] = sorted(layers[i], key=key)

        for i in range(len(layers) - 2, -1, -1):
            pos_map = {n_id: idx for idx, n_id in enumerate(layers[i + 1])}

            def key(n_id: str, pos_map: dict[str, int] = pos_map) -> tuple[float, int]:
                bary = avg_neighbor_pos(outgoing_map.get(n_id, []), pos_map)
                if bary is None:
                    order = base_order.get(n_id, 0)
                    return (float(order), order)
                return (bary, base_order.get(n_id, 0))

            layers[i] = sorted(layers[i], key=key)

    return layers


@dataclass
class ComponentLayout:
    node_ids: list[str]
    layers: list[list[str]]
    width: int
    height: int


def layout_graph(
    nodes: list[GraphNode], edges: list[GraphEdge]
) -> tuple[dict[str, Point], int, int]:
    node_ids = [n.node_id for n in nodes]
    if not node_ids:
        return {}, 640, 480

    node_map = {n.node_id: n for n in nodes}
    order_map = _build_order_map(node_ids, edges)
    levels = _assign_levels(node_ids, edges)
    components = _build_components(node_ids, edges)

    layouts: list[ComponentLayout] = []
    max_cols = _calc_max_cols()
    max_comp_width = 0

    for comp in components:
        comp_layers = _layers_for_component(comp, levels)
        comp_layers = _optimize_layer_order(comp_layers, edges, order_map, iterations=3)
        comp_layers = _wrap_layers(comp_layers, max_cols)
        comp_width, comp_height = _calc_component_size(comp_layers, node_map)
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
    positions, total_w, total_h = _pack_components(layouts, max_row_width, node_map)

    total_w = max(640, total_w + MARGIN)
    total_h = max(480, total_h + MARGIN)
    return positions, total_w, total_h


def _layers_for_component(comp: list[str], levels: dict[str, int]) -> list[list[str]]:
    max_level = 0
    for node_id in comp:
        max_level = max(max_level, levels.get(node_id, 0))

    buckets: list[list[str]] = [[] for _ in range(max_level + 1)]
    for node_id in comp:
        lvl = levels.get(node_id, 0)
        buckets[lvl].append(node_id)

    return [layer for layer in buckets if layer]


def _count_group_breaks(layer: list[str], node_map: dict[str, GraphNode]) -> int:
    breaks = 0
    for i in range(1, len(layer)):
        g_prev = node_map[layer[i - 1]].group_id if layer[i - 1] in node_map else None
        g_curr = node_map[layer[i]].group_id if layer[i] in node_map else None
        if g_prev != g_curr:
            breaks += 1
    return breaks


def _calc_component_size(
    layers: list[list[str]],
    node_map: dict[str, GraphNode] | None = None,
) -> tuple[int, int]:
    if not layers:
        return NODE_W, NODE_H
    if node_map is None:
        node_map = {}
    group_gap = GROUP_BG_PAD * 2
    max_width = 0
    for layer in layers:
        n = len(layer)
        breaks = _count_group_breaks(layer, node_map)
        row_w = n * NODE_W + max(0, n - 1 - breaks) * X_GAP + breaks * (X_GAP + group_gap)
        max_width = max(max_width, row_w)
    height = len(layers) * NODE_H + max(0, len(layers) - 1) * Y_GAP
    return max_width, height


def _pack_components(
    components: list[ComponentLayout],
    max_width: int,
    node_map: dict[str, GraphNode] | None = None,
) -> tuple[dict[str, Point], int, int]:
    if node_map is None:
        node_map = {}
    positions: dict[str, Point] = {}
    x = MARGIN
    y = MARGIN + TITLE_GAP
    row_h = 0
    max_x = 0

    for comp in components:
        if x > MARGIN and x + comp.width > max_width - MARGIN:
            x = MARGIN
            y += row_h + Y_GAP
            row_h = 0

        local_positions = _layout_component_positions(comp.layers, comp.width, node_map)
        for node_id, (lx, ly) in local_positions.items():
            positions[node_id] = (x + lx, y + ly)

        x += comp.width + X_GAP * 2
        row_h = max(row_h, comp.height)
        max_x = max(max_x, x)

    total_w = max_x
    total_h = y + row_h + MARGIN
    return positions, total_w, total_h


def _layout_component_positions(
    layers: list[list[str]],
    comp_width: int,
    node_map: dict[str, GraphNode] | None = None,
) -> dict[str, Point]:
    if node_map is None:
        node_map = {}
    group_gap = GROUP_BG_PAD * 2
    positions: dict[str, Point] = {}
    y = 0
    for layer in layers:
        breaks = _count_group_breaks(layer, node_map)
        n = len(layer)
        row_width = n * NODE_W + max(0, n - 1 - breaks) * X_GAP + breaks * (X_GAP + group_gap)
        start_x = max(0, (comp_width - row_width) // 2)
        x = start_x
        for i, node_id in enumerate(layer):
            positions[node_id] = (x, y)
            gap = X_GAP
            if i + 1 < n:
                g_curr = node_map[node_id].group_id if node_id in node_map else None
                g_next = node_map[layer[i + 1]].group_id if layer[i + 1] in node_map else None
                if g_curr != g_next:
                    gap = X_GAP + group_gap
            x += NODE_W + gap
        y += NODE_H + Y_GAP
    return positions


def _assign_levels(node_ids: list[str], edges: list[GraphEdge]) -> dict[str, int]:
    incoming = {n_id: 0 for n_id in node_ids}
    adjacency: dict[str, list[str]] = {n_id: [] for n_id in node_ids}

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


def _build_components(node_ids: list[str], edges: list[GraphEdge]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = {n_id: [] for n_id in node_ids}
    for edge in edges:
        if edge.src in adjacency and edge.dst in adjacency:
            adjacency[edge.src].append(edge.dst)
            adjacency[edge.dst].append(edge.src)

    visited: set[str] = set()
    components: list[list[str]] = []

    for node in node_ids:
        if node in visited:
            continue
        stack: list[str] = [node]
        visited.add(node)
        comp: list[str] = []
        while stack:
            current = stack.pop()
            comp.append(current)
            for nb in adjacency[current]:
                if nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        components.append(comp)

    return components


def _build_order_map(node_ids: list[str], edges: list[GraphEdge]) -> dict[str, int]:
    base_index = {n_id: idx for idx, n_id in enumerate(node_ids)}
    adjacency: dict[str, list[str]] = {n_id: [] for n_id in node_ids}
    for edge in edges:
        if edge.src in adjacency and edge.dst in adjacency:
            adjacency[edge.src].append(edge.dst)
            adjacency[edge.dst].append(edge.src)

    order: list[str] = []
    visited: set[str] = set()

    for start in node_ids:
        if start in visited:
            continue
        queue: list[str] = [start]
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


def _wrap_layers(layers: list[list[str]], max_cols: int) -> list[list[str]]:
    wrapped: list[list[str]] = []
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


def compute_edge_offsets(
    edges: list[GraphEdge],
    positions: dict[str, Point],
) -> dict[tuple[str, str], float]:
    dst_groups: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        if edge.src not in positions or edge.dst not in positions:
            continue
        dst_groups.setdefault(edge.dst, []).append((edge.src, edge.dst))

    offsets: dict[tuple[str, str], float] = {}
    spread = 20.0
    for _dst, pairs in dst_groups.items():
        n = len(pairs)
        for i, pair in enumerate(pairs):
            if n == 1:
                offsets[pair] = 0.0
            else:
                offsets[pair] = (i - (n - 1) / 2.0) * spread
    return offsets


def bezier_point(
    t: float,
    p0: FloatPoint,
    p1: FloatPoint,
    p2: FloatPoint,
) -> FloatPoint:
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
    return (x, y)


def bezier_tangent(
    t: float,
    p0: FloatPoint,
    p1: FloatPoint,
    p2: FloatPoint,
) -> FloatPoint:
    dx = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
    dy = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
    return (dx, dy)


def calc_control_point(
    start: Point,
    end: Point,
    offset: float,
) -> FloatPoint:
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
