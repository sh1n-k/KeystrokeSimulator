import tempfile
import unittest
from pathlib import Path

from app.presenters.modkeys_form import ModKeysForm
from app.storage.modkey_sets_storage import (
    default_modification_keys,
    get_modkey_set,
    upsert_modkey_set,
)


class TestModKeysForm(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "modkey_sets.json"

    def test_load_missing_set_uses_default_pass(self) -> None:
        form = ModKeysForm.load("Nope", self.path)

        self.assertEqual(form.to_keys(), default_modification_keys())
        self.assertTrue(all(r.pass_through and r.value == "Pass" for r in form.rows))

    def test_load_reads_stored_values(self) -> None:
        upsert_modkey_set(
            "Raid",
            {
                "alt": {"enabled": True, "value": "Q", "pass": False, "include_modifier": False},
                "ctrl": {"enabled": False, "value": "Pass", "pass": True, "include_modifier": True},
                "shift": {"enabled": True, "value": "4", "pass": False, "include_modifier": True},
            },
            self.path,
        )

        form = ModKeysForm.load("Raid", self.path)

        alt, ctrl, shift = form.rows
        self.assertEqual((alt.value, alt.include_modifier, alt.pass_through), ("Q", False, False))
        self.assertEqual((ctrl.enabled, ctrl.pass_through, ctrl.value), (False, True, "Pass"))
        self.assertEqual(shift.value, "4")

    def test_pass_toggle_remembers_previous_value(self) -> None:
        form = ModKeysForm("S", self.path)
        form.capture_key(0, "q")

        form.set_pass(0, True)
        self.assertEqual(form.rows[0].value, "Pass")
        form.set_pass(0, False)
        self.assertEqual(form.rows[0].value, "Q")

    def test_unpassing_a_loaded_pass_row_shows_placeholder(self) -> None:
        form = ModKeysForm.load("Default", self.path)

        form.set_pass(0, False)

        self.assertEqual(form.rows[0].value, "PressKey")

    def test_capture_accepts_only_alnum_and_not_while_passing(self) -> None:
        form = ModKeysForm("S", self.path)
        self.assertTrue(form.capture_key(1, "z"))
        self.assertEqual(form.rows[1].value, "Z")
        for bad in ("[", "F1", "!"):
            self.assertFalse(form.capture_key(1, bad))
        form.set_pass(1, True)
        self.assertFalse(form.capture_key(1, "A"))
        self.assertEqual(form.rows[1].value, "Pass")

    def test_save_writes_set_in_storage_format(self) -> None:
        form = ModKeysForm.load("Raid", self.path)
        form.set_pass(0, False)
        form.capture_key(0, "e")
        form.rows[0].include_modifier = False
        form.rows[2].enabled = False

        form.save()

        stored = get_modkey_set("Raid", self.path)
        self.assertEqual(
            stored["alt"],
            {"enabled": True, "value": "E", "pass": False, "include_modifier": False},
        )
        self.assertEqual(stored["ctrl"], default_modification_keys()["ctrl"])
        self.assertFalse(stored["shift"]["enabled"])


if __name__ == "__main__":
    unittest.main()
