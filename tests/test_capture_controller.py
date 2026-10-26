import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from app.domain.capture_geometry import CaptureResult
from app.domain.models import EventModel, ProfileModel
from app.presenters.capture_controller import (
    PERMISSION_POLL_TICKS,
    CaptureController,
)
from app.storage.profile_storage import load_profile, save_profile
from app.utils.i18n import set_language


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


class Keys:
    """주입하는 전역 키 상태."""

    def __init__(self):
        self.alt = False
        self.ctrl = False


def make_controller(mode="single", *, profiles_dir=None, keys=None, pointer=(0, 0), **kw):
    capturer = FakeCapturer()
    keys = keys or Keys()
    point = {"value": pointer}
    controller = CaptureController(
        mode=mode,
        pointer=lambda: point["value"],
        capturer=capturer,
        profiles_dir=profiles_dir,
        on_apply=MagicMock(),
        close=MagicMock(),
        alt_pressed=lambda: keys.alt,
        ctrl_pressed=lambda: keys.ctrl,
        permission=kw.pop("permission", lambda: None),
        **kw,
    )
    controller.start()
    return controller, capturer, keys, point


class TestCaptureFlow(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_capture_keeps_pick_inside_new_frame_and_updates_color(self):
        c, cap, _keys, _pt = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.select((3, 4))
        cap.emit((0, 255, 0))

        c.capture()

        self.assertEqual(c.session.selected_position, (3, 4))
        self.assertEqual(c.session.reference_color, (0, 255, 0))

    def test_capture_without_frame_warns(self):
        c, *_ = make_controller()

        c.capture()

        self.assertEqual(c.status()[1], "warn")
        self.assertIn("ALT", c.status()[0])

    def test_single_mode_ctrl_always_captures(self):
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.select((3, 4))
        c.capture = MagicMock()

        c.on_ctrl()

        c.capture.assert_called_once()
        c.on_apply.assert_not_called()

    def test_moved_area_stays_live_until_frozen(self):
        """ALT로 옮긴 뒤 떼도 새 위치를 보여 주고, CTRL 전에는 적용을 거부한다."""
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.select((3, 4))
        self.assertFalse(c.shows_live())

        c.session.set_position((900, 700))  # ALT move, then released
        cap.emit((0, 255, 0))

        self.assertTrue(c.shows_live())
        self.assertEqual(c.displayed_image().getpixel((0, 0)), (0, 255, 0))
        self.assertEqual(c.status()[0], "Press CTRL to freeze this area.")
        c.apply()
        c.on_apply.assert_not_called()

        c.capture()
        c.apply()

        result = c.on_apply.call_args.args[0]
        self.assertEqual(result.position, (900, 700))
        self.assertEqual(result.color, (0, 255, 0))

    def test_single_mode_apply_hands_result_and_closes(self):
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.select((3, 4))

        c.apply()

        result = c.on_apply.call_args.args[0]
        self.assertIsInstance(result, CaptureResult)
        self.assertEqual(result.position, (500, 400))
        self.assertEqual(result.pixel, (3, 4))
        self.assertEqual(result.color, (0, 0, 255))
        self.assertEqual(result.capture_size, (100, 100))
        c._close.assert_called_once()

    def test_apply_without_pick_warns(self):
        c, *_ = make_controller()

        c.apply()

        c.on_apply.assert_not_called()
        self.assertIn("CTRL", c.feedback[0])
        self.assertEqual(c.feedback[1], "warn")

    def test_held_capture_size_survives_size_change(self):
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.select((3, 4))

        self.assertEqual(c.set_capture_size(10, 5000), (50, 1000))

        self.assertEqual(c.result().capture_size, (100, 100))

    def test_recapture_clears_hold(self):
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.select((3, 4))

        c.recapture()

        self.assertFalse(c.is_ready())
        self.assertIsNone(c.mag_center)


class TestRestore(unittest.TestCase):
    def test_initial_capture_is_shown_held_with_its_pick(self):
        c, cap, *_ = make_controller()
        initial = CaptureResult(
            position=(10, 20),
            capture_size=(120, 80),
            image=Image.new("RGB", (120, 80), (1, 2, 3)),
            pixel=(5, 6),
            color=(1, 2, 3),
        )

        c.restore(initial)

        self.assertTrue(c.is_ready())
        self.assertFalse(c.shows_live())
        self.assertEqual(c.capture_size, (120, 80))
        self.assertEqual(cap.position, (10, 20))
        self.assertEqual(c.mag_center, (5, 6))
        self.assertEqual(c.info(), ((1, 2, 3), (15, 26)))


class TestPreviewInput(unittest.TestCase):
    def test_preview_click_is_ignored_while_live(self):
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))

        self.assertFalse(c.click_preview((3, 4), (100, 100)))

        c.capture()
        self.assertTrue(c.click_preview((3, 4), (100, 100)))
        self.assertEqual(c.session.selected_position, (3, 4))
        self.assertEqual(c.mag_center, (3, 4))

    def test_magnifier_click_keeps_center(self):
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.click_preview((50, 50), (100, 100))

        self.assertTrue(c.click_magnifier((0, 0)))

        self.assertEqual(c.session.selected_position, (45, 45))
        self.assertEqual(c.mag_center, (50, 50))

    def test_hover_moves_magnifier_and_leave_returns_to_pick(self):
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.click_preview((10, 10), (100, 100))

        self.assertTrue(c.hover_preview((70, 70), (100, 100)))
        self.assertEqual(c.mag_center, (70, 70))
        self.assertTrue(c.leave_preview())
        self.assertEqual(c.mag_center, (10, 10))

    def test_pixel_entry_selects_once(self):
        c, cap, *_ = make_controller()
        cap.emit((0, 0, 255))
        c.capture()

        self.assertTrue(c.set_pixel((7, 8)))
        self.assertFalse(c.set_pixel((7, 8)))


class TestTick(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_alt_follows_pointer_but_does_not_change_the_hold(self):
        """UI 정책 2: ALT로 옮긴 위치는 CTRL로 고정하기 전까지 적용되지 않는다."""
        c, cap, keys, pt = make_controller()
        cap.emit((0, 0, 255))
        c.capture()
        c.select((3, 4))

        keys.alt = True
        pt["value"] = (800, 600)
        update = c.tick(text_focus=False)

        self.assertTrue(update.render and update.info)
        self.assertEqual(c.box(), (800, 600, 100, 100))
        self.assertTrue(c.shows_live())
        self.assertEqual(c.session.held_position, (500, 400))

        keys.alt = False
        c.tick(text_focus=False)
        c.apply()
        c.on_apply.assert_not_called()

        cap.emit((0, 255, 0))
        keys.ctrl = True
        c.tick(text_focus=False)
        self.assertEqual(c.session.held_position, (800, 600))

    def test_alt_press_clears_feedback(self):
        c, _cap, keys, _pt = make_controller()
        c.apply()
        self.assertIsNotNone(c.feedback)

        keys.alt = True
        c.tick(text_focus=False)

        self.assertIsNone(c.feedback)

    def test_ctrl_is_edge_triggered(self):
        c, _cap, keys, _pt = make_controller()
        c.on_ctrl = MagicMock()
        keys.ctrl = True

        c.tick(text_focus=False)
        c.tick(text_focus=False)

        c.on_ctrl.assert_called_once()

    def test_ctrl_is_ignored_while_typing(self):
        c, _cap, keys, _pt = make_controller()
        c.on_ctrl = MagicMock()
        keys.ctrl = True

        c.tick(text_focus=True)
        c.on_ctrl.assert_not_called()

        keys.ctrl = False
        c.tick(text_focus=False)
        keys.ctrl = True
        c.tick(text_focus=False)
        c.on_ctrl.assert_called_once()

    def test_permission_is_rechecked_every_poll_period(self):
        calls = []

        def permission():
            calls.append(1)
            return "missing" if len(calls) > 1 else None

        c, *_ = make_controller(permission=permission)

        updates = [c.tick(text_focus=False) for _ in range(PERMISSION_POLL_TICKS)]

        self.assertEqual(len(calls), 2)
        self.assertTrue(updates[-1].status)
        self.assertFalse(any(u.status for u in updates[:-1]))
        self.assertEqual(c.status(), ("missing", "warn"))


class TestContinuous(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_second_ctrl_saves_held_frame_not_a_new_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof_dir = Path(tmp)
            c, cap, keys, _pt = make_controller("continuous", profiles_dir=prof_dir)
            cap.emit((0, 0, 255))
            keys.ctrl = True
            c.tick(text_focus=False)  # first CTRL: freeze
            keys.ctrl = False
            c.tick(text_focus=False)
            c.select((3, 4))
            cap.emit((255, 0, 0))  # the live frame changes afterwards

            keys.ctrl = True
            c.tick(text_focus=False)  # second CTRL: apply

            saved = load_profile(prof_dir, "Quick", migrate=False).event_list
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].held_screenshot.getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(saved[0].ref_pixel_value[:3], (0, 0, 255))
        self.assertEqual(c.saved_count, 1)
        self.assertIsNone(c.session.held_image)
        self.assertEqual(c.feedback[1], "ready")
        self.assertIn("1 saved", c.title())

    def test_open_workspace_takes_the_event_instead_of_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof_dir = Path(tmp)
            append = MagicMock(return_value="7")
            c, cap, keys, _pt = make_controller(
                "continuous", profiles_dir=prof_dir, append_quick=append
            )
            cap.emit((0, 0, 255))
            keys.ctrl = True
            c.tick(text_focus=False)
            keys.ctrl = False
            c.tick(text_focus=False)
            c.select((3, 4))
            keys.ctrl = True
            c.tick(text_focus=False)

            saved = load_profile(prof_dir, "Quick", migrate=False).event_list
        append.assert_called_once()
        self.assertEqual(saved, [])
        self.assertIn("'7'", c.feedback[0])
        self.assertIn("open workspace", c.feedback[0])

    def test_ctrl_after_moving_recaptures(self):
        c, cap, *_ = make_controller("continuous", profiles_dir=None)
        cap.emit((0, 0, 255))
        c.on_ctrl()
        c.select((3, 4))
        c.session.set_position((600, 400))
        c.apply = MagicMock()

        c.on_ctrl()

        c.apply.assert_not_called()
        self.assertEqual(c.session.held_position, (500, 400))

    def test_quick_events_number_on_after_existing_ones(self):
        """UI 정책 4: Quick 뒤에 자동 번호로 추가만 한다. 기존 이벤트와 키는 남는다."""
        with tempfile.TemporaryDirectory() as tmp:
            prof_dir = Path(tmp)
            save_profile(
                prof_dir,
                ProfileModel(
                    name="Quick",
                    event_list=[EventModel(event_name="3", key_to_enter="Q")],
                ),
                name="Quick",
            )
            c, cap, *_ = make_controller("continuous", profiles_dir=prof_dir)
            for color in ((0, 0, 255), (0, 255, 0)):
                cap.emit(color)
                c.capture()
                c.select((1, 1))
                c.apply()

            saved = load_profile(prof_dir, "Quick", migrate=False).event_list
        self.assertEqual([e.event_name for e in saved], ["3", "4", "5"])
        self.assertEqual(saved[0].key_to_enter, "Q")
        self.assertEqual(c.saved_count, 2)

    def test_continuous_creates_quick_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_controller("continuous", profiles_dir=Path(tmp))

            self.assertTrue((Path(tmp) / "Quick.json").exists())


class TestHudPlacementAndState(unittest.TestCase):
    def test_hud_target_moves_away_from_box(self):
        c, *_ = make_controller()  # box (500, 400, 100, 100)

        self.assertIsNone(c.hud_target((0, 0, 260, 330), (1920, 1080)))
        self.assertEqual(
            c.hud_target((450, 350, 260, 330), (1920, 1080)),
            (1920 - 260 - 16, 1080 - 330 - 16),
        )

    @patch("app.presenters.capture_controller.StateUtils.save_main_app_state")
    def test_save_state_uses_existing_keys(self, save):
        single, *_ = make_controller("single")
        single.save_state((12, 34))
        save.assert_called_with(capture_hud_pos="12/34", event_pointer="(500, 400)")

        quick, *_ = make_controller("continuous")
        quick.save_state((1, 2))
        save.assert_called_with(capture_hud_pos="1/2", quick_ptr="(500, 400)")

    @patch(
        "app.presenters.capture_controller.StateUtils.load_main_app_state",
        return_value={"capture_hud_pos": "30/40", "event_pointer": "(70, 80)"},
    )
    def test_load_state_restores_pointer_only_when_asked(self, _load):
        c, cap, *_ = make_controller()

        self.assertEqual(c.load_state(restore_pointer=False), (30, 40))
        self.assertEqual(cap.position, (500, 400))
        self.assertEqual(c.load_state(restore_pointer=True), (30, 40))
        self.assertEqual(cap.position, (70, 80))


if __name__ == "__main__":
    unittest.main(verbosity=2)
