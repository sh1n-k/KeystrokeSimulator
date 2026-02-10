import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from keystroke_event_editor import KeystrokeEventEditor
from keystroke_models import EventModel
from keystroke_processor import KeystrokeProcessor, _normalize_key_name


def _make_processor_stub() -> KeystrokeProcessor:
    proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
    proc.state_lock = threading.Lock()
    proc.current_states = {}
    proc.term_event = threading.Event()
    proc.default_press_times = (0.1, 0.1)
    return proc


class TestConditionFiltering(unittest.TestCase):
    def test_filter_by_conditions_multi_and(self):
        proc = _make_processor_stub()
        candidates = [{"name": "Skill", "conds": {"A": True, "B": False}}]

        passed = proc._filter_by_conditions(candidates, {"A": True, "B": False})
        failed = proc._filter_by_conditions(candidates, {"A": True, "B": True})

        self.assertEqual([evt["name"] for evt in passed], ["Skill"])
        self.assertEqual(failed, [])

    def test_filter_by_conditions_fallbacks_to_current_state(self):
        proc = _make_processor_stub()
        proc.current_states = {"A": True}
        candidates = [{"name": "Skill", "conds": {"A": True}}]

        passed = proc._filter_by_conditions(candidates, local_states={})
        self.assertEqual([evt["name"] for evt in passed], ["Skill"])

    def test_select_by_group_priority_and_non_group(self):
        proc = _make_processor_stub()
        events = [
            {"name": "G1_LOW", "group": "G1", "priority": 10},
            {"name": "G1_HIGH", "group": "G1", "priority": 0},
            {"name": "NO_GROUP", "group": None, "priority": 3},
        ]

        selected = proc._select_by_group_priority(events)
        selected_names = {evt["name"] for evt in selected}

        self.assertEqual(selected_names, {"G1_HIGH", "NO_GROUP"})

    def test_check_conditions_from_current_states(self):
        proc = _make_processor_stub()
        proc.current_states = {"A": True, "B": False}

        self.assertTrue(proc._check_conditions({"conds": {"A": True, "B": False}}))
        self.assertFalse(proc._check_conditions({"conds": {"A": True, "B": True}}))
        self.assertFalse(proc._check_conditions({"conds": {"MISSING": True}}))


class TestEvaluateAndExecute(unittest.IsolatedAsyncioTestCase):
    async def test_evaluate_and_execute_applies_condition_then_group(self):
        proc = _make_processor_stub()
        proc.event_data_list = [
            {"name": "A", "conds": {}, "group": None, "priority": 0, "exec": False},
            {
                "name": "B",
                "conds": {"A": True},
                "group": "G1",
                "priority": 1,
                "exec": True,
            },
            {
                "name": "C",
                "conds": {"A": True},
                "group": "G1",
                "priority": 0,
                "exec": True,
            },
            {
                "name": "D",
                "conds": {"A": False},
                "group": None,
                "priority": 0,
                "exec": True,
            },
        ]
        match_map = {"A": True, "B": True, "C": True, "D": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, ["C"])
        self.assertEqual(
            proc.current_states,
            {"A": True, "B": True, "C": True, "D": False},
        )

    async def test_evaluate_and_execute_strict_chain_blocks_child(self):
        proc = _make_processor_stub()
        proc.event_data_list = [
            {"name": "A", "conds": {}, "group": None, "priority": 0, "exec": False},
            {
                "name": "B",
                "conds": {"A": True},
                "group": None,
                "priority": 0,
                "exec": False,
            },
            {
                "name": "C",
                "conds": {"B": True},
                "group": None,
                "priority": 0,
                "exec": True,
            },
        ]

        # raw match만 보면 B/C가 True지만, 엄격 체인에서는 A가 False라 B/C 모두 비활성
        match_map = {"A": False, "B": True, "C": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, [])
        self.assertEqual(proc.current_states, {"A": False, "B": False, "C": False})


class TestSafetyAndNormalization(unittest.TestCase):
    def test_calculate_press_duration_has_minimum_floor(self):
        proc = _make_processor_stub()
        duration = proc._calculate_press_duration({"dur": 10, "rand": None})
        self.assertEqual(duration, 0.05)

    def test_calculate_press_duration_with_randomization(self):
        proc = _make_processor_stub()
        evt = {"dur": None, "rand": 100}

        with patch("keystroke_processor.random.uniform", side_effect=[0.1, -80]):
            duration = proc._calculate_press_duration(evt)

        self.assertEqual(duration, 0.05)

    def test_normalize_key_name_case_and_spaces(self):
        key_codes = {"A": 1, "Space": 2}
        self.assertEqual(_normalize_key_name(key_codes, "a"), "A")
        self.assertEqual(_normalize_key_name(key_codes, " space "), "Space")
        self.assertIsNone(_normalize_key_name(key_codes, ""))
        self.assertIsNone(_normalize_key_name(key_codes, None))


class TestEditorCycleValidation(unittest.TestCase):
    def test_validate_cycles_detects_cycle(self):
        stub = SimpleNamespace(
            existing_events=[
                EventModel(event_name="A", conditions={"B": True}),
                EventModel(event_name="B", conditions={}),
            ]
        )
        has_cycle = KeystrokeEventEditor._validate_cycles(stub, "B", {"A": True})
        self.assertTrue(has_cycle)

    def test_validate_cycles_accepts_acyclic_graph(self):
        stub = SimpleNamespace(
            existing_events=[
                EventModel(event_name="A", conditions={"B": True}),
                EventModel(event_name="B", conditions={}),
            ]
        )
        has_cycle = KeystrokeEventEditor._validate_cycles(stub, "C", {"A": True})
        self.assertFalse(has_cycle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
