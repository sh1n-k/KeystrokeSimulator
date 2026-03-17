import unittest
from unittest.mock import patch

from helpers import make_processor_stub
from keystroke_processor import _normalize_key_name


class TestConditionFiltering(unittest.TestCase):
    def test_select_by_group_priority_and_non_group(self):
        proc = make_processor_stub()
        events = [
            {"name": "G1_LOW", "group": "G1", "priority": 10},
            {"name": "G1_HIGH", "group": "G1", "priority": 0},
            {"name": "NO_GROUP", "group": None, "priority": 3},
        ]

        selected = proc._select_by_group_priority(events)
        selected_names = {evt["name"] for evt in selected}

        self.assertEqual(selected_names, {"G1_HIGH", "NO_GROUP"})

    def test_select_by_group_priority_uses_name_as_tie_breaker(self):
        proc = make_processor_stub()
        events = [
            {"name": "Zeta", "group": "G1", "priority": 0},
            {"name": "Alpha", "group": "G1", "priority": 0},
            {"name": "Solo", "group": None, "priority": 5},
        ]

        selected = proc._select_by_group_priority(events)
        selected_names = {evt["name"] for evt in selected}

        self.assertEqual(selected_names, {"Alpha", "Solo"})

    def test_check_conditions_from_current_states(self):
        proc = make_processor_stub()
        proc.current_states = {"A": True, "B": False}

        self.assertTrue(proc._check_conditions({"conds": {"A": True, "B": False}}))
        self.assertFalse(proc._check_conditions({"conds": {"A": True, "B": True}}))
        self.assertFalse(proc._check_conditions({"conds": {"MISSING": True}}))


class TestEvaluateAndExecute(unittest.IsolatedAsyncioTestCase):
    async def test_evaluate_and_execute_applies_condition_then_group(self):
        proc = make_processor_stub()
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

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, ["C"])
        self.assertEqual(
            proc.current_states,
            {"A": True, "B": True, "C": True, "D": False},
        )

    async def test_group_selection_ignores_condition_only_events_for_key_press(self):
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "COND",
                "conds": {},
                "group": "G1",
                "priority": 0,
                "exec": False,
            },
            {
                "name": "ACTION",
                "conds": {"COND": True},
                "group": "G1",
                "priority": 0,
                "exec": True,
            },
        ]
        match_map = {"COND": True, "ACTION": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, ["ACTION"])
        self.assertEqual(proc.current_states, {"COND": True, "ACTION": True})

    async def test_evaluate_and_execute_strict_chain_blocks_child(self):
        proc = make_processor_stub()
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

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, [])
        self.assertEqual(proc.current_states, {"A": False, "B": False, "C": False})

    async def test_execution_dedupe_keeps_only_one_identical_action(self):
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "A1",
                "mode": "pixel",
                "center_x": 100,
                "center_y": 200,
                "ref_bgr": [1, 2, 3],
                "invert": False,
                "key": "A",
                "dur": 100,
                "rand": 0,
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": True,
                "independent": False,
            },
            {
                "name": "A2",
                "mode": "pixel",
                "center_x": 100,
                "center_y": 200,
                "ref_bgr": [1, 2, 3],
                "invert": False,
                "key": "A",
                "dur": 100,
                "rand": 0,
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": True,
                "independent": False,
            },
        ]
        match_map = {"A1": True, "A2": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, ["A1"])

    async def test_execution_dedupe_does_not_merge_different_conditions(self):
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "Gate",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": False,
            },
            {
                "name": "A1",
                "mode": "pixel",
                "center_x": 100,
                "center_y": 200,
                "ref_bgr": [1, 2, 3],
                "invert": False,
                "key": "A",
                "dur": 100,
                "rand": 0,
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": True,
                "independent": False,
            },
            {
                "name": "A2",
                "mode": "pixel",
                "center_x": 100,
                "center_y": 200,
                "ref_bgr": [1, 2, 3],
                "invert": False,
                "key": "A",
                "dur": 100,
                "rand": 0,
                "conds": {"Gate": True},
                "group": None,
                "priority": 0,
                "exec": True,
                "independent": False,
            },
        ]
        match_map = {"Gate": True, "A1": True, "A2": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, ["A1", "A2"])


class TestSafetyAndNormalization(unittest.TestCase):
    def test_calculate_press_duration_has_minimum_floor(self):
        proc = make_processor_stub()
        duration = proc._calculate_press_duration({"dur": 10, "rand": None})
        self.assertEqual(duration, 0.05)

    def test_calculate_press_duration_with_randomization(self):
        proc = make_processor_stub()
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
