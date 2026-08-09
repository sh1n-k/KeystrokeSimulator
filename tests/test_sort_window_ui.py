import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.models import EventModel, ProfileModel
from app.ui.sort_events import (
    KeystrokeSortEvents,
    SW_FG_MUTED,
    SW_FG_PRIMARY,
    SW_FG_WARN,
)
from app.utils.i18n import set_language


class FakeVar:
    def __init__(self, value: str):
        self.value = value

    def get(self) -> str:
        return self.value


class FakeRow:
    def __init__(self, event: EventModel, y: int, height: int = 20):
        self._event_model = event
        self._y = y
        self._height = height

    def configure(self, **_kwargs):
        pass

    def winfo_y(self):
        return self._y

    def winfo_height(self):
        return self._height


class FakeRowContainer:
    def __init__(self, children):
        self.children = children

    def winfo_children(self):
        return self.children


class TestSortWindowFormatting(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_format_group_text(self):
        evt_with_group = EventModel(group_id="G1", priority=2)
        evt_without_group = EventModel(group_id=None, priority=0)

        self.assertEqual(KeystrokeSortEvents._format_group_text(evt_with_group), "G1 (2)")
        self.assertEqual(
            KeystrokeSortEvents._format_group_text(evt_without_group),
            "No Group",
        )

    def test_format_key_text(self):
        evt_action = EventModel(execute_action=True, key_to_enter="A")
        evt_missing = EventModel(execute_action=True, key_to_enter=None)
        evt_cond = EventModel(execute_action=False, key_to_enter=None)

        self.assertEqual(
            KeystrokeSortEvents._format_key_text(evt_action),
            ("A", SW_FG_PRIMARY),
        )
        self.assertEqual(
            KeystrokeSortEvents._format_key_text(evt_missing),
            ("No Key", SW_FG_WARN),
        )
        self.assertEqual(
            KeystrokeSortEvents._format_key_text(evt_cond),
            ("Condition", SW_FG_MUTED),
        )

    def test_build_summary_text(self):
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.events = [EventModel(event_name="A"), EventModel(event_name="B")]

        text = stub._build_summary_text()

        self.assertIn("2 event(s)", text)
        self.assertIn("Drag the handle", text)

    def test_drag_end_uses_bound_event_instead_of_first_child_label(self):
        events = [
            EventModel(event_name="A"),
            EventModel(event_name="B"),
            EventModel(event_name="C"),
        ]
        moving = FakeRow(events[0], y=100)
        row_b = FakeRow(events[1], y=20)
        row_c = FakeRow(events[2], y=60)
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.events = events[:]
        stub.f_events = FakeRowContainer([moving, row_b, row_c])
        stub._drag_data = {"frame": moving}
        stub._refresh_list = lambda: None

        KeystrokeSortEvents._drag_end(stub, None, moving)

        self.assertEqual([evt.event_name for evt in stub.events], ["B", "C", "A"])
        self.assertFalse(hasattr(stub, "_drag_data"))


class TestSortWindowMessages(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_load_profile_error_message_uses_default_language(self):
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.prof_dir = Path("profiles")
        stub.close = lambda *args, **kwargs: None

        with patch("app.ui.sort_events.load_profile", side_effect=RuntimeError("boom")):
            with patch("app.ui.sort_events.messagebox.showerror") as mock_error:
                result = stub._load_profile("Quick")

        self.assertIsNone(result)
        mock_error.assert_called_once()
        args, kwargs = mock_error.call_args
        self.assertEqual(args[0], "Error")
        self.assertIn("Failed to load profile", args[1])
        self.assertIs(kwargs["parent"], stub)

    def test_save_error_message_uses_default_language(self):
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.profile = ProfileModel(name="Quick", event_list=[])
        stub.events = []
        stub.prof_name = FakeVar("Quick")
        stub.save_cb = lambda _name: None
        stub.close = lambda *args, **kwargs: None

        with patch("app.ui.sort_events.save_profile", side_effect=RuntimeError("boom")):
            with patch("app.ui.sort_events.logger.error") as mock_log:
                with patch("app.ui.sort_events.messagebox.showerror") as mock_error:
                    stub.save()

        mock_log.assert_called_once()
        mock_error.assert_called_once()
        args, kwargs = mock_error.call_args
        self.assertEqual(args[0], "Save Failed")
        self.assertIn("An error occurred while saving profile", args[1])
        self.assertIs(kwargs["parent"], stub)


if __name__ == "__main__":
    unittest.main(verbosity=2)
