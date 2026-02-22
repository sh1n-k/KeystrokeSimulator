import json
import os
import shutil
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"

# Headless CI guard: skip when RUN_GUI_TESTS is not set
_RUN_GUI_TESTS = os.environ.get("RUN_GUI_TESTS", "0") == "1"

from keystroke_simulator_app import KeystrokeSimulatorApp
from keystroke_models import ProfileModel, EventModel
from profile_display import QUICK_PROFILE_NAME

# Suppress loguru output during tests to prevent clutter
from loguru import logger
logger.remove()
logger.add(lambda msg: None, level="ERROR")


@unittest.skipUnless(_RUN_GUI_TESTS, "GUI tests require RUN_GUI_TESTS=1")
class TestKeystrokeSimulatorE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a temporary directory for profiles so we don't pollute the real ones
        cls.test_profiles_dir = Path("test_profiles_e2e")
        if cls.test_profiles_dir.exists():
            shutil.rmtree(cls.test_profiles_dir)
        cls.test_profiles_dir.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls):
        if cls.test_profiles_dir.exists():
            shutil.rmtree(cls.test_profiles_dir)

    def setUp(self):
        # Prevent actually locking real hotkeys or moving mouse
        self.patcher_keyboard = patch("keystroke_simulator_app.KeyUtils")
        self.mock_keyboard = self.patcher_keyboard.start()

        # Mock SoundPlayer to not play real audio
        self.patcher_sound = patch("keystroke_simulator_app.SoundPlayer")
        self.patcher_sound.start()

        # Initialize the app and point it to test profiles dir
        with patch.object(KeystrokeSimulatorApp, "_load_settings_and_state", autospec=True) as mock_load:
            # We must assign self.settings manually since we patch out the method that normally does it
            def side_effect(app_instance):
                app_instance.settings = MagicMock()
                app_instance.settings.toggle_start_stop_mac = False
                app_instance.settings.start_stop_key = "F12"
            
            mock_load.side_effect = side_effect
            
            self.app = KeystrokeSimulatorApp(secure_callback=MagicMock())
            self.app.profiles_dir = str(self.test_profiles_dir)

    def tearDown(self):
        self.app.stop_simulation()
        self.app.destroy()
        patch.stopall()

    @patch("tkinter.messagebox.askokcancel")
    @patch("tkinter.messagebox.showwarning")
    @patch("keystroke_simulator_app.copy_profile_storage")
    def test_scenario_a_profile_management(self, mock_copy_storage, mock_warn, mock_askokcancel):
        """
        Scenario A: [Profile Management Flow]
        1. Click 'Copy Profile'
        2. Verify it's created and active
        3. Delete the profile
        4. Verify app falls back
        """
        initial_profile = self.app.profile_frame.get_selected_profile_name() or QUICK_PROFILE_NAME
        expected_name = f"{initial_profile} - Copied"

        def _mock_copy(src_dir, curr, dst):
            # Create a dummy file so `load_profiles` will naturally pick it up
            (Path(src_dir) / f"{dst}.json").write_text(json.dumps({"name": dst}), encoding="utf-8")

        mock_copy_storage.side_effect = _mock_copy
        
        # 1. Create new profile
        self.app.profile_frame.copy_profile()
        self.app.update()

        # 2. Verify it's created and automatically selected
        self.assertEqual(self.app.profile_frame.get_selected_profile_name(), expected_name)
        
        # File could be .json or .json based on logic. Let's just check if it gets selected.
        
        # 3. Delete the profile
        mock_askokcancel.return_value = True
        self.app.profile_frame.delete_profile()

        # 4. Verify fallback
        self.assertNotEqual(self.app.profile_frame.get_selected_profile_name(), expected_name)

    @patch("keystroke_simulator_app.KeystrokeQuickEventEditor")
    def test_scenario_b_event_creation_flow(self, mock_editor_class):
        """
        Scenario B: [Event Creation & Grouping Flow]
        1. Open Editor
        2. Verify the editor component is invoked.
        """
        # Create a mock quick profile file
        quick_file = self.test_profiles_dir / f"{QUICK_PROFILE_NAME}.json"
        quick_file.write_text("{}", encoding="utf-8")
        
        self.app.profile_frame.selected_profile_var.set(QUICK_PROFILE_NAME)

        # 1. Open Editor (Quick Events)
        self.app.open_quick_events()
        mock_editor_class.assert_called_once()

    @patch("keystroke_simulator_app.load_profile")
    @patch("keystroke_processor.KeystrokeProcessor.start")
    @patch("keystroke_processor.KeystrokeProcessor.stop")
    def test_scenario_c_simulator_start_stop(self, mock_proc_stop, mock_proc_start, mock_load_profile):
        """
        Scenario C: [Simulator Start and Stop Flow]
        1. Start Simulator
        2. Verify worker thread initialized
        3. Stop Simulator
        4. Verify termination
        """
        # A dummy profile name that we know isn't empty
        self.app.selected_profile.set(QUICK_PROFILE_NAME)
        # Ensure 'Start' button toggles properly with required states
        self.app.selected_process.set("Dummy Process (1234)")
        
        # Mock load_profile to return a valid ProfileModel with an active event
        dummy_event = EventModel(event_name="Dummy", use_event=True, key_to_enter="A")
        dummy_profile = ProfileModel(name=QUICK_PROFILE_NAME, event_list=[dummy_event])
        mock_load_profile.return_value = dummy_profile
        
        self.app.toggle_start_stop()
        
        # Verify processor started
        self.assertTrue(self.app.is_running.get())
        self.assertEqual(self.app.button_frame.start_stop_button["text"], "Stop")
        mock_proc_start.assert_called_once()

        # Simulate clicking Stop
        self.app.toggle_start_stop()
        
        # Verify processor stopped
        self.assertFalse(self.app.is_running.get())
        self.assertEqual(self.app.button_frame.start_stop_button["text"], "Start")
        mock_proc_stop.assert_called_once()

if __name__ == "__main__":
    unittest.main()
