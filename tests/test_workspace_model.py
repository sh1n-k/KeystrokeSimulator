"""작업 공간 presenter. UI 툴킷 없이 상태·되돌리기·자동 저장을 검증한다."""

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from app.domain.capture_geometry import CaptureResult
from app.domain.models import EventModel, ProfileModel
from app.presenters.workspace_model import (
    AUTOSAVE_DELAY_MS,
    UNDO_LIMIT,
    WorkspaceError,
    WorkspaceModel,
)
from app.storage.profile_storage import list_profile_names, load_profile, save_profile
from app.storage.run_sets_storage import get_run_set, list_run_set_names, upsert_run_set
from app.utils.i18n import set_language


def rule(name, group=None, priority=0, **kwargs):
    return EventModel(event_name=name, group_id=group, priority=priority, **kwargs)


def signal(name, **kwargs):
    return EventModel(event_name=name, execute_action=False, **kwargs)


def captured(name="S", color=(255, 0, 0)):
    return signal(
        name,
        latest_position=(10, 20),
        clicked_position=(1, 2),
        held_screenshot=Image.new("RGB", (5, 5), color),
        ref_pixel_value=color,
    )


def capture_result(color=(0, 0, 255)):
    return CaptureResult(
        position=(50, 60),
        capture_size=(5, 5),
        image=Image.new("RGB", (5, 5), color),
        pixel=(3, 3),
        color=color,
    )


class FakeView:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.errors: list[str] = []
        self.statuses: list[str] = []
        self.pending_commit: Callable[[], None] | None = None

    def on_opened(self):
        self.calls.append(("opened", None))

    def on_events_changed(self, select):
        self.calls.append(("events", select))

    def on_catalog_changed(self):
        self.calls.append(("catalog", None))

    def on_save_state_changed(self):
        self.calls.append(("save", None))

    def on_status(self, text):
        self.statuses.append(text)

    def show_error(self, message):
        self.errors.append(message)

    def commit_pending_edits(self):
        if self.pending_commit is not None:
            self.pending_commit()


class FakeScheduler:
    def __init__(self):
        self.pending: list[tuple[int, Callable[[], object]]] = []

    def __call__(self, delay, action):
        entry = (delay, action)
        self.pending.append(entry)

        def cancel():
            if entry in self.pending:
                self.pending.remove(entry)

        return cancel

    def fire(self):
        due, self.pending = self.pending, []
        for _delay, action in due:
            action()


class ModelCase(unittest.TestCase):
    def setUp(self):
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profiles_dir = self.dir / "profiles"
        self.run_sets_path = self.dir / "run_sets.json"
        self.running = False
        self.catalog_events: list[str | None] = []
        self.renamed_sets: list[tuple[str, str]] = []

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, events=(), *, name="P", **profile):
        save_profile(
            self.profiles_dir,
            ProfileModel(name=name, event_list=list(events), **profile),
            name=name,
        )
        self.view = FakeView()
        self.scheduler = FakeScheduler()
        model = WorkspaceModel(
            self.view,
            profiles_dir=self.profiles_dir,
            run_sets_path=self.run_sets_path,
            scheduler=self.scheduler,
            running_getter=lambda: self.running,
            on_catalog_changed=self.catalog_events.append,
            on_run_set_renamed=lambda a, b: self.renamed_sets.append((a, b)),
        )
        self.assertTrue(model.open_profile(name))
        return model

    def names(self, model):
        return [e.event_name for e in model.profile.event_list]

    def saved(self, name="P"):
        return load_profile(self.profiles_dir, name, migrate=False).event_list


class TestUndoTargets(ModelCase):
    """정책 6: 삭제·순서·일괄·그룹·캡처 지우기/다시 캡처는 되돌릴 수 있다."""

    def test_delete_strips_references_and_undo_restores_them(self):
        model = self.make([signal("A"), rule("B", conditions={"A": True})])
        a = model.profile.event_list[0]

        model.delete_events([a])

        self.assertEqual(self.names(model), ["B"])
        self.assertEqual(model.profile.event_list[0].conditions, {})
        self.assertEqual(model.undo_label, "delete")
        self.assertTrue(model.undo())
        self.assertEqual(self.names(model), ["A", "B"])
        self.assertEqual(model.profile.event_list[1].conditions, {"A": True})
        self.assertEqual(self.view.calls[-1][0], "save")  # undo autosaves too
        self.assertIn(("events", []), self.view.calls)

    def test_delete_keeps_reference_when_same_name_remains(self):
        model = self.make()
        a1, a2, b = rule("A"), rule("A"), rule("B", conditions={"A": True})
        model.profile.event_list[:] = [a1, a2, b]

        model.delete_events([a1])

        self.assertEqual(b.conditions, {"A": True})

    def test_clearing_a_capture_is_undoable(self):
        model = self.make([captured()])
        event = model.profile.event_list[0]
        image = event.held_screenshot

        model.clear_screen(event)

        self.assertIsNone(event.held_screenshot)
        self.assertTrue(model.undo())
        restored = model.profile.event_list[0]
        self.assertIs(restored.held_screenshot, image)
        self.assertEqual(restored.latest_position, (10, 20))

    def test_recapturing_is_undoable(self):
        model = self.make([captured()])
        event = model.profile.event_list[0]
        image = event.held_screenshot

        model.apply_capture_to(event, capture_result())

        self.assertEqual(event.latest_position, (50, 60))
        self.assertTrue(model.undo())
        restored = model.profile.event_list[0]
        self.assertIs(restored.held_screenshot, image)
        self.assertEqual(restored.ref_pixel_value, (255, 0, 0))

    def test_bulk_changes_touch_only_selection_and_undo(self):
        model = self.make([rule("A"), signal("B"), rule("C")])
        a, b, c = model.profile.event_list

        model.bulk("use", False, [a, b])
        model.bulk("toggle", True, [a, b])
        model.bulk("group", "g", [a, b])

        self.assertEqual([e.use_event for e in (a, b, c)], [False, False, True])
        self.assertEqual([e.runtime_toggle_member for e in (a, b, c)], [True, True, False])
        # Groups only apply to rules.
        self.assertEqual([e.group_id for e in (a, b, c)], ["g", None, None])
        model.undo()
        self.assertIsNone(model.profile.event_list[0].group_id)
        self.assertEqual(model.undo_label, "bulk change")

    def test_move_writes_priorities_and_is_undoable(self):
        model = self.make([rule("01", "g", 1), rule("02", "g", 1)])
        a, b = model.profile.event_list

        self.assertTrue(model.move_event(b, a))

        self.assertEqual((b.priority, a.priority), (0, 1))
        self.assertEqual(model.undo_label, "reorder")
        model.undo()
        self.assertEqual([e.priority for e in model.profile.event_list], [1, 1])

    def test_move_across_sections_is_refused(self):
        model = self.make([rule("a", "g"), rule("b", "h"), signal("s")])
        a, b, s = model.profile.event_list

        self.assertFalse(model.move_event(a, b))
        self.assertFalse(model.move_event(s, a))
        self.assertIsNone(model.undo_label)

    def test_reorder_without_change_leaves_no_undo(self):
        model = self.make([rule("01", "g", 0), rule("02", "g", 1)])
        a, b = model.profile.event_list

        self.assertFalse(model.reorder([a, b]))
        self.assertIsNone(model.undo_label)

    def test_sort_by_name_is_undoable(self):
        model = self.make([rule("b", "g", 0), rule("a", "g", 1)])
        b, a = model.profile.event_list

        model.sort_by_name()

        self.assertEqual((a.priority, b.priority), (0, 1))
        model.undo()
        self.assertEqual(
            {e.event_name: e.priority for e in model.profile.event_list}, {"b": 0, "a": 1}
        )

    def test_sort_when_already_sorted_leaves_no_undo(self):
        model = self.make([rule("a", "g", 0), rule("b", "g", 1)])

        model.sort_by_name()

        self.assertIsNone(model.undo_label)
        self.assertEqual(self.view.statuses[-1], "Already in name order.")

    def test_rename_group_and_ungroup(self):
        model = self.make([rule("A", "Old"), rule("B", " Old ")])
        a, b = model.profile.event_list

        model.rename_group("Old", "New")
        self.assertEqual([a.group_id, b.group_id], ["New", "New"])

        model.clear_group("New")
        self.assertEqual([a.group_id, b.group_id], [None, None])
        model.undo()
        self.assertEqual([e.group_id for e in model.profile.event_list], ["New", "New"])

    def test_rename_group_rejects_existing_name(self):
        model = self.make([rule("A", "g"), rule("B", "Other")])

        with self.assertRaises(WorkspaceError):
            model.rename_group("g", "other")

        self.assertEqual(model.profile.event_list[0].group_id, "g")
        self.assertIsNone(model.undo_label)

    def test_single_group_change_is_undoable(self):
        model = self.make([rule("A")])
        event = model.profile.event_list[0]

        model.set_event_group(event, " g ")
        model.set_event_group(event, "g")  # no change, no extra undo step

        self.assertEqual(event.group_id, "g")
        model.undo()
        self.assertIsNone(model.profile.event_list[0].group_id)
        self.assertIsNone(model.undo_label)

    def test_apply_target_is_undoable_and_reports_nothing_to_do(self):
        model = self.make([captured("A"), captured("B")])
        a, _b = model.profile.event_list

        self.assertEqual(model.apply_target(a), 1)
        self.assertEqual(model.undo_label, "apply target")

        lone = self.make([captured("A")], name="Q2")
        self.assertEqual(lone.apply_target(lone.profile.event_list[0]), 0)
        self.assertIsNone(lone.undo_label)

    def test_undo_stack_is_capped(self):
        model = self.make([rule("A")])
        event = model.profile.event_list[0]
        for _ in range(UNDO_LIMIT + 5):
            model.bulk("use", not event.use_event, [event])

        self.assertEqual(len(model._undo), UNDO_LIMIT)

    def test_switching_profiles_clears_undo(self):
        model = self.make([rule("A")])
        model.delete_events(model.profile.event_list[:])
        save_profile(self.profiles_dir, ProfileModel(name="Q2"), name="Q2")

        model.open_profile("Q2")

        self.assertIsNone(model.undo_label)
        self.assertFalse(model.undo())


class TestListActions(ModelCase):
    def test_copy_gets_unique_names_and_is_selected(self):
        model = self.make([rule("A", key_to_enter="1"), rule("A (2)")])

        copies = model.copy_events([model.profile.event_list[0]])

        self.assertEqual(self.names(model), ["A", "A (2)", "A (3)"])
        self.assertEqual(model.profile.event_list[2].key_to_enter, "1")
        self.assertIn(("events", copies), self.view.calls)

    def test_add_rule_uses_a_fresh_name(self):
        model = self.make([rule("Rule")])

        event = model.add_rule()

        self.assertEqual(event.event_name, "Rule (2)")
        self.assertTrue(event.execute_action)
        self.assertEqual(model.undo_label, "add rule")

    def test_add_signal_applies_capture_and_avoids_duplicates(self):
        model = self.make([signal("Signal")])

        event = model.add_signal("Signal", capture_result(), fallback="Signal (2)")

        self.assertEqual(event.event_name, "Signal (2)")
        self.assertFalse(event.execute_action)
        self.assertEqual(event.latest_position, (50, 60))
        self.assertEqual(event.ref_pixel_value, (0, 0, 255))

    def test_copy_to_profile_renames_collisions(self):
        save_profile(self.profiles_dir, ProfileModel(name="T", event_list=[rule("A")]), name="T")
        model = self.make([rule("A"), rule("B", conditions={"A": True})])
        a, b = model.profile.event_list

        model.copy_to_profile("T", [a, b])

        target = self.saved("T")
        self.assertEqual([e.event_name for e in target], ["A", "A (2)", "B"])
        self.assertEqual(target[2].conditions, {"A (2)": True})
        self.assertEqual(a.event_name, "A")  # the source stays untouched
        self.assertIn("1 renamed", self.view.statuses[-1])

    def test_counts_text(self):
        model = self.make([rule("a", key_to_enter="1"), rule("b"), signal("s")])

        self.assertEqual(model.counts_text(), "Rules 2 · Signals 1 · No key 1")


class TestEventEdits(ModelCase):
    def test_rename_event_updates_references(self):
        model = self.make([signal("A"), rule("B", conditions={"A": False})])
        a, b = model.profile.event_list

        self.assertEqual(model.rename_event(a, "  A2 "), "")

        self.assertEqual(a.event_name, "A2")
        self.assertEqual(b.conditions, {"A2": False})

    def test_rename_event_rejects_blank_and_duplicate(self):
        model = self.make([signal("A"), rule("B")])
        a, _b = model.profile.event_list

        self.assertEqual(model.rename_event(a, "  "), "Enter a name.")
        self.assertIn("already exists", model.rename_event(a, "B"))
        self.assertEqual(a.event_name, "A")

    def test_rename_of_event_outside_profile_is_ignored(self):
        """다른 프로필·되돌리기 전 객체의 이름 확정이 지금 프로필을 바꾸지 않는다."""
        model = self.make([signal("A"), rule("B", conditions={"A": True})])
        stale = signal("A")

        self.assertEqual(model.rename_event(stale, "C"), "")

        self.assertEqual(stale.event_name, "A")
        self.assertEqual(model.profile.event_list[1].conditions, {"A": True})

    def test_condition_candidates_list_signals_first_and_mark_cycles(self):
        model = self.make(
            [rule("R", conditions={"S": True}), signal("S"), rule("Q", conditions={"R": True})]
        )
        r, s, q = model.profile.event_list

        candidates = model.condition_candidates(s)

        self.assertEqual([e.event_name for e, _ in candidates], ["Q", "R"])
        cycles = {e.event_name: cycle for e, cycle in candidates}
        self.assertEqual(cycles["R"], ["R", "S", "R"])
        self.assertIsNotNone(cycles["Q"])
        self.assertIs(model.condition_candidates(r)[0][0], q)

    def test_conditions_add_toggle_remove(self):
        model = self.make([signal("S"), rule("R")])
        _s, r = model.profile.event_list

        model.set_condition(r, "S", True)
        model.set_condition(r, "S", False)
        self.assertEqual(r.conditions, {"S": False})
        model.remove_condition(r, "S")
        self.assertEqual(r.conditions, {})

    def test_timing_validation(self):
        model = self.make([rule("R")])
        event = model.profile.event_list[0]

        self.assertFalse(model.set_event_timing(event, 10, None))
        self.assertIsNone(event.press_duration_ms)
        self.assertTrue(model.set_event_timing(event, 80, 40))
        self.assertEqual((event.press_duration_ms, event.randomization_ms), (80, 40))

    def test_region_mode_clamps_to_capture(self):
        model = self.make([captured()])
        event = model.profile.event_list[0]

        model.set_match_mode(event, "region")
        model.set_region_size(event, 500, 500)

        self.assertEqual(event.match_mode, "region")
        self.assertLessEqual(event.region_size[0], 5)

    def test_runtime_toggle_settings_are_saved(self):
        model = self.make([rule("R", key_to_enter="1", runtime_toggle_member=True)])

        model.set_runtime_toggle(True, "f6")
        self.scheduler.fire()

        saved = load_profile(self.profiles_dir, "P", migrate=False)
        self.assertTrue(saved.runtime_toggle_enabled)
        self.assertEqual(saved.runtime_toggle_key, "F6")

    def test_runtime_toggle_without_members_is_a_save_error(self):
        model = self.make([rule("R", key_to_enter="1")])

        model.set_runtime_toggle(True, "F6")
        self.scheduler.fire()

        self.assertEqual(model.save_state, "error")
        self.assertIn("no selected events", model.save_detail)


class TestAutosave(ModelCase):
    def test_edit_schedules_one_debounced_save(self):
        model = self.make([rule("A", key_to_enter="1")])
        event = model.profile.event_list[0]

        model.set_event_key(event, "2")
        model.set_event_use(event, False)

        self.assertEqual(model.save_state, "saving")
        self.assertEqual(len(self.scheduler.pending), 1)
        self.assertEqual(self.scheduler.pending[0][0], AUTOSAVE_DELAY_MS)
        self.assertEqual(self.saved()[0].key_to_enter, "1")
        self.scheduler.fire()
        self.assertEqual(model.save_state, "saved")
        self.assertEqual(self.saved()[0].key_to_enter, "2")
        self.assertFalse(self.saved()[0].use_event)
        self.assertEqual(self.catalog_events[-1], None)

    def test_incomplete_events_are_saved(self):
        """정책 7: 키나 화면이 빠진 이벤트도 저장한다."""
        model = self.make()

        model.add_rule()
        self.scheduler.fire()

        saved = self.saved()
        self.assertEqual([e.event_name for e in saved], ["Rule"])
        self.assertIsNone(saved[0].key_to_enter)

    def test_duplicate_names_are_not_saved(self):
        model = self.make()
        model.profile.event_list[:] = [rule("A"), rule("A")]

        model.set_event_key(model.profile.event_list[0], "1")
        self.scheduler.fire()

        self.assertEqual(model.save_state, "error")
        self.assertEqual(self.saved(), [])

    def test_unchanged_profile_is_not_rewritten(self):
        model = self.make([rule("A")])
        path = self.profiles_dir / "P.json"
        before = path.stat().st_mtime_ns
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        marker = path.stat().st_mtime_ns

        model.set_event_key(model.profile.event_list[0], None)  # no change
        self.assertTrue(model.flush())

        self.assertGreaterEqual(marker, before)
        self.assertEqual(path.stat().st_mtime_ns, marker)

    def test_flush_commits_pending_edits_first(self):
        model = self.make([rule("A")])
        event = model.profile.event_list[0]
        self.view.pending_commit = lambda: model.rename_event(event, "Typed")

        self.assertTrue(model.flush())

        self.assertEqual(self.saved()[0].event_name, "Typed")
        self.assertEqual(self.scheduler.pending, [])

    def test_switching_profiles_flushes_pending_edits(self):
        model = self.make([rule("A")])
        model.set_event_use(model.profile.event_list[0], False)

        self.assertTrue(model.open_profile("Quick"))

        self.assertFalse(self.saved()[0].use_event)
        self.assertEqual(model.prof_name, "Quick")

    def test_failed_flush_keeps_the_profile_open_and_reports(self):
        model = self.make()
        model.profile.event_list[:] = [rule("A"), rule("A")]

        self.assertFalse(model.open_profile("Quick"))
        self.assertFalse(model.close())

        self.assertEqual(model.prof_name, "P")
        self.assertEqual(len(self.view.errors), 2)

    def test_header_rename_moves_file_and_run_set_membership(self):
        upsert_run_set("Raid", ["P", "Quick"], self.run_sets_path)
        model = self.make()

        model.set_profile_name("P2")
        model.set_favorite(True)
        self.scheduler.fire()

        self.assertFalse((self.profiles_dir / "P.json").exists())
        self.assertTrue((self.profiles_dir / "P2.json").exists())
        self.assertEqual(get_run_set("Raid", self.run_sets_path), ["P2", "Quick"])
        self.assertEqual(self.catalog_events[-1], "P2")
        self.assertTrue(load_profile(self.profiles_dir, "P2").favorite)
        self.assertEqual(model.prof_name, "P2")

    def test_header_rename_is_blocked_while_running(self):
        model = self.make()
        self.running = True

        model.set_profile_name("P2")
        self.scheduler.fire()

        self.assertEqual(model.save_state, "error")
        self.assertTrue((self.profiles_dir / "P.json").exists())
        self.assertTrue(model.name_locked)

    def test_blank_header_name_keeps_old_name_until_flush(self):
        model = self.make([rule("A")])

        model.set_profile_name("  ")
        self.scheduler.fire()
        self.assertEqual(model.save_state, "saved")

        self.assertFalse(model.flush())
        self.assertIn("Enter profile name", self.view.errors[-1])

    def test_profile_name_problem(self):
        save_profile(self.profiles_dir, ProfileModel(name="Other"), name="Other")
        model = self.make()

        self.assertEqual(model.profile_name_problem(""), "Enter profile name")
        self.assertIn("already exists", model.profile_name_problem("Other"))
        self.assertEqual(model.profile_name_problem("P"), "")


class TestCatalog(ModelCase):
    def test_quick_cannot_be_renamed_or_deleted(self):
        """정책 4."""
        model = self.make(name="Quick")

        self.assertTrue(model.name_locked)
        with self.assertRaises(WorkspaceError):
            model.rename_profile("Quick", "Q2")
        with self.assertRaises(WorkspaceError):
            model.delete_profile("Quick")
        model.set_profile_name("Q2")
        self.scheduler.fire()
        self.assertEqual(model.save_state, "error")
        self.assertIn("Quick", list_profile_names(self.profiles_dir))

    def test_rename_and_delete_are_blocked_while_running(self):
        save_profile(self.profiles_dir, ProfileModel(name="X"), name="X")
        upsert_run_set("Raid", ["X"], self.run_sets_path)
        model = self.make()
        self.running = True

        for action in (
            lambda: model.rename_profile("X", "Y"),
            lambda: model.delete_profile("X"),
            lambda: model.rename_run_set_item("Raid", "R2"),
            lambda: model.delete_run_set_item("Raid"),
        ):
            with self.assertRaises(WorkspaceError):
                action()
        self.assertIn("X", list_profile_names(self.profiles_dir))
        self.assertEqual(list_run_set_names(self.run_sets_path), ["Raid"])

    def test_copy_rename_delete_other_profile(self):
        save_profile(self.profiles_dir, ProfileModel(name="X"), name="X")
        upsert_run_set("Raid", ["X"], self.run_sets_path)
        model = self.make()

        dst = model.copy_profile_item("X")
        self.assertEqual(dst, "X - Copy")
        model.rename_profile("X - Copy", "Y")
        self.assertIn("Y", list_profile_names(self.profiles_dir))
        self.assertEqual(self.catalog_events[-1], "Y")
        model.rename_profile("X", "X2")
        self.assertEqual(get_run_set("Raid", self.run_sets_path), ["X2"])
        model.delete_profile("Y")
        self.assertNotIn("Y", list_profile_names(self.profiles_dir))
        with self.assertRaises(WorkspaceError):
            model.rename_profile("X2", "P")

    def test_rename_current_profile_from_sidebar(self):
        model = self.make([rule("A")])

        model.rename_profile("P", "P3")

        self.assertEqual(model.prof_name, "P3")
        self.assertTrue((self.profiles_dir / "P3.json").exists())
        self.assertEqual(model.name_draft, "P3")

    def test_deleting_current_profile_opens_quick(self):
        model = self.make()

        model.delete_profile("P")

        self.assertEqual(model.prof_name, "Quick")
        self.assertNotIn("P", list_profile_names(self.profiles_dir))

    def test_toggle_favorite_of_current_profile_autosaves(self):
        model = self.make()

        model.toggle_favorite("P")
        self.scheduler.fire()

        self.assertTrue(load_profile(self.profiles_dir, "P").favorite)
        self.assertEqual(self.catalog_events[-1], "P")

    def test_new_profile_and_run_set(self):
        model = self.make()

        self.assertEqual(model.default_new_name("profile"), "New profile")
        model.new_profile("Fresh")
        self.assertEqual(model.current_item(), ("profile", "Fresh"))
        with self.assertRaises(WorkspaceError):
            model.new_profile("Fresh")
        model.new_run_set("Set")
        self.assertEqual(model.current_item(), ("run_set", "Set"))
        self.assertEqual(get_run_set("Set", self.run_sets_path), ["Fresh"])

    def test_run_set_members_and_rename_follow(self):
        upsert_run_set("Raid", ["P"], self.run_sets_path)
        model = self.make()
        self.assertTrue(model.open_run_set("Raid"))

        self.assertFalse(model.set_run_set_members([]))
        self.assertTrue(model.set_run_set_members(["Quick", "P"]))
        model.rename_current_run_set("Raid 2")

        self.assertEqual(get_run_set("Raid 2", self.run_sets_path), ["Quick", "P"])
        self.assertEqual(self.renamed_sets, [("Raid", "Raid 2")])
        self.assertEqual(model.current_item(), ("run_set", "Raid 2"))

    def test_deleting_open_run_set_returns_to_profile(self):
        upsert_run_set("Raid", ["P"], self.run_sets_path)
        model = self.make()
        model.open_run_set("Raid")

        model.delete_run_set_item("Raid")

        self.assertEqual(model.current_item(), ("profile", "P"))

    def test_open_item_falls_back_for_missing_targets(self):
        model = self.make()

        model.open_item("run_set", "Nope")
        self.assertEqual(model.current_item(), ("profile", "P"))
        model.open_item("profile", "Nope")
        self.assertEqual(model.current_item(), ("profile", "Quick"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
