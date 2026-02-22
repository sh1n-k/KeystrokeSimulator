import json
import pickle
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from keystroke_models import EventModel, ProfileModel
from keystroke_profile_storage import (
    copy_profile,
    delete_profile_files,
    ensure_quick_profile,
    event_from_dict,
    event_to_dict,
    list_profile_names,
    load_profile,
    load_profile_meta_favorite,
    rename_profile_files,
    save_profile,
)


class TestProfileJsonStorage(unittest.TestCase):
    def test_json_roundtrip_drops_latest_screenshot(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            held = Image.new("RGB", (3, 3), color=(10, 20, 30))
            latest = Image.new("RGB", (3, 3), color=(1, 2, 3))

            evt = EventModel(
                event_name="E1",
                latest_position=(100, 200),
                clicked_position=(10, 20),
                latest_screenshot=latest,
                held_screenshot=held,
                ref_pixel_value=(10, 20, 30),
                key_to_enter="F1",
                match_mode="pixel",
                invert_match=False,
                region_size=None,
                execute_action=True,
                group_id="G",
                priority=7,
                conditions={"Other": True},
            )
            p = ProfileModel(name="P1", event_list=[evt], favorite=True)
            save_profile(prof_dir, p, name="P1")

            # Verify JSON doesn't contain latest_screenshot.
            raw = json.loads((prof_dir / "P1.json").read_text(encoding="utf-8"))
            self.assertIn("events", raw)
            self.assertEqual(len(raw["events"]), 1)
            self.assertNotIn("latest_screenshot", raw["events"][0])
            self.assertIn("held_screenshot", raw["events"][0])

            p2 = load_profile(prof_dir, "P1", migrate=False)
            self.assertEqual(p2.name, "P1")
            self.assertTrue(p2.favorite)
            self.assertEqual(len(p2.event_list), 1)
            e2 = p2.event_list[0]
            self.assertIsNone(e2.latest_screenshot)
            self.assertIsNotNone(e2.held_screenshot)
            self.assertEqual(e2.held_screenshot.size, (3, 3))

    def test_legacy_pickle_migration_promotes_latest_to_held(self):
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)

            latest = Image.new("RGB", (2, 2), color=(9, 8, 7))
            evt = EventModel(
                event_name="E1",
                latest_position=(1, 2),
                clicked_position=(0, 1),
                latest_screenshot=latest,
                held_screenshot=None,
                ref_pixel_value=(9, 8, 7),
                key_to_enter="A",
            )
            p = ProfileModel(name="Legacy", event_list=[evt], favorite=False)

            with open(prof_dir / "Legacy.pkl", "wb") as f:
                pickle.dump(p, f)

            # Load should read legacy and migrate to JSON.
            migrated = load_profile(prof_dir, "Legacy", migrate=True)
            self.assertEqual(migrated.name, "Legacy")
            self.assertEqual(len(migrated.event_list), 1)

            # JSON should exist; latest_screenshot should be dropped from persisted data.
            self.assertTrue((prof_dir / "Legacy.json").exists())
            p2 = load_profile(prof_dir, "Legacy", migrate=False)
            e2 = p2.event_list[0]
            self.assertIsNone(e2.latest_screenshot)
            self.assertIsNotNone(e2.held_screenshot)
            self.assertEqual(e2.held_screenshot.size, (2, 2))


class TestRenameProfileFiles(unittest.TestCase):
    """rename_profile_files: 프로필 파일 이름 변경"""

    def test_rename_json(self):
        """JSON 파일 이름 변경"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="Old", event_list=[]), name="Old")
            rename_profile_files(prof_dir, "Old", "New")
            self.assertFalse((prof_dir / "Old.json").exists())
            self.assertTrue((prof_dir / "New.json").exists())

    def test_rename_to_existing_raises(self):
        """이미 존재하는 이름으로 변경 시 FileExistsError"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="A", event_list=[]), name="A")
            save_profile(prof_dir, ProfileModel(name="B", event_list=[]), name="B")
            with self.assertRaises(FileExistsError):
                rename_profile_files(prof_dir, "A", "B")

    def test_rename_empty_name_raises(self):
        """빈 이름으로 변경 시 ValueError"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="A", event_list=[]), name="A")
            with self.assertRaises(ValueError):
                rename_profile_files(prof_dir, "A", "")


class TestCopyProfile(unittest.TestCase):
    """copy_profile: 프로필 복사"""

    def test_copy_normal(self):
        """정상 복사"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            evt = EventModel(event_name="E1", key_to_enter="A")
            save_profile(prof_dir, ProfileModel(name="Src", event_list=[evt]), name="Src")
            copy_profile(prof_dir, "Src", "Dst")

            self.assertTrue((prof_dir / "Dst.json").exists())
            dst = load_profile(prof_dir, "Dst")
            self.assertEqual(dst.name, "Dst")
            self.assertEqual(len(dst.event_list), 1)
            self.assertEqual(dst.event_list[0].event_name, "E1")

    def test_copy_duplicate_name_raises(self):
        """중복 이름으로 복사 시 FileExistsError"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="A", event_list=[]), name="A")
            with self.assertRaises(FileExistsError):
                copy_profile(prof_dir, "A", "A")

    def test_copy_empty_name_raises(self):
        """빈 이름으로 복사 시 ValueError"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="A", event_list=[]), name="A")
            with self.assertRaises(ValueError):
                copy_profile(prof_dir, "A", "  ")


class TestDeleteProfileFiles(unittest.TestCase):
    """delete_profile_files: 프로필 삭제"""

    def test_delete_existing(self):
        """정상 삭제"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="X", event_list=[]), name="X")
            self.assertTrue((prof_dir / "X.json").exists())
            delete_profile_files(prof_dir, "X")
            self.assertFalse((prof_dir / "X.json").exists())

    def test_delete_nonexistent_no_error(self):
        """존재하지 않는 파일 삭제 시 에러 없음"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            delete_profile_files(prof_dir, "NonExistent")  # should not raise


class TestListProfileNames(unittest.TestCase):
    """list_profile_names: 프로필 이름 목록"""

    def test_json_and_pkl_mixed(self):
        """JSON+PKL 혼합"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="Alpha", event_list=[]), name="Alpha")
            # Create a fake PKL
            (prof_dir / "Beta.pkl").write_bytes(b"fake")
            names = list_profile_names(prof_dir)
            self.assertIn("Alpha", names)
            self.assertIn("Beta", names)

    def test_quick_first(self):
        """Quick 프로필이 항상 첫 번째"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="Zebra", event_list=[]), name="Zebra")
            save_profile(prof_dir, ProfileModel(name="Quick", event_list=[]), name="Quick")
            names = list_profile_names(prof_dir)
            self.assertEqual(names[0], "Quick")

    def test_empty_directory(self):
        """빈 디렉토리"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            names = list_profile_names(prof_dir)
            self.assertEqual(names, [])


class TestEventRoundtrip(unittest.TestCase):
    """event_to_dict / event_from_dict: 직접 roundtrip"""

    def test_full_field_roundtrip(self):
        """전체 필드 roundtrip"""
        held = Image.new("RGB", (4, 4), color=(50, 100, 150))
        evt = EventModel(
            event_name="Round",
            latest_position=(10, 20),
            clicked_position=(5, 15),
            held_screenshot=held,
            ref_pixel_value=(50, 100, 150),
            key_to_enter="B",
            press_duration_ms=200.0,
            randomization_ms=30.0,
            independent_thread=True,
            match_mode="region",
            invert_match=True,
            region_size=(20, 30),
            execute_action=False,
            group_id="GroupA",
            priority=3,
            conditions={"Dep": False},
        )
        evt.use_event = False

        d = event_to_dict(evt)
        restored = event_from_dict(d)

        self.assertEqual(restored.event_name, "Round")
        self.assertEqual(restored.clicked_position, (5, 15))
        self.assertEqual(restored.key_to_enter, "B")
        self.assertEqual(restored.press_duration_ms, 200.0)
        self.assertTrue(restored.independent_thread)
        self.assertEqual(restored.match_mode, "region")
        self.assertTrue(restored.invert_match)
        self.assertEqual(restored.region_size, (20, 30))
        self.assertFalse(restored.execute_action)
        self.assertEqual(restored.group_id, "GroupA")
        self.assertEqual(restored.priority, 3)
        self.assertEqual(restored.conditions, {"Dep": False})
        self.assertIsNotNone(restored.held_screenshot)
        self.assertEqual(restored.held_screenshot.size, (4, 4))
        self.assertIsNone(restored.latest_screenshot)

    def test_none_fields_roundtrip(self):
        """None 필드 roundtrip"""
        evt = EventModel(event_name="Minimal")
        d = event_to_dict(evt)
        restored = event_from_dict(d)
        self.assertEqual(restored.event_name, "Minimal")
        self.assertIsNone(restored.clicked_position)
        self.assertIsNone(restored.held_screenshot)
        self.assertIsNone(restored.ref_pixel_value)

    def test_image_roundtrip_preserves_pixels(self):
        """이미지 포함 roundtrip에서 픽셀 보존"""
        img = Image.new("RGB", (2, 2), color=(42, 84, 126))
        evt = EventModel(event_name="ImgTest", held_screenshot=img)
        d = event_to_dict(evt)
        restored = event_from_dict(d)
        self.assertEqual(restored.held_screenshot.getpixel((0, 0)), (42, 84, 126))


class TestEnsureQuickProfile(unittest.TestCase):
    """ensure_quick_profile: Quick 프로필 자동 생성"""

    def test_creates_when_missing(self):
        """Quick 프로필이 없으면 생성"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            ensure_quick_profile(prof_dir)
            self.assertTrue((prof_dir / "Quick.json").exists())

    def test_no_overwrite_existing(self):
        """Quick 프로필이 이미 있으면 덮어쓰지 않음"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            evt = EventModel(event_name="Existing", key_to_enter="X")
            save_profile(prof_dir, ProfileModel(name="Quick", event_list=[evt]), name="Quick")
            ensure_quick_profile(prof_dir)
            p = load_profile(prof_dir, "Quick")
            self.assertEqual(len(p.event_list), 1)
            self.assertEqual(p.event_list[0].event_name, "Existing")


class TestLoadProfileMetaFavorite(unittest.TestCase):
    """load_profile_meta_favorite: favorite 메타데이터 조회"""

    def test_json_favorite(self):
        """JSON에서 favorite 조회"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            save_profile(prof_dir, ProfileModel(name="Fav", event_list=[], favorite=True), name="Fav")
            self.assertTrue(load_profile_meta_favorite(prof_dir, "Fav"))

    def test_nonexistent_defaults_false(self):
        """파일 없음 → False (새 프로필 생성됨)"""
        with tempfile.TemporaryDirectory() as td:
            prof_dir = Path(td)
            result = load_profile_meta_favorite(prof_dir, "NonExistent")
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()

