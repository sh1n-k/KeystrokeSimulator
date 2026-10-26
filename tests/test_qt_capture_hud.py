import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.domain.capture_geometry import CaptureResult, rects_overlap
from app.ui.capture_hud import (
    CaptureHud,
    _to_logical_rect,
    open_quick_capture,
    text_input_has_focus,
)
from app.utils.i18n import set_language
from tests.qt_support import qt_app
from tests.test_capture_controller import FakeCapturer

_CTRL = "app.presenters.capture_controller"


class HudTestCase(unittest.TestCase):
    def setUp(self):
        self.app = qt_app()
        set_language("en")
        self.keys = {"alt": False, "ctrl": False}
        self.saved: list[dict] = []
        patches = [
            patch(
                f"{_CTRL}.KeyUtils.mod_key_pressed",
                side_effect=lambda key, *a, **k: self.keys[key],
            ),
            patch(f"{_CTRL}.StateUtils.load_main_app_state", return_value={}),
            patch(
                f"{_CTRL}.StateUtils.save_main_app_state",
                side_effect=lambda **kw: self.saved.append(kw),
            ),
            patch(f"{_CTRL}.PermissionUtils.missing_macos_permissions", return_value=[]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.profiles = Path(self._tmp.name)
        self.huds: list[CaptureHud] = []

    def tearDown(self):
        for hud in self.huds:
            hud.close()
        self.app.processEvents()

    def make(self, mode="single", **kw) -> tuple[CaptureHud, FakeCapturer]:
        capturer = kw.pop("capturer", FakeCapturer())
        hud = CaptureHud(
            None, mode=mode, capturer=capturer, profiles_dir=self.profiles, **kw
        )
        self.huds.append(hud)
        return hud, capturer

    @staticmethod
    def ready(hud: CaptureHud, capturer: FakeCapturer, pixel=(10, 10)) -> None:
        capturer.emit((0, 0, 255), (pixel, (255, 0, 255)))
        hud.capture()
        hud.select(pixel)


class TestCaptureHudWindow(HudTestCase):
    def test_opens_visible_on_top_tool_window(self):
        hud, _ = self.make()

        self.assertTrue(hud.isVisible())
        self.assertTrue(hud.is_open())
        flags = hud.windowFlags()
        self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)
        self.assertEqual(flags & Qt.WindowType.Tool, Qt.WindowType.Tool)
        self.assertEqual(hud.windowModality(), Qt.WindowModality.NonModal)

    def test_grab_makes_it_modal(self):
        hud, _ = self.make(grab=True)

        self.assertEqual(hud.windowModality(), Qt.WindowModality.ApplicationModal)

    def test_width_stays_within_300px_for_100px_capture(self):
        """H-01: 100x100 캡처에서 HUD 폭은 300px 이하."""
        for lang in ("en", "ko"):
            set_language(lang)
            for mode in ("single", "continuous"):
                with self.subTest(lang=lang, mode=mode):
                    hud, cap = self.make(mode, name="Event name that is fairly long")
                    self.ready(hud, cap)
                    hud._toggle_advanced()
                    self.app.processEvents()
                    self.assertLessEqual(hud.width(), 300)
                    hud.close()

    def test_border_pieces_sit_outside_the_capture_box(self):
        hud, _ = self.make()
        hud._sync_border()

        rects = [w.geometry().getRect() for w in hud.border.windows]

        self.assertEqual(
            rects,
            [(498, 398, 104, 2), (498, 500, 104, 2), (498, 400, 2, 100), (600, 400, 2, 100)],
        )
        for rect in rects:
            self.assertFalse(rects_overlap(rect, (500, 400, 100, 100)))
        for win in hud.border.windows:
            self.assertTrue(win.isVisible())
            self.assertTrue(win.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            self.assertTrue(win.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))

    def test_logical_border_rect_never_shrinks_into_the_box(self):
        self.assertEqual(_to_logical_rect((151, 151, 100, 100), 1.5), (100, 100, 68, 68))

    def test_no_border_when_disabled(self):
        hud, _ = self.make(border=False)

        hud._check_keys()

        self.assertIsNone(hud.border)

    def test_close_stops_capture_saves_state_and_removes_border(self):
        on_close = MagicMock()
        hud, cap = self.make(on_close=on_close)
        hud._sync_border()
        pieces = list(hud.border.windows)
        cap.stop_capture = MagicMock()

        hud.close()

        self.assertFalse(hud.is_open())
        cap.stop_capture.assert_called()
        on_close.assert_called_once()
        self.assertIn("capture_hud_pos", self.saved[-1])
        self.assertEqual(self.saved[-1]["event_pointer"], "(500, 400)")
        for piece in pieces:
            self.assertFalse(piece.isVisible())
        self.assertFalse(hud.close())  # second close is a no-op

    def test_escape_closes(self):
        hud, _ = self.make()

        QTest.keyClick(hud, Qt.Key.Key_Escape)

        self.assertFalse(hud.is_open())


class TestCaptureHudFlow(HudTestCase):
    def test_single_apply_hands_result_and_closes(self):
        on_apply = MagicMock()
        hud, cap = self.make(on_apply=on_apply)
        self.assertFalse(hud.btn_apply.isEnabled())
        self.ready(hud, cap)
        self.assertTrue(hud.btn_apply.isEnabled())

        QTest.mouseClick(hud.btn_apply, Qt.MouseButton.LeftButton)

        result = on_apply.call_args.args[0]
        self.assertIsInstance(result, CaptureResult)
        self.assertEqual(result.pixel, (10, 10))
        self.assertEqual(result.color, (255, 0, 255))
        self.assertFalse(hud.is_open())

    def test_info_shows_color_and_screen_point(self):
        hud, cap = self.make()

        self.ready(hud, cap)

        self.assertEqual(hud.lbl_info.text(), "255,0,255  (510, 410)")

    def test_return_in_hud_applies(self):
        on_apply = MagicMock()
        hud, cap = self.make(on_apply=on_apply)
        self.ready(hud, cap)

        QTest.keyClick(hud, Qt.Key.Key_Return)

        on_apply.assert_called_once()

    def test_return_in_advanced_input_commits_without_applying(self):
        on_apply = MagicMock()
        hud, cap = self.make(on_apply=on_apply)
        self.ready(hud, cap)
        hud._toggle_advanced()
        entry = hud.pos_entries[0]
        entry.setText("520")

        QTest.keyClick(entry, Qt.Key.Key_Return)

        on_apply.assert_not_called()
        self.assertEqual(cap.position, (520, 400))
        self.assertIn("CTRL", hud.lbl_status.text())

    def test_up_down_nudges_pixel_entry(self):
        hud, cap = self.make()
        self.ready(hud, cap)
        hud._toggle_advanced()

        QTest.keyClick(hud.pixel_entries[0], Qt.Key.Key_Up)

        self.assertEqual(hud.controller.session.selected_position, (11, 10))

    def test_name_return_commits_without_applying(self):
        on_apply = MagicMock()
        names: list[str] = []
        hud, cap = self.make(on_apply=on_apply, on_name_change=names.append, name="A")
        self.ready(hud, cap)

        QTest.keyClick(hud.entry_name, Qt.Key.Key_Return)

        on_apply.assert_not_called()
        self.assertEqual(names, ["A"])

    def test_preview_click_picks_pixel_after_freeze(self):
        hud, cap = self.make()
        cap.emit((0, 0, 255), ((20, 30), (9, 9, 9)))
        hud.capture()

        # +1 for the 1px frame around the image.
        QTest.mouseClick(
            hud.preview, Qt.MouseButton.LeftButton, pos=QPoint(21, 31)
        )

        self.assertEqual(hud.controller.session.selected_position, (20, 30))
        self.assertEqual(hud.controller.session.reference_color, (9, 9, 9))

    def test_capture_size_spin_updates_box(self):
        hud, cap = self.make()

        hud.size_spins[0].setValue(150)

        self.assertEqual(cap.size, (150, 100))
        self.assertEqual(hud.border.windows[0].width(), 154)

    def test_initial_capture_is_restored(self):
        initial = CaptureResult(
            position=(10, 20),
            capture_size=(120, 80),
            image=Image.new("RGB", (120, 80), (1, 2, 3)),
            pixel=(5, 6),
            color=(1, 2, 3),
        )
        hud, _ = self.make(initial=initial)

        self.assertTrue(hud.btn_apply.isEnabled())
        self.assertEqual([s.value() for s in hud.size_spins], [120, 80])

    def test_continuous_second_ctrl_saves_to_quick(self):
        hud, cap = self.make("continuous")
        cap.emit((0, 0, 255))
        self.keys["ctrl"] = True
        hud._check_keys()
        self.keys["ctrl"] = False
        hud._check_keys()
        hud.select((3, 4))
        self.keys["ctrl"] = True

        hud._check_keys()

        self.assertEqual(hud.saved_count, 1)
        self.assertIn("1 saved", hud.lbl_title.text())
        self.assertTrue((self.profiles / "Quick.json").exists())

    def test_ctrl_ignored_while_name_has_focus(self):
        hud, cap = self.make()
        cap.emit((0, 0, 255))
        self.keys["ctrl"] = True
        with patch("app.ui.capture_hud.text_input_has_focus", return_value=True):
            hud._check_keys()

        self.assertIsNone(hud.controller.session.held_image)

    def test_single_mode_opens_without_name_focus_so_ctrl_works(self):
        hud, cap = self.make(grab=True)
        QApplication.processEvents()

        self.assertIsNot(QApplication.focusWidget(), hud.entry_name)
        self.assertFalse(text_input_has_focus())
        cap.emit((0, 0, 255))
        self.keys["ctrl"] = True
        hud._check_keys()
        self.assertIsNotNone(hud.controller.session.held_image)

    def test_alt_moves_box_to_pointer_and_hud_steps_aside(self):
        hud, _ = self.make()
        hud.move(400, 300)
        self.keys["alt"] = True
        with patch("app.ui.capture_hud.QCursor.pos", return_value=QPoint(420, 320)):
            hud._check_keys()

        self.assertEqual(hud.controller.box()[:2], (420, 320))
        frame = hud.frameGeometry().getRect()
        self.assertFalse(rects_overlap(frame, hud.controller.box()))


class TestOpenQuickCapture(HudTestCase):
    def make_parent(self) -> QWidget:
        parent = QWidget()
        parent.quick_hud = None  # type: ignore[attr-defined]
        parent.profiles_dir = self.profiles  # type: ignore[attr-defined]
        parent.update_ui = MagicMock()  # type: ignore[attr-defined]
        self.addCleanup(parent.deleteLater)
        return parent

    def test_opens_once_and_clears_slot_on_close(self):
        parent = self.make_parent()
        with patch(
            "app.engine.capture_session.ScreenshotCapturer", FakeCapturer
        ):
            open_quick_capture(parent)
            hud = parent.quick_hud  # type: ignore[attr-defined]
            self.assertIsInstance(hud, CaptureHud)
            self.assertEqual(hud.mode, "continuous")

            open_quick_capture(parent)
            self.assertIs(parent.quick_hud, hud)  # type: ignore[attr-defined]

            hud.close()

        self.assertIsNone(parent.quick_hud)  # type: ignore[attr-defined]
        parent.update_ui.assert_called_once()  # type: ignore[attr-defined]
        self.assertTrue((self.profiles / "Quick.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
