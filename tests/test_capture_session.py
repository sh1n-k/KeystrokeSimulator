import unittest

from PIL import Image

from app.ui.capture_session import CaptureSession


class FakeCapturer:
    def __init__(self) -> None:
        self.screenshot_callback = None
        self.capture_thread = None
        self.position = (0, 0)
        self.size = (100, 100)
        self.started = False

    def start_capture(self) -> None:
        self.started = True

    def stop_capture(self) -> None:
        self.started = False

    def set_capture_size(self, width: int, height: int) -> None:
        self.size = (width, height)

    def set_mouse_position(self, position: tuple[int, int]) -> None:
        self.position = position

    def set_current_mouse_position(self, position: tuple[int, int]) -> None:
        self.position = position

    def get_current_mouse_position(self) -> tuple[int, int]:
        return self.position


class TestCaptureSession(unittest.TestCase):
    def setUp(self) -> None:
        self.capturer = FakeCapturer()
        self.session = CaptureSession(self.capturer)

    def test_capture_callback_only_updates_session_state(self) -> None:
        self.session.start()
        image = Image.new("RGB", (10, 10), "red")

        assert self.capturer.screenshot_callback is not None
        self.capturer.screenshot_callback((3, 4), image)

        snapshot = self.session.snapshot()
        self.assertEqual(snapshot.latest_position, (3, 4))
        self.assertIs(snapshot.latest_image, image)
        self.assertEqual(snapshot.generation, 1)

    def test_hold_and_select_scale_display_coordinates(self) -> None:
        self.session.start()
        image = Image.new("RGB", (20, 10), "blue")
        assert self.capturer.screenshot_callback is not None
        self.capturer.screenshot_callback((1, 2), image)

        self.assertTrue(self.session.hold())
        self.assertTrue(self.session.select((50, 25), (100, 50)))

        snapshot = self.session.snapshot()
        self.assertEqual(snapshot.selected_position, (10, 5))
        self.assertEqual(snapshot.reference_color, (0, 0, 255))

    def test_held_position_stays_with_held_frame(self) -> None:
        self.session.start()
        assert self.capturer.screenshot_callback is not None
        self.capturer.screenshot_callback((1, 2), Image.new("RGB", (4, 4), "red"))
        self.session.hold()

        self.capturer.screenshot_callback((8, 9), Image.new("RGB", (4, 4), "blue"))

        self.assertEqual(self.session.held_position, (1, 2))
        assert self.session.held_image is not None
        self.assertEqual(self.session.held_image.getpixel((0, 0)), (255, 0, 0))

    def test_restored_held_image_keeps_restored_position(self) -> None:
        self.session.latest_position = (4, 5)
        self.session.held_image = Image.new("RGB", (2, 2))
        self.session.latest_position = (8, 9)

        self.assertEqual(self.session.held_position, (4, 5))

    def test_stop_invalidates_late_callbacks(self) -> None:
        self.session.start()
        callback = self.capturer.screenshot_callback
        self.session.stop()
        assert callback is not None

        callback((9, 9), Image.new("RGB", (2, 2)))

        self.assertEqual(self.session.snapshot().generation, 0)
        self.assertIsNone(self.capturer.screenshot_callback)

    def test_capture_size_is_clamped_at_session_boundary(self) -> None:
        self.assertEqual(self.session.set_capture_size(1, 2000), (50, 1000))
        self.assertEqual(self.capturer.size, (50, 1000))


if __name__ == "__main__":
    unittest.main()
