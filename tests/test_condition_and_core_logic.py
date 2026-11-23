import unittest
from unittest.mock import MagicMock, patch

from tests.helpers import evaluate_processor_events, make_processor_stub
from app.engine.processor import _normalize_key_name


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
            lambda _img, evt: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await evaluate_processor_events(proc)

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
            lambda _img, evt: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await evaluate_processor_events(proc)

        self.assertEqual(pressed, ["ACTION"])
        self.assertEqual(proc.current_states, {"COND": True, "ACTION": True})

    async def test_screenless_input_runs_when_and_conditions_match(self):
        proc = make_processor_stub()
        proc.event_data_list = [
            {"name": "A", "conds": {}, "group": None, "priority": 0, "exec": False},
            {"name": "C", "conds": {}, "group": None, "priority": 0, "exec": False},
            {
                "name": "B",
                "conds": {"A": True, "C": False},
                "group": None,
                "priority": 0,
                "exec": True,
                "screenless": True,
            },
        ]
        match_map = {"A": True, "C": False}
        pressed = []

        proc._check_match = lambda _img, evt: match_map.get(evt["name"], False)

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await evaluate_processor_events(proc)

        self.assertEqual(pressed, ["B"])
        self.assertEqual(
            proc.current_states, {"A": True, "C": False, "B": True}
        )

    async def test_screenless_input_stays_inactive_when_condition_fails(self):
        proc = make_processor_stub()
        proc.event_data_list = [
            {"name": "A", "conds": {}, "group": None, "priority": 0, "exec": False},
            {
                "name": "B",
                "conds": {"A": True},
                "group": None,
                "priority": 0,
                "exec": True,
                "screenless": True,
            },
        ]
        match_map = {"A": False}
        pressed = []

        proc._check_match = lambda _img, evt: match_map.get(evt["name"], False)

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await evaluate_processor_events(proc)

        self.assertEqual(pressed, [])
        self.assertEqual(proc.current_states, {"A": False, "B": False})

    async def test_derived_state_feeds_actions_without_pressing(self):
        from app.domain.models import EventModel

        proc = make_processor_stub()
        proc.key_codes = {"A": 0, "B": 1}
        screen = dict(
            latest_position=(10, 10), clicked_position=(1, 1), ref_pixel_value=(1, 2, 3)
        )
        proc.event_data_list = proc._init_event_data([
            EventModel(event_name="IN_COMBAT", execute_action=False, **screen),
            EventModel(event_name="CASTING", execute_action=False, **screen),
            # 동작이었다가 상태로 바뀌어 키·그룹이 남은 파생 상태도 키를 누르거나
            # 그룹 경쟁에 끼면 안 된다(priority 0이라 끼면 ACT를 이긴다).
            EventModel(
                event_name="COMMON",
                execute_action=False,
                key_to_enter="B",
                group_id="g",
                priority=0,
                conditions={"IN_COMBAT": True, "CASTING": False},
            ),
            EventModel(
                event_name="CHAINED",
                execute_action=False,
                conditions={"COMMON": True},
            ),
            EventModel(
                event_name="ACT",
                key_to_enter="A",
                group_id="g",
                priority=1,
                conditions={"CHAINED": True},
            ),
        ])
        pressed = []

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        for casting, expected in ((False, ["ACT"]), (True, [])):
            pressed.clear()
            match_map = {"IN_COMBAT": True, "CASTING": casting}
            proc._check_match = lambda _img, evt, m=match_map: m.get(evt["name"], False)

            await evaluate_processor_events(proc)

            self.assertEqual(pressed, expected)
            self.assertEqual(proc.current_states["COMMON"], not casting)
            self.assertEqual(proc.current_states["CHAINED"], not casting)

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
            lambda _img, evt: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await evaluate_processor_events(proc)

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
            },
        ]
        match_map = {"A1": True, "A2": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await evaluate_processor_events(proc)

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
            },
        ]
        match_map = {"Gate": True, "A1": True, "A2": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await evaluate_processor_events(proc)

        self.assertEqual(pressed, ["A1", "A2"])

    async def test_runtime_toggle_group_blocks_then_allows_member_execution(self):
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "Base",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": True,
                "key": "A",
                "runtime_toggle_member": False,
            },
            {
                "name": "Extra",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": True,
                "key": "B",
                "runtime_toggle_member": True,
            },
        ]
        match_map = {"Base": True, "Extra": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt: match_map[evt["name"]]
        )

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await evaluate_processor_events(proc)

        self.assertEqual(pressed, ["Base"])
        self.assertEqual(proc.current_states, {"Base": True, "Extra": False})

        proc.set_runtime_toggle_active(True)
        await evaluate_processor_events(proc)

        self.assertEqual(pressed[-2:], ["Base", "Extra"])
        self.assertEqual(proc.current_states, {"Base": True, "Extra": True})


class TestWaitAction(unittest.IsolatedAsyncioTestCase):
    """대기 동작: 상위 동작이 자원을 기다리는 동안 그룹의 하위 동작을 막는다."""

    def _proc(self, ready: bool, low: bool):
        proc = make_processor_stub()
        proc.event_data_list = [
            {"name": "READY", "conds": {}, "group": None, "priority": 0, "exec": False},
            {"name": "LOW", "conds": {}, "group": None, "priority": 0, "exec": False},
            {
                "name": "WAIT", "conds": {"READY": True, "LOW": True}, "group": "G",
                "priority": 0, "exec": True, "screenless": True, "key": None,
                "wait": True,
            },
            {
                "name": "SKILL", "conds": {"READY": True, "LOW": False}, "group": "G",
                "priority": 1, "exec": True, "screenless": True, "key": "A",
            },
            {
                "name": "FILLER", "conds": {}, "group": "G", "priority": 2,
                "exec": True, "key": "B",
            },
        ]
        match_map = {"READY": ready, "LOW": low, "FILLER": True}
        proc._check_match = lambda _img, evt: match_map.get(evt["name"], True)
        return proc

    async def _selected(self, ready: bool, low: bool) -> list[str]:
        proc = self._proc(ready, low)
        pressed: list[str] = []

        async def fake_press(evt, _local_states):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press
        await evaluate_processor_events(proc)
        return pressed

    async def test_wait_blocks_lower_actions_while_resource_is_low(self):
        self.assertEqual(await self._selected(ready=True, low=True), ["WAIT"])

    async def test_top_action_runs_once_resource_is_back(self):
        self.assertEqual(await self._selected(ready=True, low=False), ["SKILL"])

    async def test_lower_actions_run_while_top_action_is_not_ready(self):
        self.assertEqual(await self._selected(ready=False, low=True), ["FILLER"])

    async def test_wait_press_sends_no_key(self):
        proc = self._proc(ready=True, low=True)
        proc.sim = MagicMock()
        proc.key_codes = {"A": 0, "B": 1}
        await proc._press_key_async(proc.event_data_list[2])
        proc.sim.press.assert_not_called()


class TestSafetyAndNormalization(unittest.TestCase):
    def test_calculate_press_duration_has_minimum_floor(self):
        proc = make_processor_stub()
        duration = proc._calculate_press_duration({"dur": 10, "rand": None})
        self.assertEqual(duration, 0.05)

    def test_calculate_press_duration_with_randomization(self):
        proc = make_processor_stub()
        evt = {"dur": None, "rand": 100}

        with patch("app.engine.processor.random.uniform", side_effect=[0.1, -80]):
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
