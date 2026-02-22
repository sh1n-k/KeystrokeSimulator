import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
