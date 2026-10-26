import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget
from tests.qt_support import qt_app

from app.domain.models import ProfileModel
from app.presenters.run_controller import RunController
from app.storage.profile_storage import save_profile
from app.storage.run_sets_storage import (
    CURRENT_RUN_SET_ID,
    delete_run_set,
    rename_run_set,
    upsert_run_set,
)
from app.ui.main_window import RunWindow
from app.utils.i18n import set_language

class _RefusingWorkspace(QWidget):
    """저장에 실패한 작업 공간처럼 닫기를 거부한다(시그널 종료 때만 닫힌다)."""

    def __init__(self) -> None:
        super().__init__()
        self.quitting = False

    def close_for_quit(self) -> None:
        self.quitting = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.quitting:
            event.accept()
        else:
            event.ignore()


PROCS = [("Game", 4321, None), ("Editor", 77, None)]


class TestRunWindow(unittest.TestCase):
    def setUp(self) -> None:
        qt_app()
        set_language("en")
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        save_profile(Path("profiles"), ProfileModel(name="Rot"))
        upsert_run_set("Raid", ["Rot"], Path("run_sets.json"))
        patches = [
            patch("app.ui.main_window.ProcessCollector.get", return_value=PROCS),
            patch("app.ui.main_window.SoundPlayer", MagicMock),
            patch.object(RunController, "setup_event_handlers"),
            patch.object(RunController, "unbind_events"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.window = RunWindow()

    def tearDown(self) -> None:
        self.window._closing = True
        self.window.deleteLater()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_processes_are_sorted_with_pid(self) -> None:
        items = [
            self.window.process_combo.itemText(i)
            for i in range(self.window.process_combo.count())
        ]
        self.assertEqual(items, ["Editor (77)", "Game (4321)"])

    def test_profile_target_maps_to_profile_selection(self) -> None:
        self.assertTrue(self.window.set_target("profile", "Rot"))

        sel = self.window.selection()

        self.assertEqual(sel.profile, "Rot")
        self.assertEqual(sel.run_set, CURRENT_RUN_SET_ID)

    def test_run_set_target_maps_to_run_set_selection(self) -> None:
        self.assertTrue(self.window.set_target("run_set", "Raid"))

        sel = self.window.selection()

        self.assertEqual(sel.run_set, "Raid")
        self.assertEqual(self.window.run.run_profile_names(), ["Rot"])

    def test_targets_list_profiles_separator_then_sets(self) -> None:
        combo = self.window.target_combo
        data = [combo.itemData(i) for i in range(combo.count())]
        self.assertEqual(data[0], ("profile", "Quick"))
        self.assertIn(("profile", "Rot"), data)
        self.assertEqual(data[-1], ("run_set", "Raid"))
        self.assertIsNone(data[-2])  # separator

    def test_running_locks_selectors_but_not_workspace(self) -> None:
        self.window.run.is_running = True

        self.window.update_ui()

        self.assertFalse(self.window.process_combo.isEnabled())
        self.assertFalse(self.window.target_combo.isEnabled())
        self.assertFalse(self.window.modkey_combo.isEnabled())
        self.assertTrue(self.window.edit_button.isEnabled())
        self.assertTrue(self.window.run_button.isEnabled())
        self.assertIn("Stop", self.window.run_button.text())

    def test_blocked_status_shows_one_fix_button(self) -> None:
        self.window.run.readiness = MagicMock(  # type: ignore[method-assign]
            return_value={
                "can_start": False,
                "badge_text": "Select Process",
                "title": "t",
                "detail": "d",
                "tone": "warn",
                "action": "process",
            }
        )

        self.window.update_ui()

        self.assertFalse(self.window.btn_status_fix.isHidden())
        self.assertEqual(self.window.btn_status_fix.text(), "Refresh")
        self.assertFalse(self.window.run_button.isEnabled())

    def test_close_shuts_the_controller_down(self) -> None:
        with patch.object(self.window.run, "shutdown") as shutdown:
            self.window.close()

        shutdown.assert_called_once()

    def test_tools_menu_disables_idle_only_entries_while_running(self) -> None:
        self.window.run.is_running = True
        self.window.update_ui()

        states = {
            a.objectName(): a.isEnabled()
            for a in self.window.tools_menu.actions()
            if not a.isSeparator()
        }

        self.assertTrue(states["workspace"])
        self.assertFalse(states["settings"])
        self.assertFalse(states["quick"])


    def _write_logs(self) -> tuple[Path, Path]:
        log_dir = Path("logs")
        log_dir.mkdir()
        old = log_dir / "old.log"
        old.write_text("data", encoding="utf-8")
        keep = log_dir / "keysym.log"
        keep.write_text("keep", encoding="utf-8")
        return old, keep

    def test_clear_local_logs_cancel_keeps_files(self) -> None:
        old, keep = self._write_logs()
        with patch(
            "app.ui.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Cancel,
        ):
            self.window.clear_local_logs()

        self.assertTrue(old.exists())
        self.assertTrue(keep.exists())

    def test_clear_local_logs_ok_keeps_keysym_log(self) -> None:
        old, keep = self._write_logs()
        with patch(
            "app.ui.main_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Ok,
        ):
            self.window.clear_local_logs()

        self.assertFalse(old.exists())
        self.assertTrue(keep.exists())
        self.assertIn("1", self.window.lbl_run_status.text())


    def test_run_set_selection_keeps_last_profile(self) -> None:
        self.window.set_target("profile", "Rot")
        self.window.set_target("run_set", "Raid")

        sel = self.window.selection()

        self.assertEqual((sel.profile, sel.run_set), ("Rot", "Raid"))

    def test_offscreen_main_pos_is_centered(self) -> None:
        with patch(
            "app.ui.main_window.StateUtils.load_main_app_state",
            return_value={"main_pos": "-9000/-9000"},
        ):
            window = RunWindow()
        self.addCleanup(window.deleteLater)
        window._closing = True

        area = QGuiApplication.primaryScreen().availableGeometry()
        self.assertTrue(area.contains(window.frameGeometry().center()))

    def test_close_is_cancelled_when_workspace_refuses(self) -> None:
        workspace = _RefusingWorkspace()
        self.addCleanup(workspace.deleteLater)
        self.window.workspace = workspace
        with patch.object(RunController, "shutdown") as shutdown:
            closed = self.window.close()

        self.assertFalse(closed)
        self.assertFalse(self.window._closing)
        shutdown.assert_not_called()

    def test_signal_quit_closes_even_when_workspace_refuses(self) -> None:
        workspace = _RefusingWorkspace()
        self.addCleanup(workspace.deleteLater)
        self.window.workspace = workspace
        with patch.object(RunController, "shutdown") as shutdown:
            self.window.quit_from_signal()

        self.assertTrue(workspace.quitting)
        self.assertTrue(self.window._closing)
        shutdown.assert_called_once()


    def test_renamed_run_set_stays_selected(self) -> None:
        self.window.set_target("run_set", "Raid")
        rename_run_set("Raid", "Boss", Path("run_sets.json"))

        self.window.follow_renamed_run_set("Raid", "Boss")

        self.assertEqual(self.window.target(), ("run_set", "Boss"))

    def test_deleted_run_set_falls_back_to_last_profile(self) -> None:
        self.window.set_target("profile", "Rot")
        self.window.set_target("run_set", "Raid")
        delete_run_set("Raid", Path("run_sets.json"))

        self.window.reload_targets()

        self.assertEqual(self.window.target(), ("profile", "Rot"))

    def test_renamed_profile_follows_new_name(self) -> None:
        self.window.set_target("profile", "Rot")
        Path("profiles/Rot.json").rename(Path("profiles/Rot2.json"))

        self.window.reload_targets("Rot2")

        self.assertEqual(self.window.target(), ("profile", "Rot2"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
