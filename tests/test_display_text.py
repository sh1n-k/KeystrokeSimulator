"""작업 공간 목록 표시 문구(구역 제목·조건 요약·배지)와 프로필 규칙(Quick·정렬)."""

import tempfile
import unittest
from pathlib import Path

from app.domain.models import EventModel, ProfileModel
from app.storage.profile_storage import save_profile
from app.storage.profile_storage import ordered_profile_names
from app.domain.display_text import (
    BULK_MATRIX_MAX_EVENTS,
    BULK_COLUMN_MARKS,
    bulk_column_legend,
    bulk_condition_rows,
    bulk_condition_view,
    condition_summary,
    natural_key,
    row_badges,
    row_detail,
    section_note,
    section_title,
    sorted_conditions,
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
            ["States (1)", "Actions · group g (1)", "Actions · no group (1)"],
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

    def test_derived_state_row(self):
        derived = signal("d", conditions={"a": True, "b": False})

        self.assertEqual(row_badges(derived, referenced=False, toggle_enabled=False), ["derived"])
        self.assertEqual(row_detail(derived), "a · !b")
        self.assertEqual(
            row_badges(signal("s"), referenced=False, toggle_enabled=False), ["no screen"]
        )
        self.assertEqual(row_detail(signal("s")), "")

    def test_bulk_condition_rows(self):
        events = [
            rule("x", conditions={"a": True, "b": False}),
            rule("y", conditions={"a": True, "b": True}),
            rule("z", conditions={"a": True}),
        ]

        rows = bulk_condition_rows(events)
        self.assertEqual([r.name for r in rows], ["a", "b"])
        self.assertEqual(rows[0].cells, (True, True, True))
        self.assertTrue(rows[0].uniform)
        self.assertEqual(rows[1].cells, (False, True, None))
        self.assertEqual((rows[1].on, rows[1].off, rows[1].missing), (1, 1, 1))
        self.assertFalse(rows[1].uniform)
        # 목록 순서를 주면 그 순서, 목록에 없는 이름은 뒤에 둔다.
        events.append(rule("w", conditions={"gone": False}))
        rows = bulk_condition_rows(events, ["b", "a"])
        self.assertEqual([r.name for r in rows], ["b", "a", "gone"])
        self.assertEqual(rows[2].cells, (None, None, None, False))
        self.assertEqual(bulk_condition_rows([rule("z")]), [])

    def test_bulk_column_legend(self):
        self.assertEqual(bulk_column_legend(["a", "b c"]), "① a   ② b c")
        self.assertEqual(len(BULK_COLUMN_MARKS), BULK_MATRIX_MAX_EVENTS)

    def test_bulk_condition_view_switches_after_limit(self):
        self.assertEqual(bulk_condition_view(2), "matrix")
        self.assertEqual(bulk_condition_view(BULK_MATRIX_MAX_EVENTS), "matrix")
        self.assertEqual(bulk_condition_view(BULK_MATRIX_MAX_EVENTS + 1), "summary")

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


CONDS = {"사거리 30": True, "Buff": False, "사거리 5": False, "aura": True}


class TestConditionSort(unittest.TestCase):
    def test_natural_key_compares_numbers_as_numbers(self):
        names = ["사거리 30", "사거리 5", "사거리 100", "Buff 2", "buff 10"]

        self.assertEqual(
            sorted(names, key=natural_key),
            ["Buff 2", "buff 10", "사거리 5", "사거리 30", "사거리 100"],
        )

    def test_unsorted_keeps_saved_order(self):
        self.assertEqual(sorted_conditions(CONDS, None), list(CONDS.items()))

    def test_name_ascending_and_descending(self):
        names = [n for n, _ in sorted_conditions(CONDS, "name")]
        self.assertEqual(names, ["aura", "Buff", "사거리 5", "사거리 30"])
        names = [n for n, _ in sorted_conditions(CONDS, "name", True)]
        self.assertEqual(names, ["사거리 30", "사거리 5", "Buff", "aura"])

    def test_state_groups_on_first_then_name_ascending(self):
        self.assertEqual(
            sorted_conditions(CONDS, "state"),
            [("aura", True), ("사거리 30", True), ("Buff", False), ("사거리 5", False)],
        )
        self.assertEqual(
            sorted_conditions(CONDS, "state", True),
            [("Buff", False), ("사거리 5", False), ("aura", True), ("사거리 30", True)],
        )
