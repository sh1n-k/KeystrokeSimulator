import importlib
import pickle
import tempfile
import unittest
from pathlib import Path

from app.compat.legacy import (
    LEGACY_MODULE_ALIASES,
    canonical_module_names,
    legacy_module_names,
    remap_legacy_module_name,
)
from app.core.models import EventModel, ProfileModel
from app.storage.profile_storage import load_profile


class TestLegacyModuleAliases(unittest.TestCase):
    def test_legacy_module_lists_share_one_mapping_source(self):
        self.assertEqual(legacy_module_names(), list(LEGACY_MODULE_ALIASES))
        self.assertEqual(
            canonical_module_names(),
            list(dict.fromkeys(LEGACY_MODULE_ALIASES.values())),
        )

    def test_root_shim_import_returns_canonical_module(self):
        legacy_module = importlib.import_module("keystroke_models")
        canonical_module = importlib.import_module("app.core.models")
        self.assertIs(legacy_module, canonical_module)
        self.assertEqual(
            remap_legacy_module_name("keystroke_models"), "app.core.models"
        )


class TestLegacyPickleMigration(unittest.TestCase):
    def test_load_profile_reads_legacy_keystroke_models_pickle(self):
        importlib.import_module("keystroke_models")

        original_profile_module = ProfileModel.__module__
        original_event_module = EventModel.__module__
        try:
            ProfileModel.__module__ = "keystroke_models"
            EventModel.__module__ = "keystroke_models"

            with tempfile.TemporaryDirectory() as td:
                profiles_dir = Path(td)
                profile = ProfileModel(
                    name="Legacy",
                    event_list=[EventModel(event_name="Event", key_to_enter="A")],
                )
                with open(profiles_dir / "Legacy.pkl", "wb") as f:
                    pickle.dump(profile, f)

                loaded = load_profile(profiles_dir, "Legacy", migrate=True)

                self.assertEqual(loaded.name, "Legacy")
                self.assertEqual(loaded.event_list[0].event_name, "Event")
                self.assertTrue((profiles_dir / "Legacy.json").exists())
        finally:
            ProfileModel.__module__ = original_profile_module
            EventModel.__module__ = original_event_module


if __name__ == "__main__":
    unittest.main(verbosity=2)
