import unittest

import numpy as np

from keystroke_models import EventModel
from keystroke_processor import KeystrokeProcessor


def _make_processor_with_key_codes() -> KeystrokeProcessor:
    proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
    proc.key_codes = {"A": 0, "B": 1, "Space": 32}
    return proc


def _make_basic_event(**overrides) -> EventModel:
    defaults = dict(
        event_name="TestEvent",
        latest_position=(100, 200),
        clicked_position=(10, 20),
        ref_pixel_value=(255, 0, 0),
        key_to_enter="A",
    )
    defaults.update(overrides)
    return EventModel(**defaults)


class TestInitEventDataFieldMapping(unittest.TestCase):
    """_init_event_data: EventModel → 내부 dict 변환 정합성"""

    def test_basic_field_mapping(self):
        """기본 필드가 올바르게 매핑되는지 확인"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([_make_basic_event()])

        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt["name"], "TestEvent")
        self.assertEqual(evt["mode"], "pixel")
        self.assertEqual(evt["key"], "A")
        self.assertEqual(evt["center_x"], 110)  # 100 + 10
        self.assertEqual(evt["center_y"], 220)  # 200 + 20

    def test_invert_match_true_mapping(self):
        """invert_match=True → dict['invert']=True"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(invert_match=True)
        ])
        self.assertTrue(events[0]["invert"])

    def test_invert_match_default_false(self):
        """invert_match 기본값 → dict['invert']=False"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([_make_basic_event()])
        self.assertFalse(events[0]["invert"])

    def test_rgb_to_bgr_conversion(self):
        """ref_pixel_value (R,G,B) → ref_bgr (B,G,R) 변환"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(ref_pixel_value=(100, 150, 200))
        ])
        np.testing.assert_array_equal(
            events[0]["ref_bgr"],
            np.array([200, 150, 100], dtype=np.uint8),
        )

    def test_execute_action_false_mapping(self):
        """execute_action=False → dict['exec']=False"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(execute_action=False)
        ])
        self.assertFalse(events[0]["exec"])

    def test_group_and_priority_mapping(self):
        """group_id/priority 필드 매핑"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(group_id="G1", priority=5)
        ])
        self.assertEqual(events[0]["group"], "G1")
        self.assertEqual(events[0]["priority"], 5)

    def test_conditions_mapping(self):
        """conditions → dict['conds'] 매핑"""
        proc = _make_processor_with_key_codes()
        conds = {"OtherEvent": True}
        events, _, _ = proc._init_event_data([
            _make_basic_event(conditions=conds)
        ])
        self.assertEqual(events[0]["conds"], {"OtherEvent": True})

    def test_duration_and_randomization_mapping(self):
        """press_duration_ms, randomization_ms → dur, rand 매핑"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(press_duration_ms=150.0, randomization_ms=30.0)
        ])
        self.assertEqual(events[0]["dur"], 150.0)
        self.assertEqual(events[0]["rand"], 30.0)

    def test_key_normalization(self):
        """key_to_enter가 key_codes 기준으로 정규화됨"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(key_to_enter="a")  # 소문자 → 대문자 A
        ])
        self.assertEqual(events[0]["key"], "A")

    def test_no_key_maps_to_none(self):
        """key_to_enter가 None이면 dict['key']=None"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(key_to_enter=None)
        ])
        self.assertIsNone(events[0]["key"])


class TestInitEventDataFiltering(unittest.TestCase):
    """_init_event_data: 이벤트 필터링 및 분류"""

    def test_use_event_false_skipped(self):
        """use_event=False인 이벤트는 건너뛴다"""
        proc = _make_processor_with_key_codes()
        events, indep, _ = proc._init_event_data([
            _make_basic_event(use_event=False)
        ])
        self.assertEqual(len(events), 0)
        self.assertEqual(len(indep), 0)

    def test_missing_ref_pixel_skipped(self):
        """pixel 모드에서 ref_pixel_value가 None이면 건너뛴다"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(ref_pixel_value=None)
        ])
        self.assertEqual(len(events), 0)

    def test_short_ref_pixel_skipped(self):
        """ref_pixel_value 길이가 3 미만이면 건너뛴다"""
        proc = _make_processor_with_key_codes()
        events, _, _ = proc._init_event_data([
            _make_basic_event(ref_pixel_value=(255, 0))
        ])
        self.assertEqual(len(events), 0)

    def test_independent_thread_goes_to_independent_list(self):
        """independent_thread=True → independent_data에 분류"""
        proc = _make_processor_with_key_codes()
        events, independent, _ = proc._init_event_data([
            _make_basic_event(independent_thread=True)
        ])
        self.assertEqual(len(events), 0)
        self.assertEqual(len(independent), 1)
        self.assertEqual(independent[0]["name"], "TestEvent")

    def test_duplicate_signature_deduplicated(self):
        """동일 시그니처 이벤트는 중복 제거"""
        proc = _make_processor_with_key_codes()
        e = _make_basic_event()
        events, _, _ = proc._init_event_data([e, e])
        self.assertEqual(len(events), 1)


class TestInitEventDataMegaRect(unittest.TestCase):
    """_init_event_data: mega_rect 및 상대 좌표 계산"""

    def test_mega_rect_computed(self):
        """이벤트 좌표로부터 mega_rect가 계산됨"""
        proc = _make_processor_with_key_codes()
        _, _, mega_rect = proc._init_event_data([_make_basic_event()])

        self.assertIsNotNone(mega_rect)
        self.assertIn("left", mega_rect)
        self.assertIn("top", mega_rect)
        self.assertIn("width", mega_rect)
        self.assertIn("height", mega_rect)

    def test_rel_coords_set_after_mega_rect(self):
        """mega_rect 기준으로 rel_x, rel_y가 계산됨"""
        proc = _make_processor_with_key_codes()
        events, _, mega_rect = proc._init_event_data([_make_basic_event()])
        evt = events[0]

        self.assertEqual(evt["rel_x"], evt["center_x"] - mega_rect["left"])
        self.assertEqual(evt["rel_y"], evt["center_y"] - mega_rect["top"])

    def test_no_events_no_mega_rect(self):
        """유효 이벤트가 없으면 mega_rect=None"""
        proc = _make_processor_with_key_codes()
        _, _, mega_rect = proc._init_event_data([
            _make_basic_event(use_event=False)
        ])
        self.assertIsNone(mega_rect)

    def test_multiple_events_mega_rect_spans_all(self):
        """여러 이벤트의 좌표를 모두 포함하는 mega_rect"""
        proc = _make_processor_with_key_codes()
        e1 = _make_basic_event(
            event_name="E1",
            latest_position=(0, 0),
            clicked_position=(10, 20),
            key_to_enter="A",
        )
        e2 = _make_basic_event(
            event_name="E2",
            latest_position=(50, 100),
            clicked_position=(10, 20),
            key_to_enter="B",
        )
        events, _, mega_rect = proc._init_event_data([e1, e2])

        self.assertEqual(len(events), 2)
        # E1: center (10, 20), E2: center (60, 120)
        self.assertEqual(mega_rect["left"], 10)
        self.assertEqual(mega_rect["top"], 20)
        self.assertEqual(mega_rect["width"], 51)   # 60 - 10 + 1
        self.assertEqual(mega_rect["height"], 101)  # 120 - 20 + 1


if __name__ == "__main__":
    unittest.main(verbosity=2)
