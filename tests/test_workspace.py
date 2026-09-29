"""작업 공간 동작. 대부분은 Tk 없이 stub으로, 창 흐름은 RUN_GUI_TESTS에서."""

import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.models import EventModel, ProfileModel
from app.storage.profile_storage import load_profile, save_profile
from app.storage.run_sets_storage import get_run_set, upsert_run_set
from app.ui import theme
from app.ui.workspace import Workspace, ordered_profile_names
from app.ui.workspace_list import condition_summary, row_badges, section_title
from app.ui.workspace_sidebar import sidebar_actions
from app.core.profile_events import build_event_sections
from app.utils.i18n import set_language

_RUN_GUI_TESTS = os.environ.get("RUN_GUI_TESTS", "0") == "1"


def rule(name, group=None, priority=0, **kwargs):
    return EventModel(event_name=name, group_id=group, priority=priority, **kwargs)


def signal(name, **kwargs):
    return EventModel(event_name=name, execute_action=False, **kwargs)


class WorkspaceStubCase(unittest.TestCase):
    def setUp(self):
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profiles_dir = self.dir / "profiles"
        self.profiles_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, events, *, name="P", selected=()):
        ws = Workspace.__new__(Workspace)
        ws.profile = ProfileModel(name=name, event_list=list(events))
        ws.prof_name = name
        ws.mode = "profile"
        ws.profiles_dir = self.profiles_dir
        ws.run_sets_path = self.dir / "run_sets.json"
        ws._undo = []
        ws.tree = MagicMock()
        ws.tree.selected_events.return_value = list(selected)
        ws.detail = MagicMock()
        ws.win = MagicMock()
        ws.lbl_counts = MagicMock()
        ws.btn_undo = MagicMock()
        ws.lbl_status = MagicMock()
        ws.lbl_save = MagicMock()
        ws.search_var = MagicMock()
        ws._on_changed = MagicMock()
        ws.show_status = MagicMock()
        ws._status_after_id = None
        ws.running_getter = lambda: False
        ws.settings_getter = lambda: None
        ws.on_catalog_changed = MagicMock()
        ws._last_saved_fingerprint = None
        ws.header_frame = MagicMock()
        ws.header_frame.get_data.return_value = (name, False)
        ws.reload_catalog = MagicMock()
        return ws


class TestListActions(WorkspaceStubCase):
    def test_delete_strips_references_and_undo_restores_them(self):
        a, b = signal("A"), rule("B", conditions={"A": True})
        ws = self.make([a, b], selected=[a])

        ws.delete_selected()

        self.assertEqual([e.event_name for e in ws.profile.event_list], ["B"])
        self.assertEqual(ws.profile.event_list[0].conditions, {})
        self.assertTrue(ws.undo())
        self.assertEqual([e.event_name for e in ws.profile.event_list], ["A", "B"])
        self.assertEqual(ws.profile.event_list[1].conditions, {"A": True})

    def test_delete_keeps_reference_when_same_name_remains(self):
        a1, a2, b = rule("A"), rule("A"), rule("B", conditions={"A": True})
        ws = self.make([a1, a2, b], selected=[a1])

        ws.delete_selected()

        self.assertEqual(b.conditions, {"A": True})

    def test_copy_gets_unique_names(self):
        a = rule("A", key_to_enter="1")
        ws = self.make([a, rule("A (2)")], selected=[a])

        ws.copy_selected()

        names = [e.event_name for e in ws.profile.event_list]
        self.assertEqual(names, ["A", "A (2)", "A (3)"])
        self.assertEqual(ws.profile.event_list[2].key_to_enter, "1")

    def test_add_rule_uses_a_fresh_name(self):
        ws = self.make([rule("Rule")])
        ws.detail.entry_name = MagicMock()

        ws.add_rule()

        self.assertEqual(ws.profile.event_list[-1].event_name, "Rule (2)")
        self.assertTrue(ws.profile.event_list[-1].execute_action)

    def test_bulk_changes_touch_only_selection_and_undo(self):
        a, b, c = rule("A"), signal("B"), rule("C")
        ws = self.make([a, b, c], selected=[a, b])

        ws._on_bulk("use", False)
        ws._on_bulk("toggle", True)
        ws._on_bulk("group", "g")

        self.assertEqual([e.use_event for e in (a, b, c)], [False, False, True])
        self.assertEqual([e.runtime_toggle_member for e in (a, b, c)], [True, True, False])
        # Groups only apply to rules.
        self.assertEqual([e.group_id for e in (a, b, c)], ["g", None, None])
        ws.undo()
        self.assertIsNone(ws.profile.event_list[0].group_id)

    def test_reorder_writes_priorities_and_is_undoable(self):
        a, b = rule("01", "g", 1), rule("02", "g", 1)
        ws = self.make([a, b])

        ws._on_reorder([b, a])

        self.assertEqual((b.priority, a.priority), (0, 1))
        self.assertEqual(len(ws._undo), 1)
        ws.undo()
        self.assertEqual([e.priority for e in ws.profile.event_list], [1, 1])

    def test_reorder_without_change_leaves_no_undo(self):
        a, b = rule("01", "g", 0), rule("02", "g", 1)
        ws = self.make([a, b])

        ws._on_reorder([a, b])

        self.assertEqual(ws._undo, [])

    def test_sort_by_name_is_undoable(self):
        a, b = rule("b", "g", 0), rule("a", "g", 1)
        ws = self.make([a, b])

        ws.sort_by_name()

        self.assertEqual((b.priority, a.priority), (0, 1))
        ws.undo()
        self.assertEqual(
            {e.event_name: e.priority for e in ws.profile.event_list}, {"b": 0, "a": 1}
        )

    @patch("app.ui.workspace.simpledialog.askstring", return_value="New")
    def test_rename_group_and_ungroup(self, _ask):
        a, b = rule("A", "Old"), rule("B", " Old ")
        ws = self.make([a, b])

        ws.rename_group("Old")
        self.assertEqual([a.group_id, b.group_id], ["New", "New"])

        ws.clear_group("New")
        self.assertEqual([a.group_id, b.group_id], [None, None])
        ws.undo()
        self.assertEqual(
            [e.group_id for e in ws.profile.event_list], ["New", "New"]
        )

    @patch("app.ui.workspace.messagebox.showerror")
    @patch("app.ui.workspace.simpledialog.askstring", return_value="other")
    def test_rename_group_rejects_existing_name(self, _ask, mock_error):
        a, b = rule("A", "g"), rule("B", "Other")
        ws = self.make([a, b])

        ws.rename_group("g")

        self.assertEqual(a.group_id, "g")
        mock_error.assert_called_once()

    def test_copy_to_profile_renames_collisions(self):
        save_profile(
            self.profiles_dir,
            ProfileModel(name="T", event_list=[rule("A")]),
            name="T",
        )
        a, b = rule("A"), rule("B", conditions={"A": True})
        ws = self.make([a, b], selected=[a, b])

        ws.copy_to_profile("T")

        target = load_profile(self.profiles_dir, "T", migrate=False).event_list
        self.assertEqual([e.event_name for e in target], ["A", "A (2)", "B"])
        self.assertEqual(target[2].conditions, {"A (2)": True})
        self.assertEqual(a.event_name, "A")  # the source stays untouched


class TestSave(WorkspaceStubCase):
    def test_save_writes_profile_and_skips_when_unchanged(self):
        ws = self.make([rule("A", key_to_enter="1")])

        with patch("app.ui.workspace.save_profile", wraps=save_profile) as spy:
            ws._save()
            ws._save()

        self.assertEqual(spy.call_count, 1)
        self.assertTrue((self.profiles_dir / "P.json").exists())

    def test_save_rejects_duplicate_names(self):
        ws = self.make([rule("A"), rule("A")])

        with self.assertRaises(ValueError):
            ws._save()

    def test_rename_moves_file_and_run_set_membership(self):
        save_profile(self.profiles_dir, ProfileModel(name="P", event_list=[]), name="P")
        upsert_run_set("Raid", ["P", "Quick"], self.dir / "run_sets.json")
        ws = self.make([])
        ws.header_frame.get_data.return_value = ("P2", True)

        ws._save()

        self.assertFalse((self.profiles_dir / "P.json").exists())
        self.assertTrue((self.profiles_dir / "P2.json").exists())
        self.assertEqual(get_run_set("Raid", self.dir / "run_sets.json"), ["P2", "Quick"])
        ws.on_catalog_changed.assert_called_with("P2")
        self.assertTrue(load_profile(self.profiles_dir, "P2").favorite)

    def test_rename_is_blocked_while_running(self):
        save_profile(self.profiles_dir, ProfileModel(name="P", event_list=[]), name="P")
        ws = self.make([])
        ws.running_getter = lambda: True
        ws.header_frame.get_data.return_value = ("P2", False)

        with self.assertRaises(ValueError):
            ws._save()
        self.assertTrue((self.profiles_dir / "P.json").exists())

    def test_sidebar_rename_and_delete_are_blocked_while_running(self):
        ws = self.make([])
        ws.running_getter = lambda: True
        ws._error = MagicMock()
        ws._profile_action = MagicMock()

        ws._on_sidebar_action("profile", "delete", "P")

        ws._profile_action.assert_not_called()
        ws._error.assert_called_once()


class TestListPresentation(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_section_titles(self):
        sections = build_event_sections([signal("s"), rule("r", "g"), rule("n")])

        self.assertEqual(
            [section_title(s) for s in sections],
            ["Signals (1)", "Rules · group g (1)", "Rules · no group — all run (1)"],
        )

    def test_condition_summary_marks_off_states_and_truncates(self):
        event = rule("r", conditions={"a": True, "b": False})

        self.assertEqual(condition_summary(event), "a · !b")
        self.assertTrue(condition_summary(event, limit=4).endswith("…"))

    def test_badges(self):
        event = rule("r", runtime_toggle_member=True, use_event=False)

        badges = row_badges(event, referenced=True, toggle_enabled=False)
        self.assertEqual(badges, ["off", "no key", "no trigger", "referenced"])
        self.assertIn("⏻", row_badges(event, referenced=False, toggle_enabled=True))

    def test_quick_cannot_be_renamed_or_deleted(self):
        actions = {a for a, _ in sidebar_actions("profile", "Quick")}

        self.assertNotIn("rename", actions)
        self.assertNotIn("delete", actions)
        self.assertIn("delete", {a for a, _ in sidebar_actions("profile", "X")})

    def test_profile_order_is_quick_favorites_then_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name, fav in (("b", False), ("a", False), ("z", True)):
                save_profile(d, ProfileModel(name=name, event_list=[], favorite=fav), name=name)

            names, favorites = ordered_profile_names(d)

        self.assertEqual(names, ["Quick", "z", "a", "b"])
        self.assertEqual(favorites, {"z"})


@unittest.skipUnless(_RUN_GUI_TESTS, "GUI tests require RUN_GUI_TESTS=1")
class TestWorkspaceWindow(unittest.TestCase):
    def setUp(self):
        set_language("en")
        theme._cached_fonts = None
        self.root = tk.Tk()
        self.root.withdraw()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profiles_dir = self.dir / "profiles"
        save_profile(
            self.profiles_dir,
            ProfileModel(
                name="P",
                event_list=[
                    signal("S"),
                    rule("02 b", "g", 1, key_to_enter="2", conditions={"S": True}),
                    rule("01 a", "g", 1, key_to_enter="1", conditions={"S": True}),
                ],
            ),
            name="P",
        )
        patches = [
            patch("app.ui.workspace.StateUtils.load_main_app_state", return_value={}),
            patch("app.ui.workspace.StateUtils.save_main_app_state"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.running = False
        self.catalog = MagicMock()
        self.ws = Workspace(
            self.root,
            profiles_dir=self.profiles_dir,
            run_sets_path=self.dir / "run_sets.json",
            running_getter=lambda: self.running,
            on_catalog_changed=self.catalog,
            profile="P",
        )
        self.root.update()

    def tearDown(self):
        if self.ws.is_open():
            self.ws.close()
        self.root.destroy()
        self.tmp.cleanup()

    def test_list_shows_sections_in_run_order(self):
        tree = self.ws.tree.tree
        sections = tree.get_children()

        self.assertEqual(
            [tree.item(s, "text") for s in sections], ["Signals (1)", "Rules · group g (2)"]
        )
        rules = [tree.item(i, "text") for i in tree.get_children(sections[1])]
        self.assertEqual(rules, ["⋮⋮ 01 a", "⋮⋮ 02 b"])

    def test_drag_reorder_saves_priority(self):
        tree = self.ws.tree
        first, second = [s for s in tree.sections if s.kind == "group"][0].events

        tree.drop(tree._iid_by_event[id(second)], tree._iid_by_event[id(first)])
        self.assertTrue(self.ws.flush())

        saved = load_profile(self.profiles_dir, "P", migrate=False).event_list
        self.assertEqual({e.event_name: e.priority for e in saved if e.execute_action}, {"02 b": 0, "01 a": 1})

    def test_selecting_a_row_fills_the_detail_panel(self):
        event = self.ws.profile.event_list[1]
        self.ws.tree.select([event])
        self.root.update()

        self.assertIs(self.ws.detail.event, event)
        self.assertEqual(self.ws.detail.name_var.get(), "02 b")
        self.assertEqual(self.ws.detail.key_var.get(), "2")

    def test_running_shows_banner_and_locks_profile_name(self):
        self.ws.set_running(True)
        self.root.update()

        self.assertEqual(self.ws.lbl_running.winfo_manager(), "pack")
        self.assertIn("disabled", self.ws.header_frame.entry.state())

    def test_run_set_members_are_saved(self):
        upsert_run_set("Raid", ["P"], self.dir / "run_sets.json")
        self.ws.reload_catalog()
        self.ws.open_run_set("Raid")
        self.root.update()

        self.ws.run_set_view.vars["Quick"].set(True)
        self.ws.run_set_view._on_toggle()
        self.ws.run_set_view.vars["Quick"].set(False)
        self.ws.run_set_view.vars["P"].set(False)
        self.ws.run_set_view._on_toggle()  # emptying is refused

        data = json.loads((self.dir / "run_sets.json").read_text(encoding="utf-8"))
        self.assertEqual(data["sets"][0]["profiles"], ["Quick", "P"])

    def test_switching_profiles_flushes_pending_edits(self):
        self.ws.profile.event_list[0].use_event = False
        self.ws._on_changed()
        self.ws.open_profile("Quick")
        self.root.update()

        saved = load_profile(self.profiles_dir, "P", migrate=False).event_list
        self.assertFalse(saved[0].use_event)
        self.assertEqual(self.ws.prof_name, "Quick")


if __name__ == "__main__":
    unittest.main(verbosity=2)
