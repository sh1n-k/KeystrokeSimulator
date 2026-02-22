import tempfile
import unittest
from pathlib import Path

from PIL import Image

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


class TestProfileCRUDE2E(unittest.TestCase):
    """프로필 CRUD 전체 사이클 E2E 테스트 (GUI 없음, 순수 I/O)"""

    def test_create_read_update_delete_cycle(self):
        """Create → Read → Update (rename) → Delete 전체 사이클"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)

            # Create
            evt = EventModel(event_name="TestEvt", key_to_enter="A",
                             clicked_position=(10, 20), ref_pixel_value=(1, 2, 3))
            save_profile(prof_dir, ProfileModel(name="TestProf", event_list=[evt]), name="TestProf")
            self.assertIn("TestProf", list_profile_names(prof_dir))

            # Read
            p = load_profile(prof_dir, "TestProf")
            self.assertEqual(p.name, "TestProf")
            self.assertEqual(len(p.event_list), 1)
            self.assertEqual(p.event_list[0].key_to_enter, "A")

            # Update (rename)
            rename_profile_files(prof_dir, "TestProf", "Renamed")
            names = list_profile_names(prof_dir)
            self.assertNotIn("TestProf", names)
            self.assertIn("Renamed", names)

            # Delete
            delete_profile_files(prof_dir, "Renamed")
            self.assertNotIn("Renamed", list_profile_names(prof_dir))

    def test_copy_then_independent_modification(self):
        """프로필 복사 후 독립 수정 확인"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            evt = EventModel(event_name="Original", key_to_enter="1")
            save_profile(prof_dir, ProfileModel(name="Src", event_list=[evt]), name="Src")

            copy_profile(prof_dir, "Src", "Cpy")

            # Modify copy
            cpy = load_profile(prof_dir, "Cpy")
            cpy.event_list[0].event_name = "Modified"
            save_profile(prof_dir, cpy, name="Cpy")

            # Original unchanged
            src = load_profile(prof_dir, "Src")
            self.assertEqual(src.event_list[0].event_name, "Original")
            # Copy modified
            cpy2 = load_profile(prof_dir, "Cpy")
            self.assertEqual(cpy2.event_list[0].event_name, "Modified")

    def test_quick_profile_auto_creation_and_sort(self):
        """Quick 프로필 자동 생성 + 목록 우선 정렬"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="Alpha", event_list=[]), name="Alpha")
            ensure_quick_profile(prof_dir)

            names = list_profile_names(prof_dir)
            self.assertEqual(names[0], "Quick")
            self.assertIn("Alpha", names)

    def test_legacy_pkl_migration_then_crud(self):
        """레거시 PKL → JSON 마이그레이션 후 CRUD 동작"""
        # NOTE: pickle is used intentionally here to test legacy migration path
        import pickle

        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)

            # Create legacy PKL
            evt = EventModel(event_name="LegEvt", key_to_enter="B",
                             latest_screenshot=Image.new("RGB", (2, 2), (5, 5, 5)))
            p = ProfileModel(name="Legacy", event_list=[evt])
            with open(prof_dir / "Legacy.pkl", "wb") as f:
                pickle.dump(p, f)

            # Load triggers migration
            loaded = load_profile(prof_dir, "Legacy", migrate=True)
            self.assertEqual(loaded.name, "Legacy")
            self.assertTrue((prof_dir / "Legacy.json").exists())

            # CRUD on migrated profile
            rename_profile_files(prof_dir, "Legacy", "Migrated")
            self.assertIn("Migrated", list_profile_names(prof_dir))

            delete_profile_files(prof_dir, "Migrated")
            self.assertNotIn("Migrated", list_profile_names(prof_dir))


if __name__ == "__main__":
    unittest.main(verbosity=2)
