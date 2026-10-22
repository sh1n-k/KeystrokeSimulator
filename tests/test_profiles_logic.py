"""프로필 이벤트 공용 로직(app.core.profile_events). 작업 공간 UI 테스트는
test_workspace.py에 있다."""

import unittest

from app.core.models import EventModel
from app.core.profile_events import (
    event_matches_query,
    event_needs_attention,
    remove_condition_references,
    rename_colliding_events,
    rename_condition_references,
)


class TestConditionReferences(unittest.TestCase):
    def test_rename_replaces_old_name_and_keeps_state(self):
        events = [
            EventModel(event_name="A", conditions={"Old": True}),
            EventModel(event_name="B", conditions={"Old": False, "Other": True}),
        ]

        rename_condition_references(events, "Old", "New")

        self.assertEqual(events[0].conditions, {"New": True})
        self.assertEqual(events[1].conditions, {"Other": True, "New": False})

    def test_rename_without_match_is_a_no_op(self):
        events = [EventModel(event_name="A", conditions={"X": True})]

        rename_condition_references(events, "Missing", "New")

        self.assertEqual(events[0].conditions, {"X": True})

    def test_remove_drops_only_that_reference(self):
        events = [EventModel(event_name="A", conditions={"X": True, "Y": False})]

        remove_condition_references(events, "X")

        self.assertEqual(events[0].conditions, {"Y": False})


class TestSearchAndAttention(unittest.TestCase):
    def setUp(self):
        self.attack = EventModel(event_name="Attack", key_to_enter="A", group_id="Combat")
        self.watch = EventModel(event_name="Watch HP", execute_action=False, group_id="Combat")

    def test_query_matches_name_key_and_group(self):
        self.assertTrue(event_matches_query(self.attack, "att"))
        self.assertTrue(event_matches_query(self.watch, "combat"))
        self.assertFalse(event_matches_query(self.attack, "heal"))

    def test_query_is_case_insensitive_and_trimmed(self):
        self.assertTrue(event_matches_query(self.attack, "  ATTACK "))
        self.assertTrue(event_matches_query(self.attack, "   "))

    def test_attention_is_for_rules_without_a_key(self):
        self.assertFalse(event_needs_attention(self.watch))
        self.assertFalse(event_needs_attention(self.attack))
        self.assertTrue(event_needs_attention(EventModel(event_name="X", key_to_enter="  ")))


class TestRenameCollidingEvents(unittest.TestCase):
    """B-04 / W-12: copied events never collide, references follow the rename."""

    def test_rename_colliding_events_updates_references_inside_batch(self):
        imported = [
            EventModel(event_name="A"),
            EventModel(event_name="B", conditions={"A": True, "C": False}),
        ]

        renamed = rename_colliding_events(imported, ["A", "C", "A (2)"])

        self.assertEqual(renamed, {"A": "A (3)"})
        self.assertEqual([e.event_name for e in imported], ["A (3)", "B"])
        self.assertEqual(imported[1].conditions, {"A (3)": True, "C": False})


if __name__ == "__main__":
    unittest.main(verbosity=2)
