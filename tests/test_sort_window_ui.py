import unittest
from pathlib import Path
from unittest.mock import patch

from keystroke_models import EventModel, ProfileModel
from keystroke_sort_events import (
    KeystrokeSortEvents,
    SW_FG_MUTED,
    SW_FG_PRIMARY,
    SW_FG_WARN,
)
from i18n import set_language


class FakeVar:
    def __init__(self, value: str):
        self.value = value

    def get(self) -> str:
        return self.value


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


class TestSortWindowMessages(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_load_profile_error_message_uses_default_language(self):
        stub = KeystrokeSortEvents.__new__(KeystrokeSortEvents)
        stub.prof_dir = Path("profiles")
        stub.close = lambda *args, **kwargs: None

        with patch("keystroke_sort_events.load_profile", side_effect=RuntimeError("boom")):
            with patch("keystroke_sort_events.messagebox.showerror") as mock_error:
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

        with patch("keystroke_sort_events.save_profile", side_effect=RuntimeError("boom")):
            with patch("keystroke_sort_events.logger.error") as mock_log:
                with patch("keystroke_sort_events.messagebox.showerror") as mock_error:
                    stub.save()

        mock_log.assert_called_once()
        mock_error.assert_called_once()
        args, kwargs = mock_error.call_args
        self.assertEqual(args[0], "Save Failed")
        self.assertIn("An error occurred while saving profile", args[1])
        self.assertIs(kwargs["parent"], stub)


if __name__ == "__main__":
    unittest.main(verbosity=2)
