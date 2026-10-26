import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.domain.models import EventModel, ProfileModel
from app.storage.profile_storage import load_profile, save_profile
from app.domain.capture_geometry import (
    MAGNIFIER_SPAN,
    MAGNIFIER_ZOOM,
    CaptureResult,
    border_rects,
    display_to_image,
    hud_position,
    magnifier_to_image,
    preview_size,
    rects_overlap,
)
from app.domain.capture_render import render_magnifier, render_overlay
from app.presenters.quick_capture import append_quick_event
from app.ui import tokens as theme


class TestPreviewMapping(unittest.TestCase):
    def test_preview_is_one_to_one_up_to_limit(self):
        self.assertEqual(preview_size((100, 100)), (100, 100))
        self.assertEqual(preview_size((400, 200)), (200, 100))

    def test_display_to_image_scales_and_rejects_outside(self):
        self.assertEqual(
            display_to_image((100, 50), (200, 100), (400, 200)), (200, 100)
        )
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

        zoomed = render_magnifier(img, (0, 0), (0, 0), pad_color=theme.SURFACE_SUNKEN)

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
        self.assertIsNone(
            hud_position((0, 0, 260, 330), (800, 400, 100, 100), self.SCREEN)
        )

    def test_moves_to_opposite_corner_of_box(self):
        hud = (100, 100, 260, 330)
        box_top_left = (150, 150, 100, 100)
        box_bottom_right = (1700, 900, 100, 100)

        self.assertEqual(
            hud_position(hud, box_top_left, self.SCREEN),
            (1920 - 260 - 16, 1080 - 330 - 16),
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


class TestAppendQuickEvent(unittest.TestCase):
    def test_appends_after_existing_events_with_next_number(self):
        """B-01: earlier Quick events and their keys survive a new session."""
        with tempfile.TemporaryDirectory() as tmp:
            prof_dir = Path(tmp)
            save_profile(
                prof_dir,
                ProfileModel(
                    name="Quick",
                    event_list=[EventModel(event_name="7", key_to_enter="Q")],
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
