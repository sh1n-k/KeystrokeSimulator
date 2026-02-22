import unittest
from unittest.mock import patch

import keystroke_event_graph as graph_module

from keystroke_event_graph import (
    PALETTE,
    GraphEdge,
    GraphNode,
    _assign_levels,
    _build_components,
    _build_graph,
    _build_layers,
    _build_order_map,
    _bezier_point,
    _bezier_tangent,
    _calc_control_point,
    _calc_max_cols,
    _compute_edge_offsets,
    _count_group_breaks,
    _fade_color,
    _group_color,
    _optimize_layer_order,
    _pack_components,
    _profile_hash,
    _wrap_label,
    _wrap_layers,
    ComponentLayout,
)
from keystroke_models import EventModel, ProfileModel


def _make_node(node_id, name=None, group_id=None, **kwargs):
    """테스트용 GraphNode 생성 헬퍼"""
    return GraphNode(
        node_id=node_id,
        name=name or node_id,
        label=name or node_id,
        group_id=group_id,
        use_event=kwargs.get("use_event", True),
        execute_action=kwargs.get("execute_action", True),
        independent_thread=kwargs.get("independent_thread", False),
        missing=kwargs.get("missing", False),
    )


class TestBuildGraph(unittest.TestCase):
    """_build_graph: ProfileModel → 그래프 구조 변환"""

    def test_empty_profile(self):
        """빈 프로필 → 빈 그래프"""
        profile = ProfileModel(name="test", event_list=[])
        nodes, edges = _build_graph(profile)
        self.assertEqual(len(nodes), 0)
        self.assertEqual(len(edges), 0)

    def test_single_event_no_conditions(self):
        """단일 이벤트, 조건 없음"""
        profile = ProfileModel(
            name="test",
            event_list=[EventModel(event_name="A")],
        )
        nodes, edges = _build_graph(profile)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].name, "A")
        self.assertEqual(len(edges), 0)

    def test_condition_creates_edge(self):
        """조건 참조가 있으면 엣지 생성"""
        profile = ProfileModel(
            name="test",
            event_list=[
                EventModel(event_name="A"),
                EventModel(event_name="B", conditions={"A": True}),
            ],
        )
        nodes, edges = _build_graph(profile)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].src, "evt_0")  # A
        self.assertEqual(edges[0].dst, "evt_1")  # B
        self.assertTrue(edges[0].state)

    def test_missing_condition_creates_missing_node(self):
        """존재하지 않는 이벤트를 참조하면 missing 노드 생성"""
        profile = ProfileModel(
            name="test",
            event_list=[
                EventModel(event_name="B", conditions={"NonExistent": True}),
            ],
        )
        nodes, edges = _build_graph(profile)
        self.assertEqual(len(nodes), 2)  # B + missing
        missing = [n for n in nodes if n.missing]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].name, "NonExistent")
        self.assertIn("[MISSING]", missing[0].label)

    def test_multiple_conditions(self):
        """여러 조건이 있으면 여러 엣지 생성"""
        profile = ProfileModel(
            name="test",
            event_list=[
                EventModel(event_name="A"),
                EventModel(event_name="B"),
                EventModel(event_name="C", conditions={"A": True, "B": False}),
            ],
        )
        nodes, edges = _build_graph(profile)
        self.assertEqual(len(edges), 2)
        states = {(e.src, e.dst): e.state for e in edges}
        self.assertTrue(states[("evt_0", "evt_2")])   # A → C: True
        self.assertFalse(states[("evt_1", "evt_2")])  # B → C: False

    def test_event_attributes_mapped(self):
        """이벤트 속성이 노드에 올바르게 매핑"""
        profile = ProfileModel(
            name="test",
            event_list=[
                EventModel(
                    event_name="Special",
                    group_id="G1",
                    use_event=False,
                    execute_action=False,
                    independent_thread=True,
                ),
            ],
        )
        nodes, _ = _build_graph(profile)
        node = nodes[0]
        self.assertEqual(node.group_id, "G1")
        self.assertFalse(node.use_event)
        self.assertFalse(node.execute_action)
        self.assertTrue(node.independent_thread)

    def test_duplicate_event_names(self):
        """동명 이벤트가 있으면 조건 엣지가 모든 동명 노드에 연결"""
        profile = ProfileModel(
            name="test",
            event_list=[
                EventModel(event_name="A"),
                EventModel(event_name="A"),
                EventModel(event_name="B", conditions={"A": True}),
            ],
        )
        nodes, edges = _build_graph(profile)
        self.assertEqual(len(nodes), 3)
        # B는 두 개의 A 노드 모두에서 엣지를 받음
        b_edges = [e for e in edges if e.dst == "evt_2"]
        self.assertEqual(len(b_edges), 2)


class TestAssignLevels(unittest.TestCase):
    """_assign_levels: 위상 정렬 기반 레벨 할당"""

    def test_no_edges(self):
        """엣지 없으면 모든 노드 레벨 0"""
        levels = _assign_levels(["A", "B", "C"], [])
        self.assertEqual(levels, {"A": 0, "B": 0, "C": 0})

    def test_linear_chain(self):
        """A → B → C: 레벨 0, 1, 2"""
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="B", dst="C", state=True),
        ]
        levels = _assign_levels(["A", "B", "C"], edges)
        self.assertEqual(levels["A"], 0)
        self.assertEqual(levels["B"], 1)
        self.assertEqual(levels["C"], 2)

    def test_diamond_pattern(self):
        """다이아몬드: A → B, A → C, B → D, C → D"""
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="A", dst="C", state=True),
            GraphEdge(src="B", dst="D", state=True),
            GraphEdge(src="C", dst="D", state=True),
        ]
        levels = _assign_levels(["A", "B", "C", "D"], edges)
        self.assertEqual(levels["A"], 0)
        self.assertEqual(levels["B"], 1)
        self.assertEqual(levels["C"], 1)
        self.assertEqual(levels["D"], 2)

    def test_cycle_assigned_to_max_plus_one(self):
        """순환 노드는 max_level + 1에 배치"""
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="B", dst="A", state=True),
        ]
        levels = _assign_levels(["A", "B"], edges)
        # 둘 다 incoming > 0이므로 max_level + 1
        self.assertEqual(levels["A"], levels["B"])
        self.assertGreater(levels["A"], 0)

    def test_partial_cycle(self):
        """일부 노드만 순환: C → D → C, A → B는 정상"""
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="C", dst="D", state=True),
            GraphEdge(src="D", dst="C", state=True),
        ]
        levels = _assign_levels(["A", "B", "C", "D"], edges)
        self.assertEqual(levels["A"], 0)
        self.assertEqual(levels["B"], 1)
        # C, D는 순환이므로 max_level + 1 = 2
        self.assertEqual(levels["C"], 2)
        self.assertEqual(levels["D"], 2)

    def test_single_node(self):
        """단일 노드"""
        levels = _assign_levels(["A"], [])
        self.assertEqual(levels, {"A": 0})

    def test_disconnected_components(self):
        """분리된 컴포넌트: 각각 독립적 레벨"""
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="C", dst="D", state=True),
        ]
        levels = _assign_levels(["A", "B", "C", "D"], edges)
        self.assertEqual(levels["A"], 0)
        self.assertEqual(levels["B"], 1)
        self.assertEqual(levels["C"], 0)
        self.assertEqual(levels["D"], 1)


class TestBuildComponents(unittest.TestCase):
    """_build_components: 연결 컴포넌트 탐지"""

    def test_no_edges_each_node_is_component(self):
        """엣지 없으면 각 노드가 독립 컴포넌트"""
        components = _build_components(["A", "B", "C"], [])
        self.assertEqual(len(components), 3)

    def test_connected_single_component(self):
        """모든 노드가 연결되면 단일 컴포넌트"""
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="B", dst="C", state=True),
        ]
        components = _build_components(["A", "B", "C"], edges)
        self.assertEqual(len(components), 1)
        self.assertEqual(sorted(components[0]), ["A", "B", "C"])

    def test_two_components(self):
        """두 개의 분리된 컴포넌트"""
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="C", dst="D", state=True),
        ]
        components = _build_components(["A", "B", "C", "D"], edges)
        self.assertEqual(len(components), 2)
        comp_sets = [set(c) for c in components]
        self.assertIn({"A", "B"}, comp_sets)
        self.assertIn({"C", "D"}, comp_sets)

    def test_directed_edge_treated_as_undirected(self):
        """방향 엣지도 무방향으로 처리 (양방향 연결)"""
        edges = [GraphEdge(src="A", dst="B", state=True)]
        components = _build_components(["A", "B"], edges)
        self.assertEqual(len(components), 1)

    def test_single_node(self):
        """단일 노드 = 단일 컴포넌트"""
        components = _build_components(["A"], [])
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0], ["A"])


class TestBuildLayers(unittest.TestCase):
    """_build_layers: 위상 정렬 기반 레이어 생성"""

    def test_linear_chain(self):
        """A → B → C: 3개 레이어"""
        nodes = [_make_node("A"), _make_node("B"), _make_node("C")]
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="B", dst="C", state=True),
        ]
        layers = _build_layers(nodes, edges)
        self.assertEqual(len(layers), 3)
        self.assertIn("A", layers[0])
        self.assertIn("B", layers[1])
        self.assertIn("C", layers[2])

    def test_no_edges_single_layer(self):
        """엣지 없으면 모두 같은 레이어"""
        nodes = [_make_node("A"), _make_node("B"), _make_node("C")]
        layers = _build_layers(nodes, [])
        self.assertEqual(len(layers), 1)
        self.assertEqual(sorted(layers[0]), ["A", "B", "C"])

    def test_cycle_nodes_in_final_layer(self):
        """순환 노드는 마지막 레이어에 배치"""
        nodes = [_make_node("A"), _make_node("B")]
        edges = [
            GraphEdge(src="A", dst="B", state=True),
            GraphEdge(src="B", dst="A", state=True),
        ]
        layers = _build_layers(nodes, edges)
        # 순환이므로 incoming이 0인 노드가 없음 → remaining으로 처리
        self.assertGreaterEqual(len(layers), 1)
        all_nodes = [n for layer in layers for n in layer]
        self.assertIn("A", all_nodes)
        self.assertIn("B", all_nodes)


class TestOptimizeLayerOrder(unittest.TestCase):
    """_optimize_layer_order: 중심좌표 최적화"""

    def test_no_change_single_layer(self):
        """레이어 1개면 변경 없음"""
        layers = [["A", "B", "C"]]
        result = _optimize_layer_order(layers, [], {}, iterations=2)
        self.assertEqual(result, [["A", "B", "C"]])

    def test_minimizes_crossings(self):
        """기본 교차 최소화: A→C, B→D 매핑 시 재정렬"""
        # Layer 0: [A, B], Layer 1: [C, D]
        # A→D, B→C → 교차 발생 → 최적화 후 C, D 또는 D, C로 재정렬
        edges = [
            GraphEdge(src="A", dst="D", state=True),
            GraphEdge(src="B", dst="C", state=True),
        ]
        layers = [["A", "B"], ["C", "D"]]
        base_order = {"A": 0, "B": 1, "C": 2, "D": 3}
        result = _optimize_layer_order(layers, edges, base_order, iterations=3)

        # 최적화 후 Layer 1에서 D가 C 앞에 와야 교차 감소
        self.assertEqual(result[0], ["A", "B"])
        self.assertEqual(result[1], ["D", "C"])


class TestWrapLayers(unittest.TestCase):
    """_wrap_layers: 레이어를 최대 열 수로 분할"""

    def test_no_wrapping_needed(self):
        """레이어가 max_cols 이하면 변경 없음"""
        layers = [["A", "B"]]
        result = _wrap_layers(layers, max_cols=5)
        self.assertEqual(result, [["A", "B"]])

    def test_wrapping_splits_layer(self):
        """max_cols 초과 시 분할"""
        layers = [["A", "B", "C", "D", "E"]]
        result = _wrap_layers(layers, max_cols=3)
        self.assertEqual(result, [["A", "B", "C"], ["D", "E"]])

    def test_empty_layers_skipped(self):
        """빈 레이어는 건너뜀"""
        layers = [[], ["A", "B"], []]
        result = _wrap_layers(layers, max_cols=5)
        self.assertEqual(result, [["A", "B"]])

    def test_max_cols_one(self):
        """max_cols=1이면 각 노드가 별도 레이어"""
        layers = [["A", "B", "C"]]
        result = _wrap_layers(layers, max_cols=1)
        self.assertEqual(result, [["A"], ["B"], ["C"]])


class TestCountGroupBreaks(unittest.TestCase):
    """_count_group_breaks: 그룹 간 경계 계산"""

    def test_no_breaks(self):
        """같은 그룹이면 break 없음"""
        node_map = {
            "A": _make_node("A", group_id="G1"),
            "B": _make_node("B", group_id="G1"),
        }
        self.assertEqual(_count_group_breaks(["A", "B"], node_map), 0)

    def test_one_break(self):
        """다른 그룹 → 1 break"""
        node_map = {
            "A": _make_node("A", group_id="G1"),
            "B": _make_node("B", group_id="G2"),
        }
        self.assertEqual(_count_group_breaks(["A", "B"], node_map), 1)

    def test_mixed_groups(self):
        """G1, G1, G2, G1 → 2 breaks"""
        node_map = {
            "A": _make_node("A", group_id="G1"),
            "B": _make_node("B", group_id="G1"),
            "C": _make_node("C", group_id="G2"),
            "D": _make_node("D", group_id="G1"),
        }
        self.assertEqual(_count_group_breaks(["A", "B", "C", "D"], node_map), 2)

    def test_single_node_no_breaks(self):
        """노드 1개면 break 없음"""
        node_map = {"A": _make_node("A", group_id="G1")}
        self.assertEqual(_count_group_breaks(["A"], node_map), 0)


class TestProfileHash(unittest.TestCase):
    """_profile_hash: 프로필 해시 계산"""

    def test_deterministic(self):
        """동일 프로필 → 동일 해시"""
        profile = ProfileModel(
            name="test",
            event_list=[EventModel(event_name="A")],
        )
        h1 = _profile_hash(profile)
        h2 = _profile_hash(profile)
        self.assertEqual(h1, h2)

    def test_different_profiles_different_hash(self):
        """다른 프로필 → 다른 해시"""
        p1 = ProfileModel(name="test", event_list=[EventModel(event_name="A")])
        p2 = ProfileModel(name="test", event_list=[EventModel(event_name="B")])
        self.assertNotEqual(_profile_hash(p1), _profile_hash(p2))

    def test_empty_profile_has_hash(self):
        """빈 프로필도 유효한 해시 반환"""
        profile = ProfileModel(name="empty", event_list=[])
        h = _profile_hash(profile)
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)  # SHA-256


class TestGroupColor(unittest.TestCase):
    """_group_color: 그룹 ID 기반 색상 결정"""

    def test_none_returns_gray(self):
        """None → 회색"""
        self.assertEqual(_group_color(None), (220, 220, 220))

    def test_deterministic(self):
        """동일 group_id → 동일 색상"""
        self.assertEqual(_group_color("G1"), _group_color("G1"))

    def test_group_color_is_in_palette(self):
        """group_id가 있으면 팔레트 내 색상이 반환됨"""
        c1 = _group_color("Group_A")
        c2 = _group_color("Group_B")
        self.assertIn(c1, PALETTE)
        self.assertIn(c2, PALETTE)
        self.assertNotEqual(c1, _group_color(None))


class TestBezierMath(unittest.TestCase):
    """Bezier 곡선 수학 함수"""

    def test_bezier_point_at_start(self):
        """t=0: 시작점 반환"""
        p = _bezier_point(0.0, (0, 0), (50, 100), (100, 0))
        self.assertAlmostEqual(p[0], 0.0)
        self.assertAlmostEqual(p[1], 0.0)

    def test_bezier_point_at_end(self):
        """t=1: 끝점 반환"""
        p = _bezier_point(1.0, (0, 0), (50, 100), (100, 0))
        self.assertAlmostEqual(p[0], 100.0)
        self.assertAlmostEqual(p[1], 0.0)

    def test_bezier_point_at_mid(self):
        """t=0.5: 중간점"""
        p = _bezier_point(0.5, (0, 0), (50, 100), (100, 0))
        self.assertAlmostEqual(p[0], 50.0)
        self.assertAlmostEqual(p[1], 50.0)

    def test_bezier_tangent_direction(self):
        """접선 벡터가 올바른 방향"""
        dx, dy = _bezier_tangent(0.0, (0, 0), (100, 0), (200, 0))
        self.assertGreater(dx, 0)  # 오른쪽 방향
        self.assertAlmostEqual(dy, 0.0)  # y 변화 없음

    def test_calc_control_point_no_offset(self):
        """offset=0: 중점 반환"""
        cp = _calc_control_point((0, 0), (100, 0), 0.0)
        self.assertAlmostEqual(cp[0], 50.0)
        self.assertAlmostEqual(cp[1], 0.0)

    def test_calc_control_point_with_offset(self):
        """offset > 0: 수직 방향으로 이동"""
        cp = _calc_control_point((0, 0), (100, 0), 20.0)
        self.assertAlmostEqual(cp[0], 50.0)
        # 수평선의 수직 = y축 방향
        self.assertNotAlmostEqual(cp[1], 0.0)

    def test_calc_control_point_zero_length(self):
        """시작=끝: 길이 0일 때 offset 적용"""
        cp = _calc_control_point((50, 50), (50, 50), 10.0)
        self.assertAlmostEqual(cp[0], 60.0)  # mx + offset
        self.assertAlmostEqual(cp[1], 50.0)


class TestComputeEdgeOffsets(unittest.TestCase):
    """_compute_edge_offsets: 엣지 겹침 방지 오프셋"""

    def test_single_edge_zero_offset(self):
        """엣지 1개 → 오프셋 0"""
        edges = [GraphEdge(src="A", dst="B", state=True)]
        positions = {"A": (0, 0), "B": (100, 100)}
        offsets = _compute_edge_offsets(edges, positions)
        self.assertAlmostEqual(offsets[("A", "B")], 0.0)

    def test_multiple_edges_to_same_dest(self):
        """같은 dst로 여러 엣지 → 분산 오프셋"""
        edges = [
            GraphEdge(src="A", dst="C", state=True),
            GraphEdge(src="B", dst="C", state=True),
        ]
        positions = {"A": (0, 0), "B": (100, 0), "C": (50, 100)}
        offsets = _compute_edge_offsets(edges, positions)
        o1 = offsets[("A", "C")]
        o2 = offsets[("B", "C")]
        self.assertNotAlmostEqual(o1, o2)  # 서로 다른 오프셋
        self.assertAlmostEqual(o1 + o2, 0.0)  # 대칭

    def test_missing_position_skipped(self):
        """position에 없는 노드의 엣지는 무시"""
        edges = [GraphEdge(src="A", dst="B", state=True)]
        positions = {"A": (0, 0)}  # B 없음
        offsets = _compute_edge_offsets(edges, positions)
        self.assertEqual(len(offsets), 0)


class TestUtilityFunctions(unittest.TestCase):
    """유틸리티 함수"""

    def test_fade_color(self):
        """색상 페이드: alpha=0 → 배경색, alpha=1 → 원색"""
        result = _fade_color((255, 0, 0), (0, 0, 0), 1.0)
        self.assertEqual(result, (255, 0, 0))

        result = _fade_color((255, 0, 0), (0, 0, 0), 0.0)
        self.assertEqual(result, (0, 0, 0))

    def test_fade_color_half(self):
        """alpha=0.5: 중간색"""
        result = _fade_color((200, 100, 0), (0, 0, 0), 0.5)
        self.assertEqual(result, (100, 50, 0))

    def test_wrap_label_short(self):
        """짧은 텍스트: 그대로 반환"""
        lines = _wrap_label("Hello", width=20, max_lines=2)
        self.assertEqual(lines, ["Hello"])

    def test_wrap_label_truncate(self):
        """max_lines 초과 시 마지막 줄에 ... 추가"""
        text = "This is a very long label that should be truncated"
        lines = _wrap_label(text, width=10, max_lines=2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("..."))

    def test_wrap_label_empty(self):
        """빈 텍스트: [''] 반환"""
        lines = _wrap_label("", width=20, max_lines=2)
        self.assertEqual(lines, [""])

    def test_calc_max_cols_lower_clamped_to_3(self):
        """폭이 작아도 최소 3열"""
        with patch.object(graph_module, "TARGET_WIDTH", 320):
            self.assertEqual(_calc_max_cols(), 3)

    def test_calc_max_cols_uses_formula(self):
        """중간 폭에서는 계산식과 일치"""
        with patch.object(graph_module, "TARGET_WIDTH", 1200):
            usable = max(
                320,
                graph_module.TARGET_WIDTH - graph_module.MARGIN * 2,
            )
            expected = max(
                3,
                min(
                    8,
                    int(
                        (usable + graph_module.X_GAP)
                        // (graph_module.NODE_W + graph_module.X_GAP)
                    ),
                ),
            )
            self.assertEqual(_calc_max_cols(), expected)

    def test_calc_max_cols_upper_clamped_to_8(self):
        """폭이 매우 커도 최대 8열"""
        with patch.object(graph_module, "TARGET_WIDTH", 10000):
            self.assertEqual(_calc_max_cols(), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
