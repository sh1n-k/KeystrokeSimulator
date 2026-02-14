import threading
import unittest

from keystroke_processor import KeystrokeProcessor


def _make_processor_stub(event_data_list=None) -> KeystrokeProcessor:
    proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
    proc.state_lock = threading.Lock()
    proc.current_states = {}
    proc.term_event = threading.Event()
    proc.default_press_times = (0.1, 0.1)
    proc.event_data_list = event_data_list or []
    return proc


def _evt(name, conds=None, **kwargs):
    """테스트용 이벤트 dict 생성 헬퍼"""
    d = {
        "name": name,
        "conds": conds or {},
        "group": None,
        "priority": 0,
        "exec": True,
    }
    d.update(kwargs)
    return d


class TestResolveEffectiveStatesBasic(unittest.TestCase):
    """_resolve_effective_states: 기본 동작"""

    def test_all_raw_match_true_no_conditions(self):
        """조건 없는 이벤트들이 모두 raw match True → 전부 활성"""
        proc = _make_processor_stub([_evt("A"), _evt("B")])
        result = proc._resolve_effective_states({"A": True, "B": True})
        self.assertEqual(result, {"A": True, "B": True})

    def test_all_raw_match_false(self):
        """모든 이벤트 raw match False → 전부 비활성"""
        proc = _make_processor_stub([_evt("A"), _evt("B")])
        result = proc._resolve_effective_states({"A": False, "B": False})
        self.assertEqual(result, {"A": False, "B": False})

    def test_raw_false_shortcircuits_regardless_of_conditions(self):
        """raw match False → 조건과 무관하게 비활성 (short-circuit)"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": True}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": False})
        self.assertTrue(result["A"])
        self.assertFalse(result["B"])

    def test_missing_event_falls_back_to_current_states(self):
        """조건에 참조된 이벤트가 event_data_list에 없으면 current_states에서 조회"""
        proc = _make_processor_stub([
            _evt("B", conds={"External": True}),
        ])
        proc.current_states = {"External": True}
        result = proc._resolve_effective_states({"B": True})
        self.assertTrue(result["B"])

    def test_missing_event_defaults_to_false(self):
        """참조된 이벤트가 current_states에도 없으면 False로 기본 처리"""
        proc = _make_processor_stub([
            _evt("B", conds={"NonExistent": True}),
        ])
        result = proc._resolve_effective_states({"B": True})
        self.assertFalse(result["B"])


class TestResolveEffectiveStatesChain(unittest.TestCase):
    """_resolve_effective_states: 조건 체인"""

    def test_two_level_chain_active(self):
        """A → B: A 활성이면 B도 활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": True}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": True})
        self.assertTrue(result["A"])
        self.assertTrue(result["B"])

    def test_two_level_chain_blocked(self):
        """A → B: A 비활성이면 B도 비활성 (엄격 체인)"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": True}),
        ])
        result = proc._resolve_effective_states({"A": False, "B": True})
        self.assertFalse(result["A"])
        self.assertFalse(result["B"])

    def test_three_level_chain_all_active(self):
        """A → B → C: 3단계 체인 전부 활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": True}),
            _evt("C", conds={"B": True}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": True, "C": True})
        self.assertTrue(result["A"])
        self.assertTrue(result["B"])
        self.assertTrue(result["C"])

    def test_three_level_chain_broken_at_root(self):
        """A → B → C: 루트 A가 비활성이면 B, C 모두 비활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": True}),
            _evt("C", conds={"B": True}),
        ])
        result = proc._resolve_effective_states({"A": False, "B": True, "C": True})
        self.assertFalse(result["A"])
        self.assertFalse(result["B"])
        self.assertFalse(result["C"])

    def test_three_level_chain_broken_at_middle(self):
        """A → B → C: 중간 B가 raw False면 C도 비활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": True}),
            _evt("C", conds={"B": True}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": False, "C": True})
        self.assertTrue(result["A"])
        self.assertFalse(result["B"])
        self.assertFalse(result["C"])

    def test_expect_false_condition(self):
        """B(conds={A: False}): A가 비활성일 때 B 활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": False}),
        ])
        result = proc._resolve_effective_states({"A": False, "B": True})
        self.assertFalse(result["A"])
        self.assertTrue(result["B"])

    def test_expect_false_condition_not_met(self):
        """B(conds={A: False}): A가 활성이면 B 비활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": False}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": True})
        self.assertTrue(result["A"])
        self.assertFalse(result["B"])

    def test_multiple_conditions_all_must_match(self):
        """다중 조건: 모두 충족해야 활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B"),
            _evt("C", conds={"A": True, "B": True}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": True, "C": True})
        self.assertTrue(result["C"])

    def test_multiple_conditions_partial_fail(self):
        """다중 조건: 하나라도 불충족이면 비활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B"),
            _evt("C", conds={"A": True, "B": True}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": False, "C": True})
        self.assertFalse(result["C"])


class TestResolveEffectiveStatesCycle(unittest.TestCase):
    """_resolve_effective_states: 순환 참조 방어"""

    def test_direct_cycle_returns_false(self):
        """A ↔ B 직접 순환 → 방어적으로 False"""
        proc = _make_processor_stub([
            _evt("A", conds={"B": True}),
            _evt("B", conds={"A": True}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": True})
        # 순환 참조 시 visiting 집합에서 감지되어 False
        self.assertFalse(result["A"])
        self.assertFalse(result["B"])

    def test_three_node_cycle(self):
        """A → B → C → A 3노드 순환"""
        proc = _make_processor_stub([
            _evt("A", conds={"C": True}),
            _evt("B", conds={"A": True}),
            _evt("C", conds={"B": True}),
        ])
        result = proc._resolve_effective_states({"A": True, "B": True, "C": True})
        # 모두 순환에 걸려 False
        self.assertFalse(result["A"])
        self.assertFalse(result["B"])
        self.assertFalse(result["C"])

    def test_self_reference(self):
        """A → A 자기 참조"""
        proc = _make_processor_stub([
            _evt("A", conds={"A": True}),
        ])
        result = proc._resolve_effective_states({"A": True})
        self.assertFalse(result["A"])


class TestResolveEffectiveStatesDiamond(unittest.TestCase):
    """_resolve_effective_states: 다이아몬드 의존성"""

    def test_diamond_all_active(self):
        """
        다이아몬드 패턴:
          A
         / \\
        B   C
         \\ /
          D
        D는 B와 C 모두 활성 필요
        """
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": True}),
            _evt("C", conds={"A": True}),
            _evt("D", conds={"B": True, "C": True}),
        ])
        result = proc._resolve_effective_states(
            {"A": True, "B": True, "C": True, "D": True}
        )
        self.assertTrue(result["D"])

    def test_diamond_one_branch_blocked(self):
        """다이아몬드: C가 비활성이면 D도 비활성"""
        proc = _make_processor_stub([
            _evt("A"),
            _evt("B", conds={"A": True}),
            _evt("C", conds={"A": True}),
            _evt("D", conds={"B": True, "C": True}),
        ])
        result = proc._resolve_effective_states(
            {"A": True, "B": True, "C": False, "D": True}
        )
        self.assertTrue(result["B"])
        self.assertFalse(result["C"])
        self.assertFalse(result["D"])


class TestResolveEffectiveStatesResolutionOrder(unittest.TestCase):
    """_resolve_effective_states: 해석 순서 무관성"""

    def test_reverse_order_events(self):
        """event_data_list 순서가 역순이어도 동일 결과"""
        proc = _make_processor_stub([
            _evt("C", conds={"B": True}),
            _evt("B", conds={"A": True}),
            _evt("A"),
        ])
        result = proc._resolve_effective_states({"A": True, "B": True, "C": True})
        self.assertTrue(result["A"])
        self.assertTrue(result["B"])
        self.assertTrue(result["C"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
