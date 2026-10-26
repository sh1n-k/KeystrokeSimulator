import random
import unittest

from PIL import Image

from app.domain.models import EventModel
from app.domain.profile_events import (
    apply_target_to_same_area,
    build_event_sections,
    copy_event_name,
    move_in_section,
    referenced_event_names,
    snapshot_events,
    sort_sections_by_name,
    write_section_order,
)
from app.domain.validation import (
    condition_cycle_if_added,
    event_name_taken,
    find_condition_cycle,
    max_region_dimension,
    region_limits,
    timing_is_valid,
)
from tests.helpers import make_processor_stub


def rule(name, group=None, priority=0, **kwargs):
    return EventModel(event_name=name, group_id=group, priority=priority, **kwargs)


def signal(name, **kwargs):
    return EventModel(event_name=name, execute_action=False, **kwargs)


def processor_pick(events):
    proc = make_processor_stub()
    data = [
        {
            "name": e.event_name,
            "group": (e.group_id or "").strip() or None,
            "priority": e.priority,
            "exec": True,
        }
        for e in events
    ]
    return {
        evt["group"]: evt["name"]
        for evt in proc._select_by_group_priority(data)
        if evt["group"]
    }


class TestEventSections(unittest.TestCase):
    def test_signals_first_then_groups_by_name_then_ungrouped(self):
        events = [
            rule("r3"),
            rule("b1", "beta"),
            signal("s1"),
            rule("a1", "Alpha"),
        ]

        sections = build_event_sections(events)

        self.assertEqual(
            [(s.kind, s.group) for s in sections],
            [("signal", ""), ("group", "Alpha"), ("group", "beta"), ("ungrouped", "")],
        )

    def test_group_order_is_priority_then_name(self):
        events = [
            rule("02 b", "g", 1),
            rule("01 a", "g", 1),
            rule("03 c", "g", 0),
        ]

        (section,) = build_event_sections(events)

        self.assertEqual(
            [e.event_name for e in section.events], ["03 c", "01 a", "02 b"]
        )

    def test_whitespace_in_group_ids_joins_one_section(self):
        sections = build_event_sections([rule("a", "g"), rule("b", " g ")])

        self.assertEqual(len(sections), 1)


class TestDisplayOrderMatchesProcessor(unittest.TestCase):
    """W-02: the first rule shown in each group is the one the processor runs."""

    def test_existing_profile_order_matches_group_selection(self):
        # Real profiles: equal priorities, order encoded in name numbers.
        events = [rule(f"{n:02d} skill", "beast", 1) for n in (5, 1, 3, 2)]
        events += [rule("b", "other", 2), rule("a", "other", 2), rule("c", "other", 0)]

        shown = {
            s.group: s.events[0].event_name
            for s in build_event_sections(events)
            if s.kind == "group"
        }

        self.assertEqual(shown, processor_pick(events))
        self.assertEqual(shown, {"beast": "01 skill", "other": "c"})

    def test_random_profiles_match_group_selection(self):
        rng = random.Random(7)
        for _ in range(50):
            events = [
                rule(
                    f"e{i}",
                    rng.choice(["x", "y", "z"]),
                    rng.randint(0, 3),
                )
                for i in range(rng.randint(1, 12))
            ]
            shown = {
                s.group: s.events[0].event_name
                for s in build_event_sections(events)
                if s.kind == "group"
            }
            self.assertEqual(shown, processor_pick(events))

    def test_dragged_order_is_what_the_processor_runs(self):
        events = [rule(f"0{n} x", "g", 1) for n in (1, 2, 3)]
        (section,) = build_event_sections(events)

        new_order = move_in_section(section.events, section.events[2], 0)
        write_section_order(new_order)

        self.assertEqual(processor_pick(events), {"g": "03 x"})
        self.assertEqual([e.priority for e in new_order], [0, 1, 2])


class TestOrderWriting(unittest.TestCase):
    def test_write_section_order_reports_changes_only(self):
        events = [rule("a", priority=0), rule("b", priority=1)]

        self.assertFalse(write_section_order(events))
        self.assertTrue(write_section_order(list(reversed(events))))
        self.assertEqual([e.priority for e in events], [1, 0])

    def test_move_in_section_clamps_target(self):
        a, b, c = rule("a"), rule("b"), rule("c")

        self.assertEqual(move_in_section((a, b, c), a, 99), [b, c, a])
        self.assertEqual(move_in_section((a, b, c), c, -5), [c, a, b])

    def test_sort_sections_by_name_rewrites_each_section(self):
        events = [rule("b", "g", 0), rule("a", "g", 5), signal("z"), signal("y")]

        changed = sort_sections_by_name(events)

        self.assertTrue(changed)
        self.assertEqual(
            {e.event_name: e.priority for e in events},
            {"a": 0, "b": 1, "y": 0, "z": 1},
        )

    def test_snapshot_is_independent_of_later_edits(self):
        original = rule("a", "g", 3, conditions={"s": True})

        (copy,) = snapshot_events([original])
        original.priority = 9
        original.conditions["t"] = False

        self.assertEqual(copy.priority, 3)
        self.assertEqual(copy.conditions, {"s": True})


class TestEventHelpers(unittest.TestCase):
    def test_referenced_event_names(self):
        events = [signal("s"), rule("r", conditions={"s": True, "t": False})]

        self.assertEqual(referenced_event_names(events), {"s", "t"})

    def test_copy_event_name_avoids_existing(self):
        events = [rule("a"), rule("a (2)")]

        self.assertEqual(copy_event_name("a", events), "a (3)")

    def test_apply_target_to_same_area(self):
        img = Image.new("RGB", (10, 10), (1, 2, 3))
        source = signal("src", latest_position=(5, 5), clicked_position=(2, 2))
        same = signal("same", latest_position=(5, 5), held_screenshot=img)
        other = signal("other", latest_position=(9, 9), held_screenshot=img)

        count = apply_target_to_same_area([source, same, other], source)

        self.assertEqual(count, 1)
        self.assertEqual(same.clicked_position, (2, 2))
        self.assertEqual(same.ref_pixel_value, (1, 2, 3))
        self.assertIsNone(other.clicked_position)


class TestValidation(unittest.TestCase):
    def test_condition_cycle_detection(self):
        events = [rule("A", conditions={"B": True}), rule("B"), rule("C")]

        self.assertEqual(find_condition_cycle(events, "B", {"A": True}), ["A", "B", "A"])
        self.assertIsNone(find_condition_cycle(events, "C", {"A": True}))

    def test_condition_cycle_if_added(self):
        a = rule("A", conditions={"B": True})
        b = rule("B")
        events = [a, b]

        self.assertIsNotNone(condition_cycle_if_added(events, b, "A"))
        self.assertIsNone(condition_cycle_if_added(events, a, "B"))

    def test_event_name_taken_ignores_the_event_itself(self):
        a = rule("A")

        self.assertFalse(event_name_taken([a], " A ", ignore=a))
        self.assertTrue(event_name_taken([a, rule("B")], "A", ignore=None))

    def test_region_limits(self):
        self.assertEqual(max_region_dimension(50, 100), 100)
        self.assertEqual(max_region_dimension(99, 100), 2)
        self.assertEqual(region_limits((100, 100), (30, 50)), (61, 100))

    def test_timing_rules_match_the_old_editor(self):
        self.assertTrue(timing_is_valid(None, None))
        self.assertFalse(timing_is_valid(40, None))
        self.assertFalse(timing_is_valid(60, 20))
        self.assertTrue(timing_is_valid(None, 20))  # random alone is not checked
        self.assertTrue(timing_is_valid(60, 30))


if __name__ == "__main__":
    unittest.main(verbosity=2)
