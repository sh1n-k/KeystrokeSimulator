import tempfile
import unittest
from pathlib import Path

from app.storage.run_sets_storage import (
    CURRENT_RUN_SET_ID,
    copy_run_set,
    delete_run_set,
    get_run_set,
    is_current_run_set,
    list_run_set_names,
    load_run_sets,
    upsert_run_set,
)
from app.ui.main_frames import _ellipsize_display


class TestRunSetsStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "run_sets.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upsert_list_get(self) -> None:
        upsert_run_set("Combat", ["Rot", "Util"], self.path)
        self.assertEqual(list_run_set_names(self.path), ["Combat"])
        self.assertEqual(get_run_set("Combat", self.path), ["Rot", "Util"])

    def test_rejects_empty_members(self) -> None:
        with self.assertRaises(ValueError):
            upsert_run_set("Empty", [], self.path)

    def test_rejects_reserved_current_name(self) -> None:
        with self.assertRaises(ValueError):
            upsert_run_set(CURRENT_RUN_SET_ID, ["Quick"], self.path)

    def test_copy_and_delete(self) -> None:
        upsert_run_set("A", ["Quick"], self.path)
        copy_run_set("A", "B", self.path)
        self.assertEqual(get_run_set("B", self.path), ["Quick"])
        next_id = delete_run_set("A", self.path)
        self.assertEqual(next_id, "B")
        self.assertNotIn("A", list_run_set_names(self.path))
        next_id = delete_run_set("B", self.path)
        self.assertEqual(next_id, CURRENT_RUN_SET_ID)
        self.assertEqual(load_run_sets(self.path), {})

    def test_is_current(self) -> None:
        self.assertTrue(is_current_run_set(CURRENT_RUN_SET_ID))
        self.assertFalse(is_current_run_set("Combat"))

    def test_ellipsize_display_keeps_short_names(self) -> None:
        self.assertEqual(_ellipsize_display("short", 18), "short")
        long_name = "a" * 30
        out = _ellipsize_display(long_name, 18)
        self.assertEqual(len(out), 18)
        self.assertTrue(out.endswith("…"))


if __name__ == "__main__":
    unittest.main()
