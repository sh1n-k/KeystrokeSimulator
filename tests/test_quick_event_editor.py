import os
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from app.core.models import ProfileModel
from app.ui.quick_event_editor import KeystrokeQuickEventEditor
from app.utils.i18n import set_language

_RUN_GUI_TESTS = os.environ.get("RUN_GUI_TESTS", "0") == "1"


class FakeWidget:
    def __init__(self):
        self.state = {}

    def config(self, **kwargs):
        self.state.update(kwargs)

    def cget(self, key):
        return self.state.get(key)


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeEntry:
    def __init__(self):
        self.value = ""

    def delete(self, _start, _end):
        self.value = ""

    def insert(self, _index, value):
        self.value = str(value)


class TestQuickEventEditorStatus(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def _make_stub(self):
        stub = KeystrokeQuickEventEditor.__new__(KeystrokeQuickEventEditor)
        stub.saved_count = 0
        stub.latest_img = None
        stub.held_img = None
        stub.clicked_pos = None
        stub.lbl_step = FakeWidget()
        stub.lbl_session = FakeWidget()
        stub.lbl_feedback = FakeWidget()
        return stub

    def test_refresh_status_text_guides_first_step(self):
        stub = self._make_stub()

        stub._refresh_status_text()

        self.assertIn("move the mouse", stub.lbl_step.cget("text"))
        self.assertEqual(
            stub.lbl_session.cget("text"),
            "0 Quick event(s) saved in this session.",
        )

    def test_hold_image_without_live_preview_sets_feedback(self):
        stub = self._make_stub()
        stub.latest_pos = None

        stub.hold_image()

        self.assertIn("Move the mouse over the target first", stub.lbl_feedback.cget("text"))

    def test_hold_image_saves_event_when_target_already_selected(self):
        stub = self._make_stub()
        stub.latest_pos = (11, 22)
        stub.latest_img = Image.new("RGB", (20, 20), "red")
        stub.clicked_pos = (3, 4)
        stub.entries = [FakeEntry(), FakeEntry(), FakeEntry(), FakeEntry()]
        stub.lbl_img2 = object()
        stub._upd_img = MagicMock()
        stub._apply_overlay = MagicMock()
        stub.save_event = MagicMock()

        stub.hold_image()

        self.assertEqual(stub.entries[0].value, "11")
        self.assertEqual(stub.entries[1].value, "22")
        stub.save_event.assert_called_once()

    @patch("app.ui.quick_event_editor.save_profile")
    @patch("app.ui.quick_event_editor.load_profile")
    def test_save_event_updates_feedback_and_count(
        self, mock_load_profile, mock_save_profile
    ):
        stub = self._make_stub()
        stub.event_idx = 1
        stub.events = []
        stub.latest_pos = (10, 20)
        stub.clicked_pos = (3, 4)
        stub.latest_img = Image.new("RGB", (8, 8), "blue")
        stub.held_img = stub.latest_img.copy()
        stub.ref_pixel = (0, 0, 255)
        stub.capture_w_var = FakeVar(120)
        stub.capture_h_var = FakeVar(80)
        stub.prof_dir = "profiles"
        mock_load_profile.return_value = ProfileModel(name="Quick", event_list=[])

        stub.save_event()

        self.assertEqual(stub.saved_count, 1)
        self.assertEqual(len(stub.events), 1)
        self.assertEqual(stub.events[0].capture_size, (120, 80))
        mock_save_profile.assert_called_once()
        self.assertIn("Quick event #1 saved", stub.lbl_feedback.cget("text"))
        self.assertEqual(
            stub.lbl_session.cget("text"),
            "1 Quick event(s) saved in this session.",
        )


@unittest.skipUnless(_RUN_GUI_TESTS, "GUI tests require RUN_GUI_TESTS=1")
class TestQuickEventEditorLayout(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()

    def tearDown(self):
        self.root.destroy()

    @patch("app.ui.quick_event_editor.KeyUtils.mod_key_pressed", return_value=False)
    @patch("app.ui.quick_event_editor.ensure_quick_profile")
    @patch("app.ui.quick_event_editor.ScreenshotCapturer")
    @patch("app.ui.quick_event_editor.WindowUtils.center_window")
    @patch("app.ui.quick_event_editor.StateUtils.load_main_app_state", return_value={})
    @patch("app.ui.quick_event_editor.StateUtils.save_main_app_state")
    def test_action_buttons_are_centered(
        self,
        _mock_save_state,
        _mock_load_state,
        _mock_center,
        mock_capturer_cls,
        _mock_ensure_quick,
        _mock_mod_key,
    ):
        capturer = mock_capturer_cls.return_value
        capturer.capture_thread = None
        capturer.get_current_mouse_position.return_value = (0, 0)
        editor = KeystrokeQuickEventEditor(self.root)

        self.root.update()
        editor.win.update()

        dock_center = editor.button_dock.winfo_width() / 2
        group_center = editor.button_group.winfo_x() + editor.button_group.winfo_width() / 2
        self.assertLessEqual(abs(dock_center - group_center), 1)
        editor.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
