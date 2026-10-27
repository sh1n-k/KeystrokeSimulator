import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from tests.qt_support import qt_app
from tests.test_capture_controller import FakeCapturer

from app.domain.capture_geometry import CaptureResult
from app.domain.models import EventModel, ProfileModel, UserSettings
from app.storage.profile_storage import load_profile, save_profile
from app.storage.run_sets_storage import get_run_set, upsert_run_set
from app.ui.capture_hud import open_quick_capture
from app.ui.workspace import WorkspaceWindow, open_workspace
from app.utils.i18n import set_language


def rule(name, group=None, priority=0, **kwargs):
    return EventModel(event_name=name, group_id=group, priority=priority, **kwargs)


def signal(name, **kwargs):
    return EventModel(
        event_name=name,
        execute_action=False,
        latest_position=(10, 20),
        clicked_position=(1, 2),
        held_screenshot=Image.new("RGB", (5, 5), (255, 0, 0)),
        ref_pixel_value=(255, 0, 0),
        **kwargs,
    )


class FakeHost(QWidget):
    """`RunWindow`가 작업 공간에 주는 것만 흉내 낸다."""

    def __init__(self) -> None:
        super().__init__()
        self.workspace: QWidget | None = None
        self.profiles_dir = Path("profiles")
        self.run_sets_path = Path("run_sets.json")
        self.run = MagicMock(is_running=False)
        self.settings = UserSettings()
        self.reload_targets = MagicMock()
        self.follow_renamed_run_set = MagicMock()
        self.update_ui = MagicMock()


class WorkspaceWindowCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = qt_app()
        set_language("en")
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        save_profile(
            Path("profiles"),
            ProfileModel(
                name="P",
                event_list=[
                    signal("S"),
                    rule("02 b", "g", 1, key_to_enter="2", conditions={"S": True}),
                    rule("01 a", "g", 1, key_to_enter="1", conditions={"S": True}),
                    rule("loose"),
                ],
            ),
            name="P",
        )
        self.host = FakeHost()
        open_workspace(self.host, kind="profile", name="P")
        self.ws = self.host.workspace
        assert isinstance(self.ws, WorkspaceWindow)

    def tearDown(self) -> None:
        ws = self.ws
        if ws.is_open():
            ws.model.close()
            ws._closed = True
            ws.close()
        self.host.deleteLater()
        self.app.processEvents()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def event(self, name: str) -> EventModel:
        return next(e for e in self.ws.model.profile.event_list if e.event_name == name)

    def saved(self) -> list[EventModel]:
        return load_profile(Path("profiles"), "P", migrate=False).event_list

    def flush(self) -> None:
        self.assertTrue(self.ws.model.flush())


class TestOpening(WorkspaceWindowCase):
    def test_reopening_reuses_the_window_and_selects(self) -> None:
        upsert_run_set("Raid", ["P"], Path("run_sets.json"))
        self.ws.on_catalog_changed()

        open_workspace(self.host, kind="run_set", name="Raid")

        self.assertIs(self.host.workspace, self.ws)
        self.assertEqual(self.ws.model.current_item(), ("run_set", "Raid"))
        self.assertIs(self.ws.center.currentWidget(), self.ws.run_set_view)
        self.assertTrue(self.ws.detail.isHidden())

    def test_sidebar_stays_put_across_items_and_options(self) -> None:
        upsert_run_set("Raid", ["P"], Path("run_sets.json"))
        self.ws.on_catalog_changed()
        self.app.processEvents()
        top = self.ws.sidebar.mapTo(self.ws, self.ws.sidebar.rect().topLeft())

        self.ws._toggle_options()
        self.app.processEvents()
        self.assertEqual(self.ws.sidebar.mapTo(self.ws, self.ws.sidebar.rect().topLeft()), top)

        self.ws.model.open_run_set("Raid")
        self.app.processEvents()
        self.assertEqual(self.ws.sidebar.mapTo(self.ws, self.ws.sidebar.rect().topLeft()), top)
        self.assertTrue(self.ws.header.isHidden())
        self.assertTrue(self.ws.top_bar.isHidden())  # empty row is folded away

        self.ws.set_running(True)
        self.assertFalse(self.ws.top_bar.isHidden())  # running badge still shows
        self.ws.set_running(False)
        self.assertTrue(self.ws.top_bar.isHidden())

        self.ws.model.open_profile("P")
        self.assertFalse(self.ws.top_bar.isHidden())
        self.assertFalse(self.ws.header.isHidden())

    def test_list_shows_sections_in_run_order(self) -> None:
        store = self.ws.tree.store
        heads = [store.item(r, 0).text() for r in range(store.rowCount())]
        self.assertEqual(
            heads, ["Signals (1)", "Rules · group g (2)", "Rules · no group (1)"]
        )
        group = store.item(1, 0)
        names = [group.child(r, 0).text() for r in range(group.rowCount())]
        self.assertEqual(names, ["⋮⋮ 01 a", "⋮⋮ 02 b"])
        loose = store.item(2, 0).child(0, 3).text()
        self.assertIn("no key", loose)

    def test_sidebar_lists_profiles_and_marks_current(self) -> None:
        self.assertEqual(self.ws.sidebar.names("profile"), ["Quick", "P"])
        selected = self.ws.sidebar.tree.selectedItems()
        self.assertEqual(selected[0].text(0), "P")

    def test_selecting_a_row_fills_the_detail_panel(self) -> None:
        event = self.event("02 b")
        self.ws.tree.select([event])

        detail = self.ws.detail
        self.assertIs(detail.current, event)
        self.assertEqual(detail.entry_name.text(), "02 b")
        self.assertEqual(detail.combo_key.currentText(), "2")
        self.assertEqual(detail.combo_group.currentText(), "g")
        self.assertFalse(detail.editor.isHidden())

    def test_multi_selection_shows_bulk_actions(self) -> None:
        self.ws.tree.select([self.event("01 a"), self.event("02 b")])

        self.assertFalse(self.ws.detail.bulk.isHidden())
        self.assertTrue(self.ws.detail.editor.isHidden())
        self.assertEqual(self.ws.detail.lbl_title.text(), "2 selected")


class TestEditing(WorkspaceWindowCase):
    def test_name_edit_autosaves_and_renames_references(self) -> None:
        self.ws.tree.select([self.event("S")])
        self.ws.detail.entry_name.setText("Sig")
        self.ws.detail.commit_name()
        self.assertEqual(self.ws.model.save_state, "saving")

        QTest.qWait(400)

        self.assertEqual(self.ws.model.save_state, "saved")
        saved = {e.event_name: e for e in self.saved()}
        self.assertIn("Sig", saved)
        self.assertEqual(saved["01 a"].conditions, {"Sig": True})
        self.assertTrue(self.ws.lbl_save.text().startswith("Saved"))

    def test_duplicate_name_is_refused_in_place(self) -> None:
        self.ws.tree.select([self.event("S")])
        self.ws.detail.entry_name.setText("loose")
        self.assertFalse(self.ws.detail.commit_name())

        self.assertIn("already exists", self.ws.detail.lbl_name_error.text())
        self.assertEqual(self.event("S").event_name, "S")

    def _refused_rename_then_open_other(self, via_run_set: bool) -> list[EventModel]:
        save_profile(
            Path("profiles"),
            ProfileModel(
                name="Q",
                event_list=[signal("S"), rule("Attack", conditions={"S": True})],
            ),
            name="Q",
        )
        self.ws.tree.select([self.event("S")])
        self.ws.detail.entry_name.setText("loose")
        self.assertFalse(self.ws.detail.commit_name())

        if via_run_set:
            upsert_run_set("Set", ["P"], Path("run_sets.json"))
            self.ws.model.open_run_set("Set")
        self.ws.model.open_profile("Q")
        self.ws.model.flush()
        return load_profile(Path("profiles"), "Q", migrate=False).event_list

    def test_refused_name_is_not_applied_to_the_next_profile(self) -> None:
        saved = self._refused_rename_then_open_other(via_run_set=False)

        self.assertEqual(saved[1].conditions, {"S": True})
        self.assertEqual([e.event_name for e in saved], ["S", "Attack"])

    def test_refused_name_is_not_applied_after_run_set_view(self) -> None:
        saved = self._refused_rename_then_open_other(via_run_set=True)

        self.assertEqual(saved[1].conditions, {"S": True})

    def test_delete_key_then_undo_shortcut(self) -> None:
        self.ws.show()
        self.ws.activateWindow()
        self.assertTrue(QTest.qWaitForWindowActive(self.ws, 1000))
        self.ws.tree.select([self.event("S")])
        self.ws.tree.setFocus()

        QTest.keyClick(self.ws.tree, Qt.Key.Key_Delete)
        self.assertNotIn("S", [e.event_name for e in self.ws.model.profile.event_list])
        self.assertEqual(self.event("01 a").conditions, {})
        self.assertEqual(self.ws.btn_undo.text(), "Undo: delete")

        undo = QKeySequence(QKeySequence.StandardKey.Undo)[0]
        QTest.keyClick(self.ws.tree, undo.key(), undo.keyboardModifiers())

        self.assertEqual(self.event("01 a").conditions, {"S": True})
        self.assertFalse(self.ws.btn_undo.isEnabled())

    def test_drag_drop_reorders_within_section_only(self) -> None:
        first, second = self.event("01 a"), self.event("02 b")

        self.assertTrue(self.ws.tree.drop(second, first))
        self.flush()
        saved = {e.event_name: e.priority for e in self.saved() if e.execute_action}
        self.assertEqual((saved["02 b"], saved["01 a"]), (0, 1))

        self.assertFalse(self.ws.tree.drop(self.event("loose"), first))
        self.assertIn("same section", self.ws.lbl_status.text())

    def test_drop_is_refused_while_searching(self) -> None:
        self.ws.entry_search.setText("0")

        self.assertFalse(self.ws.tree.drop(self.event("02 b"), self.event("01 a")))

    def test_search_filters_rows(self) -> None:
        self.ws.entry_search.setText("loose")

        store = self.ws.tree.store
        self.assertEqual(store.rowCount(), 1)
        self.assertEqual(store.item(0, 0).child(0, 0).text(), "⋮⋮ loose")

    def test_clear_screen_is_undoable(self) -> None:
        event = self.event("S")
        image = event.held_screenshot
        self.ws.tree.select([event])

        self.ws.detail.btn_clear_screen.click()
        self.assertIsNone(event.held_screenshot)
        self.ws.undo()

        self.assertIs(self.event("S").held_screenshot, image)

    def test_capture_button_opens_hud_and_apply_is_undoable(self) -> None:
        event = self.event("S")
        self.ws.tree.select([event])
        with patch("app.ui.capture_hud.CaptureHud") as hud:
            self.ws.detail.btn_capture.click()
        kwargs = hud.call_args.kwargs
        self.assertEqual(kwargs["mode"], "single")
        self.assertEqual(kwargs["name"], "S")
        self.assertIsNotNone(kwargs["initial"])
        self.assertTrue(kwargs["border"])

        kwargs["on_apply"](
            CaptureResult(
                position=(50, 60),
                capture_size=(5, 5),
                image=Image.new("RGB", (5, 5), (0, 0, 255)),
                pixel=(3, 3),
                color=(0, 0, 255),
            )
        )
        self.assertEqual(self.event("S").latest_position, (50, 60))
        self.ws.undo()
        self.assertEqual(self.event("S").latest_position, (10, 20))

    def test_capture_while_running_draws_no_border(self) -> None:
        self.host.run.is_running = True
        self.ws.tree.select([self.event("S")])
        with patch("app.ui.capture_hud.CaptureHud") as hud:
            self.ws.detail.btn_capture.click()

        self.assertFalse(hud.call_args.kwargs["border"])

    def test_new_signal_comes_from_the_hud(self) -> None:
        self.host.run.is_running = True
        with patch("app.ui.capture_hud.CaptureHud") as hud:
            self.ws.btn_add_signal.click()
        kwargs = hud.call_args.kwargs
        self.assertFalse(kwargs["border"])  # no border while running
        kwargs["on_name_change"]("Buff")
        kwargs["on_apply"](
            CaptureResult(
                position=(1, 1),
                capture_size=(5, 5),
                image=Image.new("RGB", (5, 5)),
                pixel=(0, 0),
                color=(0, 0, 0),
            )
        )

        added = self.event("Buff")
        self.assertFalse(added.execute_action)
        self.assertEqual(self.ws.tree.selected_events(), [added])

    def test_add_rule_selects_it_and_saves_incomplete(self) -> None:
        self.ws.btn_add_rule.click()
        self.flush()

        self.assertEqual(self.ws.detail.entry_name.text(), "Rule")
        self.assertIn("Rule", [e.event_name for e in self.saved()])
        self.assertIn("No key 2", self.ws.lbl_counts.text())

    def test_bulk_turn_off(self) -> None:
        a, b = self.event("01 a"), self.event("02 b")
        self.ws.tree.select([a, b])

        self.ws.detail.bulk_buttons[1].click()

        self.assertEqual([a.use_event, b.use_event], [False, False])
        self.assertEqual(self.ws.tree.selected_events(), [a, b])

    def test_condition_menu_marks_cycles(self) -> None:
        self.ws.tree.select([self.event("S")])
        self.ws.detail._fill_condition_menu()

        actions = [a for a in self.ws.detail.cond_menu.actions() if not a.isSeparator()]
        texts = {a.text(): a.isEnabled() for a in actions}
        self.assertFalse(texts["01 a — circular: S → 01 a → S"])
        self.assertTrue(texts["loose"])


class TestRunningAndClosing(WorkspaceWindowCase):
    def test_running_shows_banner_and_locks_profile_name(self) -> None:
        self.host.run.is_running = True
        self.ws.set_running(True)

        self.assertFalse(self.ws.lbl_running.isHidden())
        self.assertFalse(self.ws.header.entry.isEnabled())
        self.ws.set_running(False)
        self.host.run.is_running = False
        self.ws.set_running(False)
        self.assertTrue(self.ws.lbl_running.isHidden())
        self.assertTrue(self.ws.header.entry.isEnabled())

    def test_quick_name_is_locked(self) -> None:
        self.ws.model.open_profile("Quick")

        self.assertFalse(self.ws.header.entry.isEnabled())

    def test_sidebar_delete_is_refused_while_running(self) -> None:
        self.host.run.is_running = True
        with patch("app.ui.workspace.QMessageBox") as box:
            self.ws._on_sidebar_action("profile", "delete", "P")

        box.warning.assert_called_once()
        box.question.assert_not_called()
        self.assertTrue(Path("profiles/P.json").exists())

    def test_escape_clears_search_first_then_closes(self) -> None:
        self.ws.show()
        self.ws.entry_search.setText("x")
        self.ws.entry_search.setFocus()
        with patch.object(self.ws.entry_search, "hasFocus", return_value=True):
            self.ws._on_escape()
        self.assertEqual(self.ws.entry_search.text(), "")
        self.assertTrue(self.ws.is_open())

        self.ws.model.set_event_use(self.event("S"), False)
        self.assertTrue(self.ws.model.save_pending)
        self.ws._on_escape()

        self.assertFalse(self.ws.is_open())
        self.assertIsNone(self.host.workspace)
        self.host.reload_targets.assert_called_with(None)
        self.assertFalse(self.saved()[0].use_event)  # flushed on close
        state = json.loads(Path("app_state.json").read_text(encoding="utf-8"))
        self.assertIn("workspace_pos", state)
        self.assertIn("workspace_size", state)

    def test_close_is_refused_when_save_fails(self) -> None:
        self.ws.model.profile.event_list.append(rule("loose"))
        with patch("app.ui.workspace.QMessageBox") as box:
            self.ws.close()

        box.warning.assert_called_once()
        self.assertTrue(self.ws.is_open())
        self.ws.model.profile.event_list.pop()

    def test_close_for_quit_closes_without_dialog_when_save_fails(self) -> None:
        self.ws.model.profile.event_list.append(rule("loose"))
        with patch("app.ui.workspace.QMessageBox") as box:
            self.ws.close_for_quit()

        box.warning.assert_not_called()
        self.assertFalse(self.ws.is_open())
        self.assertIsNone(self.host.workspace)


class TestRunSetsAndOptions(WorkspaceWindowCase):
    def test_run_set_members_are_saved_and_emptying_is_refused(self) -> None:
        upsert_run_set("Raid", ["P"], Path("run_sets.json"))
        self.ws.on_catalog_changed()
        self.ws.model.open_run_set("Raid")
        view = self.ws.run_set_view

        view.checks["Quick"].setChecked(True)
        view.checks["Quick"].setChecked(False)
        view.checks["P"].setChecked(False)  # emptying is refused and reverted

        self.assertTrue(view.checks["P"].isChecked())
        self.assertEqual(get_run_set("Raid", Path("run_sets.json")), ["P"])
        self.assertIn("at least one", view.lbl_error.text())

    def test_profile_rename_while_editing_set_keeps_new_name(self) -> None:
        save_profile(Path("profiles"), ProfileModel(name="B"), name="B")
        upsert_run_set("Raid", ["P", "B"], Path("run_sets.json"))
        self.ws.model.open_run_set("Raid")

        self.ws.model.rename_profile("B", "C")
        self.ws.run_set_view.checks["Quick"].setChecked(True)

        saved = get_run_set("Raid", Path("run_sets.json"))
        self.assertEqual(sorted(saved), ["C", "P", "Quick"])

    def test_quick_capture_goes_into_open_quick_and_survives_autosave(self) -> None:
        save_profile(Path("profiles"), ProfileModel(name="Quick", event_list=[rule("1")]))
        self.assertTrue(self.ws.model.open_profile("Quick"))
        self.host.quick_hud = None  # type: ignore[attr-defined]
        with patch("app.engine.capture_session.ScreenshotCapturer", FakeCapturer):
            open_quick_capture(self.host)
        hud = self.host.quick_hud  # type: ignore[attr-defined]
        self.addCleanup(hud.close)
        result = CaptureResult(
            position=(5, 6),
            capture_size=(5, 5),
            image=Image.new("RGB", (5, 5), (0, 0, 255)),
            pixel=(1, 1),
            color=(0, 0, 255),
        )

        name = hud.controller.append_quick(result)
        self.ws.model.add_rule()  # 그 뒤 작업 공간에서 편집한다.
        self.assertTrue(self.ws.model.flush())

        saved = load_profile(Path("profiles"), "Quick", migrate=False).event_list
        self.assertEqual(name, "2")
        self.assertIn("2", [e.event_name for e in saved])
        self.assertEqual(self.ws.model.undo_label, "add rule")

    def test_run_set_rename_follows_in_main_window(self) -> None:
        upsert_run_set("Raid", ["P"], Path("run_sets.json"))
        self.ws.on_catalog_changed()
        self.ws.model.open_run_set("Raid")

        self.ws.run_set_view.entry_name.setText("Raid 2")
        self.ws.run_set_view._commit_name()

        self.host.follow_renamed_run_set.assert_called_with("Raid", "Raid 2")
        self.assertEqual(self.ws.sidebar.names("run_set"), ["Raid 2"])

    def test_runtime_toggle_capture_and_member_checkbox(self) -> None:
        box = self.ws.toggle_box
        box.chk_enabled.setChecked(True)
        self.assertTrue(self.ws.model.profile.runtime_toggle_enabled)
        self.assertIn("on", self.ws.btn_options.text())

        box.start_capture()
        self.assertTrue(box.capturing)
        box.handle_wheel(120)
        self.assertFalse(box.capturing)
        self.assertEqual(self.ws.model.profile.runtime_toggle_key, "W_UP")

        self.ws.tree.select([self.event("01 a")])
        self.assertFalse(self.ws.detail.chk_toggle.isHidden())
        self.ws.detail.chk_toggle.setChecked(True)
        self.flush()
        saved = load_profile(Path("profiles"), "P", migrate=False)
        self.assertTrue(saved.runtime_toggle_enabled)
        self.assertTrue(next(e for e in saved.event_list if e.event_name == "01 a").runtime_toggle_member)

    def test_graph_tab_renders_png(self) -> None:
        self.ws.tabs.setCurrentWidget(self.ws.graph)

        pixmap = self.ws.graph.label.pixmap()
        self.assertFalse(pixmap.isNull())


if __name__ == "__main__":
    unittest.main(verbosity=2)

