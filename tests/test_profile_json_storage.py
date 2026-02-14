import json
import pickle
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from keystroke_models import EventModel, ProfileModel
from keystroke_profile_storage import load_profile, save_profile


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


if __name__ == "__main__":
    unittest.main()

