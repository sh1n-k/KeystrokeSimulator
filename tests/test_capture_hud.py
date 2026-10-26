import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from app.domain.models import EventModel, ProfileModel
from app.storage.profile_storage import load_profile, save_profile
from app.ui.capture_hud import (
    MAGNIFIER_SPAN,
    MAGNIFIER_ZOOM,
    CaptureHud,
    CaptureResult,
    append_quick_event,
    border_rects,
    ctrl_capture_allowed,
    display_to_image,
    hud_position,
    magnifier_to_image,
    preview_size,
    render_magnifier,
    render_overlay,
)
from app.ui import theme
from app.ui.capture_session import CaptureSession, rects_overlap
from app.utils.i18n import set_language

_RUN_GUI_TESTS = os.environ.get("RUN_GUI_TESTS", "0") == "1"


class FakeCapturer:
    def __init__(self, position=(500, 400)):
        self.screenshot_callback = None
        self.capture_thread = None
        self.position = position
        self.size = (100, 100)

    def start_capture(self):
        pass

    def stop_capture(self):
        pass

    def set_capture_size(self, width, height):
        self.size = (width, height)

    def set_mouse_position(self, position):
        self.position = position

    def set_current_mouse_position(self, position):
        self.position = position

    def get_current_mouse_position(self):
        return self.position

    def emit(self, color, marker=None):
        img = Image.new("RGB", self.size, color)
        if marker is not None:
            img.putpixel(marker[0], marker[1])
        self.screenshot_callback(self.position, img)


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeFocus:
    def __init__(self, cls):
        self.cls = cls

    def winfo_class(self):
        return self.cls


class TestPreviewMapping(unittest.TestCase):
    def test_preview_is_one_to_one_up_to_limit(self):
        self.assertEqual(preview_size((100, 100)), (100, 100))
        self.assertEqual(preview_size((400, 200)), (200, 100))

    def test_display_to_image_scales_and_rejects_outside(self):
        self.assertEqual(display_to_image((100, 50), (200, 100), (400, 200)), (200, 100))
        self.assertIsNone(display_to_image((200, 10), (200, 100), (400, 200)))


class TestMagnifier(unittest.TestCase):
    def test_magnifier_to_image_maps_cells(self):
        half = MAGNIFIER_SPAN // 2
        self.assertEqual(
            magnifier_to_image((0, 0), (50, 50), (100, 100)), (50 - half, 50 - half)
        )
        center_cell = half * MAGNIFIER_ZOOM + MAGNIFIER_ZOOM // 2
        self.assertEqual(
            magnifier_to_image((center_cell, center_cell), (50, 50), (100, 100)),
            (50, 50),
        )
        self.assertIsNone(magnifier_to_image((0, 0), (0, 0), (100, 100)))

    def test_render_magnifier_pads_outside_and_marks_selected(self):
        img = Image.new("RGB", (20, 20), (255, 0, 0))

        zoomed = render_magnifier(img, (0, 0), (0, 0))

        size = MAGNIFIER_SPAN * MAGNIFIER_ZOOM
        self.assertEqual(zoomed.size, (size, size))
        half = MAGNIFIER_SPAN // 2
        # Top-left cell lies outside the image and stays padded, not red.
        self.assertNotEqual(zoomed.getpixel((1, 1)), (255, 0, 0))
        # The selected (center) cell has a black outline and red inside.
        x0 = half * MAGNIFIER_ZOOM
        self.assertEqual(zoomed.getpixel((x0, x0)), (0, 0, 0))
        self.assertEqual(zoomed.getpixel((x0 + 3, x0 + 3)), (255, 0, 0))


class TestOverlay(unittest.TestCase):
    def test_pixel_mode_inverts_crosshair_once(self):
        img = Image.new("RGB", (10, 10), (10, 20, 30))

        res = render_overlay(img, (3, 4))

        self.assertEqual(res.getpixel((0, 4)), (245, 235, 225))
        self.assertEqual(res.getpixel((3, 0)), (245, 235, 225))
        self.assertEqual(res.getpixel((3, 4)), (245, 235, 225))
        self.assertEqual(res.getpixel((0, 0)), (10, 20, 30))
        self.assertEqual(img.getpixel((0, 4)), (10, 20, 30))

    def test_region_mode_draws_rectangle_and_ignores_stale_pixel(self):
        img = Image.new("RGB", (40, 40), (0, 0, 0))

        res = render_overlay(img, (20, 20), (20, 20))
        stale = render_overlay(img, (99, 5))

        self.assertEqual(res.getpixel((10, 20)), (255, 255, 0))
        self.assertEqual(stale.getpixel((5, 5)), (0, 0, 0))


class TestHudPosition(unittest.TestCase):
    SCREEN = (1920, 1080)

    def test_no_move_without_overlap(self):
        self.assertIsNone(hud_position((0, 0, 260, 330), (800, 400, 100, 100), self.SCREEN))

    def test_moves_to_opposite_corner_of_box(self):
        hud = (100, 100, 260, 330)
        box_top_left = (150, 150, 100, 100)
        box_bottom_right = (1700, 900, 100, 100)

        self.assertEqual(
            hud_position(hud, box_top_left, self.SCREEN), (1920 - 260 - 16, 1080 - 330 - 16)
        )
        self.assertEqual(
            hud_position((1600, 700, 260, 330), box_bottom_right, self.SCREEN), (16, 16)
        )

    def test_stays_on_screen_when_box_covers_every_corner(self):
        hud = (1400, 550, 260, 330)
        box = (100, 50, 1700, 1000)  # no corner is free: fall back on-screen

        x, y = hud_position(hud, box, self.SCREEN)

        self.assertEqual((x, y), (1920 - 260 - 16, 16))


class TestBorderRects(unittest.TestCase):
    """O-01: the outline sits outside the capture box and never covers it."""

    def test_border_surrounds_box_from_outside(self):
        box = (100, 50, 40, 30)

        rects = border_rects(box, 2)

        self.assertEqual(
            rects,
            [(98, 48, 44, 2), (98, 80, 44, 2), (98, 50, 2, 30), (140, 50, 2, 30)],
        )
        for rect in rects:
            self.assertFalse(rects_overlap(rect, box))

    def test_border_at_screen_edge_keeps_positive_size(self):
        for _x, _y, w, h in border_rects((0, 0, 100, 100), 2):
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)


class TestBindCommit(unittest.TestCase):
    def test_enter_runs_handler_and_breaks(self):
        widget = MagicMock()
        handler = MagicMock()

        CaptureHud._bind_commit(widget, handler)

        sequences = [c.args[0] for c in widget.bind.call_args_list]
        self.assertEqual(sequences, ["<Return>", "<KP_Enter>"])
        on_return = widget.bind.call_args_list[0].args[1]
        self.assertEqual(on_return(None), "break")
        handler.assert_called_once()


class TestCtrlFocusGuard(unittest.TestCase):
    def test_text_inputs_block_ctrl_capture(self):
        self.assertFalse(ctrl_capture_allowed(FakeFocus("TEntry")))
        self.assertFalse(ctrl_capture_allowed(FakeFocus("TSpinbox")))
        self.assertTrue(ctrl_capture_allowed(FakeFocus("TButton")))
        self.assertTrue(ctrl_capture_allowed(None))

    @patch("app.ui.capture_hud.KeyUtils.mod_key_pressed")
    def test_check_keys_ignores_ctrl_while_typing(self, mock_pressed):
        mock_pressed.side_effect = lambda key: key == "ctrl"
        hud = _make_hud_stub(CaptureSession(FakeCapturer()), mode="single")
        hud.win.focus_get.return_value = FakeFocus("TEntry")
        hud._on_ctrl = MagicMock()

        CaptureHud._check_keys(hud)

        hud._on_ctrl.assert_not_called()

        hud._ctrl_was_pressed = False
        hud.win.focus_get.return_value = None
        CaptureHud._check_keys(hud)

        hud._on_ctrl.assert_called_once()


def _make_hud_stub(session, *, mode, profiles_dir=None):
    hud = CaptureHud.__new__(CaptureHud)
    hud.mode = mode
    hud.capture_session = session
    hud.profiles_dir = profiles_dir
    hud.on_apply = MagicMock()
    hud.saved_count = 0
    hud.region_size = None
    hud._is_closing = False
    hud._alt_down = False
    hud._ctrl_was_pressed = False
    hud._held_size = None
    hud._mag_center = None
    hud._feedback = None
    hud._permission_message = None
    hud._permission_ticks = 30
    hud.capture_w_var = FakeVar(100)
    hud.capture_h_var = FakeVar(100)
    hud.win = MagicMock()
    hud.border = None
    hud.close = MagicMock()
    hud._render = MagicMock()
    hud._render_info = MagicMock()
    hud._avoid_capture_box = MagicMock()
    return hud


class TestCaptureFlow(unittest.TestCase):
    def setUp(self):
        set_language("en")
        self.capturer = FakeCapturer()
        self.session = CaptureSession(self.capturer)
        self.session.start()

    def test_capture_keeps_pick_inside_new_frame_and_updates_color(self):
        hud = _make_hud_stub(self.session, mode="single")
        self.capturer.emit((0, 0, 255))
        hud.capture()
        hud._select((3, 4))
        self.capturer.emit((0, 255, 0))

        hud.capture()

        self.assertEqual(self.session.selected_position, (3, 4))
        self.assertEqual(self.session.reference_color, (0, 255, 0))

    def test_single_mode_ctrl_always_captures(self):
        hud = _make_hud_stub(self.session, mode="single")
        self.capturer.emit((0, 0, 255))
        hud.capture()
        hud._select((3, 4))
        hud.capture = MagicMock()

        hud._on_ctrl()

        hud.capture.assert_called_once()
        hud.on_apply.assert_not_called()

    def test_moved_area_stays_live_until_frozen(self):
        """After ALT moves off the held area, releasing ALT keeps the live view
        and Apply refuses the stale capture until CTRL freezes the new area."""
        hud = _make_hud_stub(self.session, mode="single")
        self.capturer.emit((0, 0, 255))
        hud.capture()
        hud._select((3, 4))
        self.assertFalse(hud._shows_live())

        self.session.set_position((900, 700))  # ALT move, then released
        self.capturer.emit((0, 255, 0))

        self.assertTrue(hud._shows_live())
        self.assertEqual(hud._displayed_image().getpixel((0, 0)), (0, 255, 0))
        self.assertEqual(hud._status()[0], "Press CTRL to freeze this area.")
        hud.apply()
        hud.on_apply.assert_not_called()

        hud.capture()
        hud.apply()

        result = hud.on_apply.call_args.args[0]
        self.assertEqual(result.position, (900, 700))
        self.assertEqual(result.color, (0, 255, 0))

    def test_single_mode_apply_hands_result_and_closes(self):
        hud = _make_hud_stub(self.session, mode="single")
        self.capturer.emit((0, 0, 255))
        hud.capture()
        hud._select((3, 4))

        hud.apply()

        result = hud.on_apply.call_args.args[0]
        self.assertIsInstance(result, CaptureResult)
        self.assertEqual(result.position, (500, 400))
        self.assertEqual(result.pixel, (3, 4))
        self.assertEqual(result.color, (0, 0, 255))
        self.assertEqual(result.capture_size, (100, 100))
        hud.close.assert_called_once()

    def test_continuous_second_ctrl_saves_held_frame_not_a_new_one(self):
        """H-07: the second CTRL applies the capture the target was picked on."""
        with tempfile.TemporaryDirectory() as tmp:
            prof_dir = Path(tmp)
            hud = _make_hud_stub(self.session, mode="continuous", profiles_dir=prof_dir)
            self.capturer.emit((0, 0, 255))
            hud._on_ctrl()  # first CTRL: freeze
            hud._select((3, 4))
            self.capturer.emit((255, 0, 0))  # the live frame changes afterwards

            hud._on_ctrl()  # second CTRL: apply

            saved = load_profile(prof_dir, "Quick", migrate=False).event_list
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].held_screenshot.getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(saved[0].ref_pixel_value[:3], (0, 0, 255))
        self.assertEqual(hud.saved_count, 1)
        self.assertIsNone(self.session.held_image)

    def test_continuous_ctrl_after_moving_recaptures(self):
        hud = _make_hud_stub(self.session, mode="continuous", profiles_dir=Path("x"))
        self.capturer.emit((0, 0, 255))
        hud._on_ctrl()
        hud._select((3, 4))
        self.session.set_position((600, 400))
        hud.apply = MagicMock()

        hud._on_ctrl()

        hud.apply.assert_not_called()
        self.assertEqual(self.session.held_position, (500, 400))

    def test_apply_without_pick_warns(self):
        hud = _make_hud_stub(self.session, mode="single")

        hud.apply()

        hud.on_apply.assert_not_called()
        self.assertIn("CTRL", hud._feedback[0])


class TestAppendQuickEvent(unittest.TestCase):
    def test_appends_after_existing_events_with_next_number(self):
        """B-01: earlier Quick events and their keys survive a new session."""
        with tempfile.TemporaryDirectory() as tmp:
            prof_dir = Path(tmp)
            save_profile(
                prof_dir,
                ProfileModel(
                    name="Quick", event_list=[EventModel(event_name="7", key_to_enter="Q")]
                ),
                name="Quick",
            )
            result = CaptureResult(
                position=(1, 2),
                capture_size=(120, 80),
                image=Image.new("RGB", (120, 80)),
                pixel=(3, 4),
                color=(9, 9, 9),
            )

            name = append_quick_event(prof_dir, result)

            saved = load_profile(prof_dir, "Quick", migrate=False).event_list
        self.assertEqual(name, "8")
        self.assertEqual([e.event_name for e in saved], ["7", "8"])
        self.assertEqual(saved[0].key_to_enter, "Q")
        self.assertEqual(saved[1].capture_size, (120, 80))
        self.assertEqual(saved[1].latest_position, (1, 2))


@unittest.skipUnless(_RUN_GUI_TESTS, "GUI tests require RUN_GUI_TESTS=1")
class TestCaptureHudLayout(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        # theme caches Font objects on the first root; earlier GUI tests
        # destroyed theirs.
        theme._cached_fonts = None
        self.root.withdraw()

    def tearDown(self):
        set_language("en")
        self.root.destroy()

    @patch("app.ui.capture_hud.KeyUtils.mod_key_pressed", return_value=False)
    @patch("app.ui.capture_hud.StateUtils.save_main_app_state")
    @patch("app.ui.capture_hud.StateUtils.load_main_app_state", return_value={})
    def test_hud_width_stays_within_300px_for_100px_capture(self, *_mocks):
        """H-01: the HUD is at most 300px wide for a 100x100 capture."""
        for lang in ("en", "ko"):
            set_language(lang)
            for mode in ("single", "continuous"):
                with self.subTest(lang=lang, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    capturer = FakeCapturer()
                    hud = CaptureHud(
                        self.root,
                        mode=mode,
                        name="Event name that is fairly long",
                        capturer=capturer,
                        profiles_dir=Path(tmp),
                    )
                    self.root.update()
                    capturer.emit((0, 0, 255), ((10, 10), (255, 0, 255)))
                    hud.capture()
                    hud._select((10, 10))
                    hud._toggle_advanced()
                    self.root.update()

                    self.assertLessEqual(hud.win.winfo_width(), 300)
                    hud._sync_border()
                    self.root.update()
                    top = hud.border.windows[0]
                    self.assertEqual(
                        (top.winfo_x(), top.winfo_y(), top.winfo_width()),
                        (498, 398, 104),
                    )
                    self.assertEqual(int(hud.win.attributes("-topmost")), 1)
                    self.assertTrue(hud.is_ready())
                    self.assertEqual(hud.lbl_info.cget("text"), "255,0,255  (510, 410)")
                    hud.close()

    @patch("app.ui.capture_hud.KeyUtils.mod_key_pressed", return_value=False)
    @patch("app.ui.capture_hud.StateUtils.save_main_app_state")
    @patch("app.ui.capture_hud.StateUtils.load_main_app_state", return_value={})
    def test_advanced_inputs_commit_enter_without_applying(self, *_mocks):
        """Enter in the advanced inputs must stop before the window's Apply
        binding. Checked through the binding path: synthetic key events need
        app focus, which is slow and flaky on macOS."""
        committed = []
        original = CaptureHud._bind_commit

        def record(widget, handler):
            committed.append(widget)
            original(widget, handler)

        with patch.object(CaptureHud, "_bind_commit", side_effect=record):
            hud = CaptureHud(self.root, mode="single", capturer=FakeCapturer())
        spins = [
            w
            for w in hud.advanced.winfo_children()
            if w.winfo_class() == "TSpinbox"
        ]

        for widget in [*hud.pos_entries, *hud.pixel_entries, *spins]:
            self.assertIn(widget, committed)
        self.assertEqual(len(spins), 2)
        hud.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
