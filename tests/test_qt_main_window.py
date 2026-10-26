import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox
from tests.qt_support import qt_app

from app.domain.models import ProfileModel
from app.presenters.run_controller import RunController
from app.storage.profile_storage import save_profile
from app.storage.run_sets_storage import CURRENT_RUN_SET_ID, upsert_run_set
from app.ui.main_window import RunWindow
from app.utils.i18n import set_language

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
