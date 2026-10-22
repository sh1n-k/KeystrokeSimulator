"""이벤트 편집 검증 — 모달 편집기(event_editor.py) 제거 후 상세 패널 기준."""

import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from app.core.models import EventModel
from app.ui.capture_hud import CaptureResult
from app.ui.workspace_detail import (
    EventDetailPanel,
    apply_capture,
    capture_from_event,
    clamp_region,
    clear_capture,
    event_issues,
)
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
            event_name="r", key_to_enter="A", conditions={"s": True}, match_mode="region"
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
        event = screen_event(match_mode="region", region_size=(40, 40), invert_match=True)

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


def _panel_stub(events, event):
    panel = EventDetailPanel.__new__(EventDetailPanel)
    interp = tk.Tcl()
    panel.events_getter = lambda: events
    panel.event = event
    panel._syncing = False
    panel.name_var = tk.StringVar(master=interp, value=event.event_name)
    panel.lbl_name_error = MagicMock()
    panel.on_change = MagicMock()
    panel.refresh = MagicMock()
    panel.running_getter = lambda: False
    panel.capture_hud = None
    panel.before_screen_change = MagicMock()
    return panel


class TestDetailPanelName(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_rename_updates_dependent_conditions(self):
        a = EventModel(event_name="A")
        b = EventModel(event_name="B", conditions={"A": True})
        panel = _panel_stub([a, b], a)
        panel.name_var.set("A2")

        panel._commit_name()

        self.assertEqual(a.event_name, "A2")
        self.assertEqual(b.conditions, {"A2": True})
        panel.on_change.assert_called_once_with(a, "name")

    def test_duplicate_or_blank_name_is_rejected(self):
        a = EventModel(event_name="A")
        b = EventModel(event_name="B")
        panel = _panel_stub([a, b], a)

        for bad in (" B ", "  "):
            panel.name_var.set(bad)
            self.assertEqual(panel._commit_name(), "break")

        self.assertEqual(a.event_name, "A")
        panel.on_change.assert_not_called()


class TestConditionCandidates(unittest.TestCase):
    """W-07: signals first, cycles shown as disabled with the path."""

    def test_candidates_order_and_cycle_reason(self):
        target = EventModel(event_name="R1", conditions={"S1": True})
        rule_referencing_target = EventModel(event_name="R2", conditions={"R1": True})
        signal = EventModel(event_name="S2", execute_action=False)
        used = EventModel(event_name="S1", execute_action=False)
        panel = _panel_stub([target, rule_referencing_target, signal, used], target)

        candidates = panel.condition_candidates()

        self.assertEqual([e.event_name for e, _ in candidates], ["S2", "R2"])
        self.assertIsNone(candidates[0][1])
        self.assertEqual(candidates[1][1], ["R1", "R2", "R1"])


class TestDetailPanelCapture(unittest.TestCase):
    @patch("app.ui.workspace_detail.CaptureHud")
    def test_capture_opens_single_hud_with_event_screen(self, mock_hud):
        event = screen_event(event_name="E", match_mode="region", region_size=(40, 30))
        panel = _panel_stub([event], event)
        panel.winfo_toplevel = MagicMock()

        panel.open_capture()

        kwargs = mock_hud.call_args.kwargs
        self.assertEqual(kwargs["mode"], "single")
        self.assertTrue(kwargs["grab"])
        self.assertTrue(kwargs["border"])
        self.assertEqual(kwargs["region_size"], (40, 30))
        self.assertEqual(kwargs["initial"].pixel, (50, 50))

        result = CaptureResult((1, 2), (60, 60), Image.new("RGB", (60, 60)), (3, 4), (5, 6, 7))
        panel._changed = MagicMock()
        kwargs["on_apply"](result)

        self.assertEqual(event.latest_position, (1, 2))
        panel._changed.assert_called_once_with("screen")

    @patch("app.ui.workspace_detail.CaptureHud")
    def test_capture_while_running_draws_no_border(self, mock_hud):
        event = EventModel(event_name="E")
        panel = _panel_stub([event], event)
        panel.winfo_toplevel = MagicMock()
        panel.running_getter = lambda: True

        panel.open_capture()

        self.assertFalse(mock_hud.call_args.kwargs["border"])
        self.assertIsNone(mock_hud.call_args.kwargs["initial"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
