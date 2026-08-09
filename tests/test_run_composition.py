import unittest

from app.core.models import EventModel, ProfileModel
from app.core.run_composition import (
    compose_run_session,
    format_run_profile_summary,
    namespace_event,
    namespaced_token,
    normalize_run_profile_list,
)


class TestNamespace(unittest.TestCase):
    def test_namespaced_token(self) -> None:
        self.assertEqual(namespaced_token("Rot", "Heal"), "Rot/Heal")

    def test_namespace_event_rewrites_name_group_conditions(self) -> None:
        evt = EventModel(
            event_name="Skill",
            group_id="gcd",
            conditions={"Buff": True, "Other": False},
            key_to_enter="1",
        )
        out = namespace_event("Warrior", evt)
        self.assertEqual(out.event_name, "Warrior/Skill")
        self.assertEqual(out.group_id, "Warrior/gcd")
        self.assertEqual(
            out.conditions, {"Warrior/Buff": True, "Warrior/Other": False}
        )
        self.assertEqual(evt.event_name, "Skill")
        self.assertEqual(evt.group_id, "gcd")

    def test_empty_group_stays_none(self) -> None:
        evt = EventModel(event_name="A", group_id="  ", key_to_enter="1")
        out = namespace_event("P", evt)
        self.assertIsNone(out.group_id)


class TestComposeRunSession(unittest.TestCase):
    def test_empty_selection_errors(self) -> None:
        session = compose_run_session([])
        self.assertFalse(session.ok)
        self.assertTrue(session.errors)

    def test_merges_two_profiles_without_name_collision(self) -> None:
        a = ProfileModel(
            name="A",
            event_list=[
                EventModel(event_name="Heal", use_event=True, key_to_enter="1"),
                EventModel(
                    event_name="Cond",
                    use_event=True,
                    execute_action=False,
                    conditions={"Heal": True},
                ),
            ],
        )
        b = ProfileModel(
            name="B",
            event_list=[
                EventModel(event_name="Heal", use_event=True, key_to_enter="2"),
            ],
        )
        session = compose_run_session([("A", a), ("B", b)])
        self.assertTrue(session.ok)
        names = [e.event_name for e in session.events]
        self.assertEqual(names, ["A/Heal", "A/Cond", "B/Heal"])
        cond = next(e for e in session.events if e.event_name == "A/Cond")
        self.assertEqual(cond.conditions, {"A/Heal": True})

    def test_duplicate_names_within_profile_error(self) -> None:
        p = ProfileModel(
            event_list=[
                EventModel(event_name="X", key_to_enter="1"),
                EventModel(event_name="X", key_to_enter="2"),
            ]
        )
        session = compose_run_session([("P", p)])
        self.assertFalse(session.ok)
        self.assertTrue(
            any("X" in err or "중복" in err or "Duplicate" in err for err in session.errors)
        )

    def test_runtime_toggle_conflicting_keys_error(self) -> None:
        a = ProfileModel(
            event_list=[
                EventModel(event_name="Base", use_event=True, key_to_enter="A"),
                EventModel(
                    event_name="Extra",
                    use_event=True,
                    key_to_enter="B",
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=True,
            runtime_toggle_key="F6",
        )
        b = ProfileModel(
            event_list=[
                EventModel(event_name="Base", use_event=True, key_to_enter="C"),
                EventModel(
                    event_name="Extra",
                    use_event=True,
                    key_to_enter="D",
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=True,
            runtime_toggle_key="F7",
        )
        session = compose_run_session([("A", a), ("B", b)])
        self.assertFalse(session.ok)
        self.assertTrue(
            any("differ" in e.lower() or "다릅니다" in e for e in session.errors)
        )

    def test_runtime_toggle_same_key_merges(self) -> None:
        a = ProfileModel(
            event_list=[
                EventModel(event_name="Base", use_event=True, key_to_enter="A"),
                EventModel(
                    event_name="Extra",
                    use_event=True,
                    key_to_enter="B",
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=True,
            runtime_toggle_key="F6",
        )
        b = ProfileModel(
            event_list=[
                EventModel(event_name="Util", use_event=True, key_to_enter="C"),
            ],
            runtime_toggle_enabled=False,
        )
        session = compose_run_session([("A", a), ("B", b)])
        self.assertTrue(session.ok, session.errors)
        self.assertTrue(session.runtime_toggle_enabled)
        self.assertEqual(session.runtime_toggle_key, "F6")

    def test_orphan_toggle_members_cleared_when_profile_toggle_off(self) -> None:
        rot = ProfileModel(
            event_list=[
                EventModel(event_name="Base", use_event=True, key_to_enter="A"),
                EventModel(
                    event_name="Extra",
                    use_event=True,
                    key_to_enter="B",
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=True,
            runtime_toggle_key="F6",
        )
        util = ProfileModel(
            event_list=[
                EventModel(
                    event_name="Potion",
                    use_event=True,
                    key_to_enter="C",
                    runtime_toggle_member=True,
                ),
            ],
            runtime_toggle_enabled=False,
        )
        session = compose_run_session([("Rot", rot), ("Util", util)])
        self.assertTrue(session.ok, session.errors)
        util_evt = next(e for e in session.events if e.event_name == "Util/Potion")
        self.assertFalse(util_evt.runtime_toggle_member)
        rot_extra = next(e for e in session.events if e.event_name == "Rot/Extra")
        self.assertTrue(rot_extra.runtime_toggle_member)


class TestHelpers(unittest.TestCase):
    def test_format_summary(self) -> None:
        self.assertEqual(format_run_profile_summary([]), "—")
        self.assertEqual(format_run_profile_summary(["A", "B"]), "A · B")
        self.assertIn(
            "+1", format_run_profile_summary(["A", "B", "C", "D"], max_names=3)
        )

    def test_normalize_run_profile_list(self) -> None:
        self.assertEqual(
            normalize_run_profile_list(["B", "A", "B", "missing"], {"A", "B", "C"}),
            ["B", "A"],
        )


if __name__ == "__main__":
    unittest.main()
