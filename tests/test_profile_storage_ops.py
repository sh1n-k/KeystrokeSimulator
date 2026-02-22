import pickle
import tempfile
import unittest
from pathlib import Path

from keystroke_models import EventModel, ProfileModel
from keystroke_profile_storage import (
    copy_profile,
    delete_profile_files,
    ensure_quick_profile,
    list_profile_names,
    load_profile,
    rename_profile_files,
    save_profile,
)


class TestProfileStorageOps(unittest.TestCase):
    def test_list_profile_names_unifies_json_and_pickle_and_keeps_quick_first(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            (prof_dir / "B.pkl").write_bytes(b"legacy")
            (prof_dir / "A.json").write_text("{}", encoding="utf-8")
            (prof_dir / "Quick.pkl").write_bytes(b"legacy")

            self.assertEqual(list_profile_names(prof_dir), ["Quick", "A", "B"])

    def test_ensure_quick_profile_creates_quick_json_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)

            ensure_quick_profile(prof_dir)

            self.assertTrue((prof_dir / "Quick.json").exists())
            quick = load_profile(prof_dir, "Quick", migrate=False)
            self.assertEqual(quick.name, "Quick")
            self.assertIsInstance(quick.modification_keys, dict)
            self.assertTrue(quick.modification_keys["alt"]["enabled"])
            self.assertTrue(quick.modification_keys["alt"]["pass"])

    def test_ensure_quick_profile_migrates_quick_pickle(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            quick = ProfileModel(
                name="Quick",
                event_list=[EventModel(event_name="E1", key_to_enter="A")],
            )
            with open(prof_dir / "Quick.pkl", "wb") as f:
                pickle.dump(quick, f)

            ensure_quick_profile(prof_dir)

            self.assertTrue((prof_dir / "Quick.json").exists())
            migrated = load_profile(prof_dir, "Quick", migrate=False)
            self.assertEqual(len(migrated.event_list), 1)

    def test_copy_profile_creates_new_profile(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            src = ProfileModel(
                name="Src",
                event_list=[EventModel(event_name="A", key_to_enter="F1")],
                favorite=True,
            )
            save_profile(prof_dir, src, name="Src")

            copy_profile(prof_dir, "Src", "Dst")

            copied = load_profile(prof_dir, "Dst", migrate=False)
            self.assertEqual(copied.name, "Dst")
            self.assertTrue(copied.favorite)
            self.assertEqual(len(copied.event_list), 1)

    def test_copy_profile_rejects_existing_destination(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="Src", event_list=[]), name="Src")
            save_profile(prof_dir, ProfileModel(name="Dst", event_list=[]), name="Dst")

            with self.assertRaises(FileExistsError):
                copy_profile(prof_dir, "Src", "Dst")

    def test_rename_profile_files_renames_json_and_removes_old_pickle(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="Old", event_list=[]), name="Old")
            (prof_dir / "Old.pkl").write_bytes(b"legacy")

            rename_profile_files(prof_dir, "Old", "New")

            self.assertFalse((prof_dir / "Old.json").exists())
            self.assertFalse((prof_dir / "Old.pkl").exists())
            self.assertTrue((prof_dir / "New.json").exists())

    def test_rename_profile_files_falls_back_from_pickle(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            old = ProfileModel(
                name="Old",
                event_list=[EventModel(event_name="E1", key_to_enter="A")],
            )
            with open(prof_dir / "Old.pkl", "wb") as f:
                pickle.dump(old, f)

            rename_profile_files(prof_dir, "Old", "New")

            self.assertFalse((prof_dir / "Old.pkl").exists())
            self.assertTrue((prof_dir / "New.json").exists())
            renamed = load_profile(prof_dir, "New", migrate=False)
            self.assertEqual(len(renamed.event_list), 1)

    def test_delete_profile_files_removes_json_and_pickle(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="Del", event_list=[]), name="Del")
            (prof_dir / "Del.pkl").write_bytes(b"legacy")

            delete_profile_files(prof_dir, "Del")

            self.assertFalse((prof_dir / "Del.json").exists())
            self.assertFalse((prof_dir / "Del.pkl").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
