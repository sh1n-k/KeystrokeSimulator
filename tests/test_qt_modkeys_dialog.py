import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.qt_support import qt_app

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QWidget

from app.storage.modkey_sets_storage import (
    default_modification_keys,
    get_modkey_set,
    list_modkey_set_names,
    upsert_modkey_set,
)
from app.ui.modkeys_dialog import ModKeysDialog, edit_modkey_set
from app.utils.i18n import set_language


class TestModKeysDialog(unittest.TestCase):
    def setUp(self) -> None:
        qt_app()
        set_language("en")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "modkey_sets.json"
        self.parent = QWidget()
        self.addCleanup(self.parent.deleteLater)

    def make(self, name: str = "Default") -> ModKeysDialog:
        dialog = ModKeysDialog(self.parent, name, self.path)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_loads_default_pass_rows_locked(self) -> None:
        dialog = self.make()

        for row in dialog.rows:
            self.assertTrue(row.pass_check.isChecked())
            self.assertFalse(row.key.isEnabled())
            self.assertFalse(row.include_check.isEnabled())
            self.assertEqual(row.key.text(), "Pass")
        self.assertFalse(
            bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        )

    def test_unpass_capture_and_save(self) -> None:
        dialog = self.make("Raid")
        alt = dialog.rows[0]

        alt.pass_check.setChecked(False)
        self.assertTrue(alt.key.isEnabled())
        QTest.keyClick(alt.key, Qt.Key.Key_E)
        QTest.keyClick(alt.key, Qt.Key.Key_BracketLeft)  # ignored
        alt.include_check.setChecked(False)
        dialog.rows[2].enabled.setChecked(False)
        dialog.save_button.click()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        stored = get_modkey_set("Raid", self.path)
        self.assertEqual(
            stored["alt"],
            {"enabled": True, "value": "E", "pass": False, "include_modifier": False},
        )
        self.assertEqual(stored["ctrl"], default_modification_keys()["ctrl"])
        self.assertFalse(stored["shift"]["enabled"])

    def test_enter_saves_from_key_field(self) -> None:
        upsert_modkey_set(
            "Raid",
            {
                "alt": {"enabled": True, "value": "Q", "pass": False, "include_modifier": True},
            },
            self.path,
        )
        dialog = self.make("Raid")
        dialog.show()
        self.assertEqual(dialog.rows[0].key.text(), "Q")

        QTest.keyClick(dialog.rows[0].key, Qt.Key.Key_7)
        QTest.keyClick(dialog.rows[0].key, Qt.Key.Key_Return)

        self.assertFalse(dialog.isVisible())
        self.assertEqual(get_modkey_set("Raid", self.path)["alt"]["value"], "7")

    def test_escape_closes_without_saving(self) -> None:
        dialog = self.make("Raid")
        dialog.show()
        dialog.rows[0].pass_check.setChecked(False)

        QTest.keyClick(dialog, Qt.Key.Key_Escape)

        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertNotIn("Raid", list_modkey_set_names(self.path))

    def test_save_failure_keeps_dialog_open(self) -> None:
        dialog = self.make()
        dialog.show()
        with (
            patch(
                "app.presenters.modkeys_form.upsert_modkey_set",
                side_effect=OSError("disk"),
            ),
            patch("app.ui.modkeys_dialog.QMessageBox.critical") as critical,
        ):
            dialog.save_button.click()

        critical.assert_called_once()
        self.assertTrue(dialog.isVisible())
        dialog.reject()

    def test_edit_modkey_set_runs_modally_and_returns(self) -> None:
        def fake_exec(dialog: ModKeysDialog) -> int:
            self.assertEqual(
                dialog.windowModality(), Qt.WindowModality.ApplicationModal
            )
            dialog.save()
            return int(dialog.result())

        with patch.object(ModKeysDialog, "exec", fake_exec):
            edit_modkey_set(self.parent, "Fresh", self.path)

        self.assertEqual(get_modkey_set("Fresh", self.path), default_modification_keys())


if __name__ == "__main__":
    unittest.main(verbosity=2)
