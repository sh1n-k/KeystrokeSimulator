"""실행 가능 판정(`EventModel.has_processor_inputs`)을 쓰는 세 경로의 일치 검증.

시작 가능 여부(`events_with_processor_inputs`), processor 로드(`_init_event_data`),
작업 공간 배지(`event_issues`)가 같은 이벤트를 같은 기준으로 다뤄야 한다.
"""

import unittest

from PIL import Image

from app.domain.event_editing import event_issues
from app.domain.models import EventModel
from app.engine.processor import KeystrokeProcessor
from app.presenters.run_controller import events_with_processor_inputs
from app.utils.i18n import set_language


def _processor() -> KeystrokeProcessor:
    proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
    proc.key_codes = {"A": 0}
    return proc


def _image() -> Image.Image:
    return Image.new("RGB", (40, 40), (1, 2, 3))


def _cases() -> dict[str, tuple[EventModel, bool]]:
    """이름 → (이벤트, has_processor_inputs 기대값)."""
    screen = {"latest_position": (10, 10), "clicked_position": (20, 20)}
    return {
        "pixel_complete": (
            EventModel(event_name="p", key_to_enter="A", ref_pixel_value=(1, 2, 3), **screen),
            True,
        ),
        "pixel_rgba": (
            EventModel(event_name="p4", key_to_enter="A", ref_pixel_value=(1, 2, 3, 255), **screen),
            True,
        ),
        "pixel_missing_ref": (
            EventModel(event_name="p0", key_to_enter="A", **screen),
            False,
        ),
        "pixel_short_ref": (
            EventModel(event_name="p2", key_to_enter="A", ref_pixel_value=(1, 2), **screen),
            False,
        ),
        "region_complete": (
            EventModel(
                event_name="r",
                key_to_enter="A",
                match_mode="region",
                held_screenshot=_image(),
                ref_pixel_value=(1, 2, 3),
                region_size=(10, 10),
                **screen,
            ),
            True,
        ),
        "region_missing_image": (
            EventModel(
                event_name="r0",
                key_to_enter="A",
                match_mode="region",
                ref_pixel_value=(1, 2, 3),
                **screen,
            ),
            False,
        ),
        "unknown_mode_needs_pixel_ref": (
            EventModel(event_name="u", key_to_enter="A", match_mode="other", **screen),
            False,
        ),
        "unknown_mode_short_ref": (
            # 예전 processor는 여기서 ref_pixel_value[2] IndexError가 났다.
            EventModel(
                event_name="u2",
                key_to_enter="A",
                match_mode="other",
                ref_pixel_value=(1, 2),
                **screen,
            ),
            False,
        ),
        "unknown_mode_complete": (
            EventModel(
                event_name="u3",
                key_to_enter="A",
                match_mode="other",
                ref_pixel_value=(1, 2, 3),
                **screen,
            ),
            True,
        ),
        "screenless_input": (
            EventModel(event_name="s", key_to_enter="A", conditions={"p": True}),
            True,
        ),
        "no_screen_no_condition": (
            EventModel(event_name="n", key_to_enter="A"),
            False,
        ),
        # 화면 없이 조건만 있는 상태는 파생 상태로 로드한다.
        "derived_state": (
            EventModel(event_name="st", execute_action=False, conditions={"p": True}),
            True,
        ),
        "state_without_screen_or_conditions": (
            EventModel(event_name="st0", execute_action=False),
            False,
        ),
        "state_complete": (
            EventModel(event_name="st2", execute_action=False, ref_pixel_value=(1, 2, 3), **screen),
            True,
        ),
    }


class TestProcessorInputsConsistency(unittest.TestCase):
    def setUp(self) -> None:
        set_language("en")

    def test_model_predicate(self) -> None:
        for name, (event, expected) in _cases().items():
            with self.subTest(name):
                self.assertEqual(event.has_processor_inputs(), expected)

    def test_run_readiness_uses_same_predicate(self) -> None:
        for name, (event, expected) in _cases().items():
            with self.subTest(name):
                self.assertEqual(bool(events_with_processor_inputs([event])), expected)

    def test_processor_loads_exactly_events_with_inputs(self) -> None:
        proc = _processor()
        for name, (event, expected) in _cases().items():
            with self.subTest(name):
                self.assertEqual(len(proc._init_event_data([event])), int(expected))

    def test_processor_skips_disabled_events(self) -> None:
        event, _ = _cases()["pixel_complete"]
        event.use_event = False
        self.assertEqual(_processor()._init_event_data([event]), [])

    def test_workspace_badge_flags_every_event_processor_would_drop(self) -> None:
        for name, (event, expected) in _cases().items():
            with self.subTest(name):
                if not expected:
                    self.assertTrue(event_issues(event), name)

    def test_loadable_events_never_get_incomplete_capture_badge(self) -> None:
        incomplete = "The screen capture is incomplete. Capture again."
        for name, (event, expected) in _cases().items():
            with self.subTest(name):
                if expected:
                    self.assertNotIn(incomplete, event_issues(event))

    def test_incomplete_capture_badge(self) -> None:
        event, _ = _cases()["pixel_missing_ref"]
        self.assertIn(
            "The screen capture is incomplete. Capture again.", event_issues(event)
        )
        complete, _ = _cases()["pixel_complete"]
        self.assertEqual(event_issues(complete), [])


if __name__ == "__main__":
    unittest.main()
