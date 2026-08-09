import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ui.simulator_app import KeystrokeSimulatorApp


def _make_app_stub() -> KeystrokeSimulatorApp:
    app = KeystrokeSimulatorApp.__new__(KeystrokeSimulatorApp)
    app.lbl_run_status = MagicMock()
    return app


class TestClearLocalLogs(unittest.TestCase):
    @patch("app.ui.simulator_app.ask_confirm", return_value=False)
    def test_cancel_does_not_delete_or_show_followup(self, mock_confirm):
        app = _make_app_stub()
        with tempfile.TemporaryDirectory() as td:
            prev = os.getcwd()
            try:
                os.chdir(td)
                log_dir = Path("logs")
                log_dir.mkdir()
                old = log_dir / "old.log"
                old.write_text("x", encoding="utf-8")
                (log_dir / "keysym.log").write_text("keep", encoding="utf-8")

                KeystrokeSimulatorApp.clear_local_logs(app)

                self.assertTrue(old.exists())
                self.assertTrue((log_dir / "keysym.log").exists())
            finally:
                os.chdir(prev)
        mock_confirm.assert_called_once()

    @patch("app.ui.simulator_app.ask_confirm", return_value=True)
    @patch("app.ui.simulator_app.messagebox")
    def test_ok_deletes_old_logs_without_second_dialog(
        self, mock_messagebox, mock_confirm
    ):
        app = _make_app_stub()
        with tempfile.TemporaryDirectory() as td:
            prev = os.getcwd()
            try:
                os.chdir(td)
                log_dir = Path("logs")
                log_dir.mkdir()
                old = log_dir / "old.log"
                old.write_text("data", encoding="utf-8")
                keep = log_dir / "keysym.log"
                keep.write_text("keep", encoding="utf-8")

                KeystrokeSimulatorApp.clear_local_logs(app)

                self.assertFalse(old.exists())
                self.assertTrue(keep.exists())
            finally:
                os.chdir(prev)
        mock_confirm.assert_called_once()
        mock_messagebox.showinfo.assert_not_called()
        mock_messagebox.askokcancel.assert_not_called()
        app.lbl_run_status.config.assert_called()


class TestAskConfirmDialog(unittest.TestCase):
    def test_ask_confirm_returns_false_on_cancel(self):
        import tkinter as tk

        from app.ui.dialogs import ConfirmDialog

        root = tk.Tk()
        root.withdraw()
        try:
            # Drive cancel path by overriding wait to immediately cancel.
            original_init = ConfirmDialog.__init__

            def auto_cancel_init(self, master, **kwargs):
                original_init(self, master, **kwargs)

            # Create dialog without waiting: call constructor pieces manually.
            dialog = ConfirmDialog.__new__(ConfirmDialog)
            dialog.result = False
            dialog.destroy = MagicMock()
            ConfirmDialog._on_cancel(dialog)
            self.assertFalse(dialog.result)
            dialog.destroy.assert_called_once()
        finally:
            root.destroy()

    def test_ask_confirm_ok_sets_result_true(self):
        from app.ui.dialogs import ConfirmDialog

        dialog = ConfirmDialog.__new__(ConfirmDialog)
        dialog.result = False
        dialog.destroy = MagicMock()
        ConfirmDialog._on_ok(dialog)
        self.assertTrue(dialog.result)
        dialog.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
