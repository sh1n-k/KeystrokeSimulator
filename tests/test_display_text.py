"""작업 공간 동작. 대부분은 Tk 없이 stub으로, 창 흐름은 RUN_GUI_TESTS에서."""

import tempfile
import unittest
from pathlib import Path

from app.domain.models import EventModel, ProfileModel
from app.storage.profile_storage import save_profile
from app.storage.profile_storage import ordered_profile_names
from app.domain.display_text import (
    condition_summary,
    row_badges,
    section_note,
    section_title,
)
from app.presenters.workspace_sidebar import sidebar_actions
from app.domain.profile_events import build_event_sections
from app.utils.i18n import set_language


def rule(name, group=None, priority=0, **kwargs):
    return EventModel(event_name=name, group_id=group, priority=priority, **kwargs)


def signal(name, **kwargs):
    return EventModel(event_name=name, execute_action=False, **kwargs)


class TestListPresentation(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_section_titles(self):
        sections = build_event_sections([signal("s"), rule("r", "g"), rule("n")])

        self.assertEqual(
            [section_title(s) for s in sections],
            ["Signals (1)", "Rules · group g (1)", "Rules · no group (1)"],
        )
        self.assertEqual(
            [section_note(s) for s in sections],
            ["Conditions only", "Top match runs", "All matches run"],
        )

    def test_condition_summary_marks_off_states_and_truncates(self):
        event = rule("r", conditions={"a": True, "b": False})

        self.assertEqual(condition_summary(event), "a · !b")
        self.assertTrue(condition_summary(event, limit=4).endswith("…"))

    def test_badges(self):
        event = rule("r", runtime_toggle_member=True, use_event=False)

        badges = row_badges(event, referenced=True, toggle_enabled=False)
        self.assertEqual(badges, ["off", "no key", "no trigger", "referenced"])
        self.assertIn(
            "hotkey", row_badges(event, referenced=False, toggle_enabled=True)
        )

    def test_quick_cannot_be_renamed_or_deleted(self):
        actions = {a for a, _ in sidebar_actions("profile", "Quick")}

        self.assertNotIn("rename", actions)
        self.assertNotIn("delete", actions)
        self.assertIn("delete", {a for a, _ in sidebar_actions("profile", "X")})

    def test_profile_order_is_quick_favorites_then_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name, fav in (("b", False), ("a", False), ("z", True)):
                save_profile(
                    d, ProfileModel(name=name, event_list=[], favorite=fav), name=name
                )

            names, favorites = ordered_profile_names(d)

        self.assertEqual(names, ["Quick", "z", "a", "b"])
        self.assertEqual(favorites, {"z"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
