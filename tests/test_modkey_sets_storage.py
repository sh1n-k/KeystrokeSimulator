import tempfile
import unittest
from pathlib import Path

from app.storage.modkey_sets_storage import (
    DEFAULT_MODKEY_SET_NAME,
    coerce_modification_keys,
    copy_modkey_set,
    default_modification_keys,
    delete_modkey_set,
    get_modkey_set,
    list_modkey_set_names,
    load_modkey_sets,
    save_modkey_sets,
    upsert_modkey_set,
)


class TestModKeySetsStorage(unittest.TestCase):
    def test_load_creates_default_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "modkey_sets.json"
            catalog = load_modkey_sets(path)
            self.assertIn(DEFAULT_MODKEY_SET_NAME, catalog)
            self.assertTrue(path.exists())
            self.assertEqual(
                catalog[DEFAULT_MODKEY_SET_NAME], default_modification_keys()
            )

    def test_upsert_copy_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "modkey_sets.json"
            load_modkey_sets(path)
            keys = default_modification_keys()
            keys["alt"] = {"enabled": True, "value": "Q", "pass": False}
            upsert_modkey_set("Combat", keys, path)
            self.assertEqual(get_modkey_set("Combat", path)["alt"]["value"], "Q")
            copy_modkey_set("Combat", "Combat - Copied", path)
            self.assertIn("Combat - Copied", list_modkey_set_names(path))
            next_sel = delete_modkey_set("Combat", path)
            self.assertNotIn("Combat", list_modkey_set_names(path))
            self.assertIsNotNone(next_sel)

    def test_cannot_delete_last_set(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "modkey_sets.json"
            load_modkey_sets(path)
            with self.assertRaises(ValueError):
                delete_modkey_set(DEFAULT_MODKEY_SET_NAME, path)

    def test_save_load_preserves_order_default_first(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "modkey_sets.json"
            catalog = {
                "Zebra": default_modification_keys(),
                DEFAULT_MODKEY_SET_NAME: default_modification_keys(),
                "Alpha": default_modification_keys(),
            }
            save_modkey_sets(catalog, path)
            names = list_modkey_set_names(path)
            self.assertEqual(names[0], DEFAULT_MODKEY_SET_NAME)
            self.assertEqual(names[1], "Alpha")

    def test_include_modifier_roundtrip_and_legacy_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "modkey_sets.json"
            keys = default_modification_keys()
            keys["shift"] = {
                "enabled": True,
                "value": "V",
                "pass": False,
                "include_modifier": False,
            }
            upsert_modkey_set("Combat", keys, path)
            loaded = get_modkey_set("Combat", path)
            self.assertFalse(loaded["shift"]["include_modifier"])

            legacy = coerce_modification_keys(
                {
                    "shift": {
                        "enabled": True,
                        "value": "V",
                        "pass": False,
                    }
                }
            )
            self.assertTrue(legacy["shift"]["include_modifier"])


if __name__ == "__main__":
    unittest.main()
