"""이벤트 편집 검증 — 모달 편집기(event_editor.py) 제거 후 상세 패널 기준."""

import unittest

from PIL import Image

from app.domain.capture_geometry import CaptureResult
from app.domain.event_editing import (
    apply_capture,
    capture_from_event,
    clamp_region,
    clear_capture,
    event_issues,
)
from app.domain.models import EventModel
from app.utils.i18n import set_language


def screen_event(**kwargs):
    return EventModel(
        latest_position=(100, 200),
        clicked_position=(50, 50),
        held_screenshot=Image.new("RGB", (100, 100), (1, 2, 3)),
        ref_pixel_value=(1, 2, 3),
        capture_size=(100, 100),
        **kwargs,
    )


class TestEventIssues(unittest.TestCase):
    """기존 편집기의 저장 전 필수 조건과 같은 판정."""

    def setUp(self):
        set_language("en")

    def test_rule_needs_key(self):
        issues = event_issues(screen_event(event_name="r", key_to_enter=None))

        self.assertTrue(any("key" in i for i in issues))

    def test_rule_without_screen_needs_a_condition(self):
        self.assertTrue(event_issues(EventModel(event_name="r", key_to_enter="A")))
        self.assertEqual(
            event_issues(
                EventModel(event_name="r", key_to_enter="A", conditions={"s": True})
            ),
            [],
        )

    def test_signal_needs_screen_but_no_key(self):
        self.assertTrue(event_issues(EventModel(event_name="s", execute_action=False)))
        self.assertEqual(
            event_issues(screen_event(event_name="s", execute_action=False)), []
        )

    def test_region_mode_needs_capture(self):
        event = EventModel(
            event_name="r",
            key_to_enter="A",
            conditions={"s": True},
            match_mode="region",
        )

        self.assertTrue(any("Region" in i for i in event_issues(event)))


class TestCaptureRoundTrip(unittest.TestCase):
    def test_apply_and_read_back_capture(self):
        event = EventModel(event_name="e")
        result = CaptureResult(
            position=(5, 6),
            capture_size=(120, 80),
            image=Image.new("RGB", (120, 80)),
            pixel=(7, 8),
            color=(9, 8, 7),
        )

        apply_capture(event, result)
        back = capture_from_event(event)

        self.assertEqual(
            (back.position, back.capture_size, back.pixel, back.color),
            ((5, 6), (120, 80), (7, 8), (9, 8, 7)),
        )
        self.assertEqual(event.latest_position, (5, 6))
        self.assertEqual(event.clicked_position, (7, 8))

    def test_capture_from_event_without_screen_is_none(self):
        self.assertIsNone(capture_from_event(EventModel(event_name="e")))

    def test_clear_capture_resets_screen_fields(self):
        event = screen_event(
            match_mode="region", region_size=(40, 40), invert_match=True
        )

        clear_capture(event)

        self.assertIsNone(event.latest_position)
        self.assertIsNone(event.held_screenshot)
        self.assertEqual(event.match_mode, "pixel")
        self.assertFalse(event.invert_match)
        self.assertIsNone(event.region_size)


class TestRegionClamp(unittest.TestCase):
    def test_region_is_clamped_to_capture_bounds(self):
        event = screen_event(match_mode="region", region_size=(80, 70))
        event.clicked_position = (30, 30)

        clamp_region(event)

        self.assertEqual(event.region_size, (61, 61))

    def test_region_minimum_is_20(self):
        event = screen_event(match_mode="region", region_size=(10, 15))

        clamp_region(event)

        self.assertEqual(event.region_size, (20, 20))

    def test_pixel_mode_is_untouched(self):
        event = screen_event(match_mode="pixel", region_size=(500, 500))

        clamp_region(event)

        self.assertEqual(event.region_size, (500, 500))


if __name__ == "__main__":
    unittest.main(verbosity=2)
