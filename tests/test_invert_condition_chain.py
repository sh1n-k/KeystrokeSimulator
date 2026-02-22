import unittest

from helpers import make_processor_stub


class TestInvertWithConditionChain(unittest.IsolatedAsyncioTestCase):
    """invert_match가 조건 체인과 결합되는 시나리오"""

    async def test_inverted_parent_true_enables_child(self):
        """
        Parent(invert): 픽셀 불일치 → invert 적용 후 True
        Child(conds={Parent: True}): 조건 충족 → 실행
        """
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "Parent",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": False,
                "invert": True,
            },
            {
                "name": "Child",
                "conds": {"Parent": True},
                "group": None,
                "priority": 0,
                "exec": True,
                "invert": False,
            },
        ]

        # _check_match는 invert 적용 후의 결과를 반환
        match_map = {"Parent": True, "Child": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertIn("Child", pressed)
        self.assertTrue(proc.current_states["Parent"])
        self.assertTrue(proc.current_states["Child"])

    async def test_inverted_parent_false_blocks_child(self):
        """
        Parent(invert): 픽셀 일치 → invert 적용 후 False
        Child(conds={Parent: True}): 조건 불충족 → 차단
        """
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "Parent",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": False,
                "invert": True,
            },
            {
                "name": "Child",
                "conds": {"Parent": True},
                "group": None,
                "priority": 0,
                "exec": True,
                "invert": False,
            },
        ]

        match_map = {"Parent": False, "Child": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, [])
        self.assertFalse(proc.current_states["Parent"])
        self.assertFalse(proc.current_states["Child"])

    async def test_both_inverted_chain(self):
        """
        Parent(invert): True
        Child(invert, conds={Parent: True}): 조건 충족 + 매치 True → 실행
        """
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "Parent",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": False,
                "invert": True,
            },
            {
                "name": "Child",
                "conds": {"Parent": True},
                "group": None,
                "priority": 0,
                "exec": True,
                "invert": True,
            },
        ]

        match_map = {"Parent": True, "Child": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertIn("Child", pressed)
        self.assertTrue(proc.current_states["Parent"])
        self.assertTrue(proc.current_states["Child"])

    async def test_inverted_parent_with_expect_false_child(self):
        """
        Parent(invert): False (invert 적용 후)
        Child(conds={Parent: False}): Parent가 False이므로 조건 충족 → 실행
        """
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "Parent",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": False,
                "invert": True,
            },
            {
                "name": "Child",
                "conds": {"Parent": False},
                "group": None,
                "priority": 0,
                "exec": True,
                "invert": False,
            },
        ]

        # Parent: invert 후 False, Child: raw match True
        match_map = {"Parent": False, "Child": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertIn("Child", pressed)
        self.assertFalse(proc.current_states["Parent"])
        self.assertTrue(proc.current_states["Child"])

    async def test_inverted_event_with_group_priority(self):
        """
        같은 그룹 내 invert 이벤트들의 우선순위 선택
        G1_LOW(priority=10): True
        G1_HIGH(priority=0): True
        → priority 0인 G1_HIGH만 실행
        """
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "G1_LOW",
                "conds": {},
                "group": "G1",
                "priority": 10,
                "exec": True,
                "invert": True,
            },
            {
                "name": "G1_HIGH",
                "conds": {},
                "group": "G1",
                "priority": 0,
                "exec": True,
                "invert": True,
            },
        ]

        match_map = {"G1_LOW": True, "G1_HIGH": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, ["G1_HIGH"])

    async def test_three_level_chain_with_mixed_invert(self):
        """
        A(invert): True
        B(conds={A: True}): True
        C(invert, conds={B: True}): True
        → 3단계 체인에서 invert가 혼합되어도 정상 실행
        """
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "A",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": False,
                "invert": True,
            },
            {
                "name": "B",
                "conds": {"A": True},
                "group": None,
                "priority": 0,
                "exec": False,
                "invert": False,
            },
            {
                "name": "C",
                "conds": {"B": True},
                "group": None,
                "priority": 0,
                "exec": True,
                "invert": True,
            },
        ]

        match_map = {"A": True, "B": True, "C": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertIn("C", pressed)
        self.assertTrue(proc.current_states["A"])
        self.assertTrue(proc.current_states["B"])
        self.assertTrue(proc.current_states["C"])

    async def test_three_level_chain_broken_at_middle(self):
        """
        A(invert): True
        B(invert, conds={A: True}): False (invert 후)
        C(conds={B: True}): raw True지만 B가 False라 차단
        """
        proc = make_processor_stub()
        proc.event_data_list = [
            {
                "name": "A",
                "conds": {},
                "group": None,
                "priority": 0,
                "exec": False,
                "invert": True,
            },
            {
                "name": "B",
                "conds": {"A": True},
                "group": None,
                "priority": 0,
                "exec": False,
                "invert": True,
            },
            {
                "name": "C",
                "conds": {"B": True},
                "group": None,
                "priority": 0,
                "exec": True,
                "invert": False,
            },
        ]

        # A: True, B: False (invert 적용 후), C: True (raw)
        match_map = {"A": True, "B": False, "C": True}
        pressed = []

        proc._check_match = (
            lambda _img, evt, is_independent=False: match_map[evt["name"]]
        )

        async def fake_press(evt):
            pressed.append(evt["name"])

        proc._press_key_async = fake_press

        await proc._evaluate_and_execute_main(img=None)

        self.assertEqual(pressed, [])
        self.assertTrue(proc.current_states["A"])
        self.assertFalse(proc.current_states["B"])
        self.assertFalse(proc.current_states["C"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
