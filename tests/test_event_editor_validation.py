import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import tkinter as tk
from PIL import Image

from keystroke_event_editor import KeystrokeEventEditor
from keystroke_models import EventModel


class TestEditorCycleValidation(unittest.TestCase):
    """KeystrokeEventEditor._validate_cycles: 순환 참조 검증"""

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

    def test_validate_cycles_self_reference(self):
        """자기 참조 감지"""
        stub = SimpleNamespace(
            existing_events=[
                EventModel(event_name="A", conditions={}),
            ]
        )
        has_cycle = KeystrokeEventEditor._validate_cycles(stub, "A", {"A": True})
        self.assertTrue(has_cycle)

    def test_validate_cycles_three_node_cycle(self):
        """3노드 순환 감지"""
        stub = SimpleNamespace(
            existing_events=[
                EventModel(event_name="A", conditions={"C": True}),
                EventModel(event_name="B", conditions={"A": True}),
                EventModel(event_name="C", conditions={}),
            ]
        )
        has_cycle = KeystrokeEventEditor._validate_cycles(stub, "C", {"B": True})
        self.assertTrue(has_cycle)


class TestValidateRequiredFields(unittest.TestCase):
    """KeystrokeEventEditor._validate_required_fields: 필수 필드 검증"""

    def _make_editor_stub(self, latest_pos=None, clicked_pos=None,
                          held_img=None, ref_pixel=None, key_to_enter=None,
                          execute_action=True):
        stub = SimpleNamespace(
            latest_pos=latest_pos,
            clicked_pos=clicked_pos,
            held_img=held_img,
            ref_pixel=ref_pixel,
            key_to_enter=key_to_enter,
            execute_action_var=SimpleNamespace(get=lambda: execute_action),
        )
        return stub

    @patch("keystroke_event_editor.messagebox")
    def test_missing_position_fails(self, mock_msgbox):
        """좌표 누락 시 False"""
        stub = self._make_editor_stub(
            latest_pos=None, clicked_pos=(10, 20),
            held_img="img", ref_pixel=(1, 2, 3), key_to_enter="A",
        )
        result = KeystrokeEventEditor._validate_required_fields(stub)
        self.assertFalse(result)

    @patch("keystroke_event_editor.messagebox")
    def test_missing_key_when_execute_action(self, mock_msgbox):
        """execute_action=True에서 키 누락 시 False"""
        stub = self._make_editor_stub(
            latest_pos=(1, 2), clicked_pos=(10, 20),
            held_img="img", ref_pixel=(1, 2, 3), key_to_enter=None,
            execute_action=True,
        )
        result = KeystrokeEventEditor._validate_required_fields(stub)
        self.assertFalse(result)

    @patch("keystroke_event_editor.messagebox")
    def test_missing_held_img_fails(self, mock_msgbox):
        """held_img 누락 시 False (region 모드에서 특히 중요)"""
        stub = self._make_editor_stub(
            latest_pos=(1, 2), clicked_pos=(10, 20),
            held_img=None, ref_pixel=(1, 2, 3), key_to_enter="A",
        )
        result = KeystrokeEventEditor._validate_required_fields(stub)
        self.assertFalse(result)

    def test_valid_event_passes(self):
        """유효한 이벤트 → True"""
        stub = self._make_editor_stub(
            latest_pos=(1, 2), clicked_pos=(10, 20),
            held_img="img", ref_pixel=(1, 2, 3), key_to_enter="A",
        )
        result = KeystrokeEventEditor._validate_required_fields(stub)
        self.assertTrue(result)


class TestRegionSizeClamp(unittest.TestCase):
    def test_on_region_size_change_allows_20x20(self):
        stub = KeystrokeEventEditor.__new__(KeystrokeEventEditor)
        interp = tk.Tcl()
        stub.region_w_var = tk.IntVar(master=interp, value=10)
        stub.region_h_var = tk.IntVar(master=interp, value=15)
        stub.held_img = None
        stub.clicked_pos = None
        stub.lbl_img2 = None
        stub._draw_overlay = MagicMock()
        stub._sync_region_constraints = MagicMock()

        KeystrokeEventEditor._on_region_size_change(stub)

        self.assertEqual(stub.region_w_var.get(), 20)
        self.assertEqual(stub.region_h_var.get(), 20)

    def test_on_region_size_change_clamps_to_available_bounds(self):
        stub = KeystrokeEventEditor.__new__(KeystrokeEventEditor)
        interp = tk.Tcl()
        stub.region_w_var = tk.IntVar(master=interp, value=80)
        stub.region_h_var = tk.IntVar(master=interp, value=70)
        stub.held_img = Image.new("RGB", (100, 100))
        stub.clicked_pos = (30, 30)
        stub.lbl_img2 = None
        stub._draw_overlay = MagicMock()
        stub._sync_region_constraints = MagicMock()

        KeystrokeEventEditor._on_region_size_change(stub)

        self.assertEqual(stub.region_w_var.get(), 61)
        self.assertEqual(stub.region_h_var.get(), 61)

    def test_sync_region_constraints_disables_inputs_when_point_is_too_close_to_edge(self):
        stub = KeystrokeEventEditor.__new__(KeystrokeEventEditor)
        interp = tk.Tcl()
        stub.match_mode_var = tk.StringVar(master=interp, value="region")
        stub.held_img = Image.new("RGB", (100, 100))
        stub.clicked_pos = (5, 50)
        stub.entry_region_w = MagicMock()
        stub.entry_region_h = MagicMock()

        KeystrokeEventEditor._sync_region_constraints(stub)

        stub.entry_region_w.config.assert_called_once_with(to=20, state="disabled")
        stub.entry_region_h.config.assert_called_once_with(to=100, state="disabled")


class TestRegionBoundsValidation(unittest.TestCase):
    def _make_stub(self, clicked_position=(50, 50), image_size=(100, 100), mode="region"):
        stub = KeystrokeEventEditor.__new__(KeystrokeEventEditor)
        interp = tk.Tcl()
        stub.match_mode_var = tk.StringVar(master=interp, value=mode)
        stub.clicked_pos = clicked_position
        stub.held_img = Image.new("RGB", image_size)
        return stub

    def test_max_region_dimension_even_and_odd(self):
        self.assertEqual(KeystrokeEventEditor._max_region_dimension(50, 100), 100)
        self.assertEqual(KeystrokeEventEditor._max_region_dimension(99, 100), 2)
        self.assertEqual(KeystrokeEventEditor._max_region_dimension(0, 100), 1)

    @patch("keystroke_event_editor.messagebox")
    def test_validate_region_bounds_rejects_edge_point_under_minimum(self, mock_messagebox):
        stub = self._make_stub(clicked_position=(5, 50))

        result = KeystrokeEventEditor._validate_region_bounds(stub, 20, 20)

        self.assertFalse(result)
        mock_messagebox.showerror.assert_called_once()

    @patch("keystroke_event_editor.messagebox")
    def test_validate_region_bounds_rejects_size_over_limit(self, mock_messagebox):
        stub = self._make_stub(clicked_position=(30, 30), image_size=(100, 100))

        result = KeystrokeEventEditor._validate_region_bounds(stub, 80, 80)

        self.assertFalse(result)
        mock_messagebox.showerror.assert_called_once()

    @patch("keystroke_event_editor.messagebox")
    def test_validate_region_bounds_accepts_valid_size(self, mock_messagebox):
        stub = self._make_stub(clicked_position=(30, 30), image_size=(100, 100))

        result = KeystrokeEventEditor._validate_region_bounds(stub, 20, 20)

        self.assertTrue(result)
        mock_messagebox.showerror.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
