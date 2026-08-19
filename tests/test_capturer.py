import time
import unittest
from unittest.mock import patch, MagicMock

from app.core.capturer import ScreenshotCapturer
from tests.helpers import make_image_frame


class TestSetCaptureSize(unittest.TestCase):
    """set_capture_size() 기능 테스트"""

    def _make_capturer(self, screen_w=1920, screen_h=1080):
        with patch(
            "app.core.capturer.MonitorUtils.get_primary_size",
            return_value=(screen_w, screen_h),
        ):
            return ScreenshotCapturer()

    def test_default_box_size(self):
        """기본값은 100×100"""
        capturer = self._make_capturer()
        self.assertEqual(capturer.box_w, 100)
        self.assertEqual(capturer.box_h, 100)

    def test_set_capture_size_normal(self):
        """set_capture_size로 크기 변경"""
        capturer = self._make_capturer()
        capturer.set_capture_size(300, 200)
        self.assertEqual(capturer.box_w, 300)
        self.assertEqual(capturer.box_h, 200)

    def test_set_capture_size_minimum_clamp(self):
        """0 이하 값은 1로 클램핑"""
        capturer = self._make_capturer()
        capturer.set_capture_size(0, -5)
        self.assertEqual(capturer.box_w, 1)
        self.assertEqual(capturer.box_h, 1)

    def test_set_capture_size_one(self):
        """최솟값 1"""
        capturer = self._make_capturer()
        capturer.set_capture_size(1, 1)
        self.assertEqual(capturer.box_w, 1)
        self.assertEqual(capturer.box_h, 1)

    def test_boundary_check_uses_box_w_h(self):
        """경계 검사: screen_width - box_w 기준"""
        capturer = self._make_capturer(screen_w=1920, screen_h=1080)
        capturer.set_capture_size(500, 300)

        # 유효 위치: x+500=1919 < 1920, y+300=1079 < 1080 → 통과
        capturer.set_current_mouse_position((1419, 779))
        self.assertEqual(capturer.current_position, (1419, 779))

        # 경계 초과: x + box_w = 1920 >= 1920 → 무시
        before = capturer.current_position
        capturer.set_current_mouse_position((1420, 779))  # 1420 + 500 = 1920 >= 1920
        self.assertEqual(capturer.current_position, before)

    def test_boundary_check_y_axis(self):
        """경계 검사: y축 box_h 기준"""
        capturer = self._make_capturer(screen_w=1920, screen_h=1080)
        capturer.set_capture_size(100, 400)

        # 유효: y + box_h = 679 + 400 = 1079 < 1080
        capturer.set_current_mouse_position((100, 679))
        self.assertEqual(capturer.current_position, (100, 679))

        # 경계 초과: y + box_h = 680 + 400 = 1080 >= 1080
        before = capturer.current_position
        capturer.set_current_mouse_position((100, 680))
        self.assertEqual(capturer.current_position, before)

    def test_set_capture_size_large(self):
        """대형 캡처 크기 설정 (1000×1000)"""
        capturer = self._make_capturer()
        capturer.set_capture_size(1000, 1000)
        self.assertEqual(capturer.box_w, 1000)
        self.assertEqual(capturer.box_h, 1000)

    def test_asymmetric_size(self):
        """너비와 높이가 다른 비대칭 크기"""
        capturer = self._make_capturer()
        capturer.set_capture_size(300, 150)
        self.assertEqual(capturer.box_w, 300)
        self.assertEqual(capturer.box_h, 150)


class TestCapturerAttributes(unittest.TestCase):
    """ScreenshotCapturer: 속성 초기화 및 접근"""

    def _make_capturer(self, screen_w=1920, screen_h=1080):
        with patch(
            "app.core.capturer.MonitorUtils.get_primary_size",
            return_value=(screen_w, screen_h),
        ):
            return ScreenshotCapturer()

    def test_screenshot_callback_settable(self):
        """screenshot_callback 설정 가능"""
        capturer = self._make_capturer()

        def cb(pos, img):
            return None

        capturer.screenshot_callback = cb
        self.assertIs(capturer.screenshot_callback, cb)

    def test_current_position_initial(self):
        """current_position 초기값은 (0, 0)"""
        capturer = self._make_capturer()
        self.assertEqual(capturer.current_position, (0, 0))

    def test_get_current_mouse_position_type(self):
        """get_current_mouse_position() 반환 타입"""
        capturer = self._make_capturer()
        pos = capturer.get_current_mouse_position()
        self.assertIsInstance(pos, tuple)
        self.assertEqual(len(pos), 2)

    def test_capture_screenshot_keeps_grabbing_when_position_is_unchanged(self):
        capturer = self._make_capturer()
        capturer.current_position = (10, 10)
        capturer.screenshot_callback = MagicMock(
            side_effect=lambda *_: capturer.capturing.clear()
        )
        capturer.capturing.set()

        frame = make_image_frame(10, 10, channels=4)
        backend = MagicMock()
        backend.is_dead.return_value = False
        backend.grab.return_value = [frame]

        with (
            patch("app.core.capturer.open_screen_backend", return_value=backend),
            patch("app.core.capturer.time.sleep", return_value=None),
        ):
            capturer._last_capture_signature = (
                (10, 10),
                capturer.box_w,
                capturer.box_h,
            )
            capturer._idle_cycles = 5
            capturer.capture_screenshot()

        backend.grab.assert_called_once()
        capturer.screenshot_callback.assert_called_once()
        backend.close.assert_called_once()
        _pos, image = capturer.screenshot_callback.call_args[0]
        self.assertEqual(image.size, (10, 10))

    def test_preview_uses_the_same_backend_as_the_run_loop(self):
        """편집기 기준색과 실행 매칭이 어긋나지 않으려면 캡처 경로가 같아야 한다."""
        capturer = self._make_capturer()
        capturer.capturing.set()
        capturer.screenshot_callback = MagicMock(
            side_effect=lambda *_: capturer.capturing.clear()
        )
        backend = MagicMock()
        backend.is_dead.return_value = False
        backend.grab.return_value = [make_image_frame(4, 4, channels=4)]

        with (
            patch(
                "app.core.capturer.open_screen_backend", return_value=backend
            ) as opener,
            patch("app.core.capturer.time.sleep", return_value=None),
        ):
            capturer.capture_screenshot()

        opener.assert_called_once()
        (groups,) = opener.call_args[0]
        self.assertEqual(
            groups[0]["rect"],
            {
                "left": 0,
                "top": 0,
                "width": capturer.screen_width,
                "height": capturer.screen_height,
            },
        )

    def test_preview_uses_the_lower_preview_fps(self):
        """전체 화면을 스트리밍하므로 실행 루프와 같은 fps는 낭비다."""
        from app.core.screen_backend import PREVIEW_STREAM_FPS

        capturer = self._make_capturer()
        capturer.capturing.set()
        capturer.screenshot_callback = MagicMock(
            side_effect=lambda *_: capturer.capturing.clear()
        )
        backend = MagicMock()
        backend.is_dead.return_value = False
        backend.grab.return_value = [make_image_frame(4, 4, channels=4)]

        with (
            patch(
                "app.core.capturer.open_screen_backend", return_value=backend
            ) as opener,
            patch("app.core.capturer.time.sleep", return_value=None),
        ):
            capturer.capture_screenshot()

        self.assertEqual(opener.call_args.kwargs["fps"], PREVIEW_STREAM_FPS)
        self.assertLess(PREVIEW_STREAM_FPS, 30)

    def test_capture_group_keeps_the_requested_coordinates(self):
        """미리보기 좌표를 보정하면 저장되는 기준 좌표와 어긋난다."""
        capturer = self._make_capturer()
        capturer.set_capture_size(100, 100)

        group = capturer._capture_group((-50, -50))

        self.assertEqual(
            group["rect"], {"left": -50, "top": -50, "width": 100, "height": 100}
        )

    def test_reopen_interval_starts_after_the_attempt(self):
        """실패 경로가 수 초 걸려도 스로틀이 무력화되면 안 된다."""
        capturer = self._make_capturer()
        dead = MagicMock()
        dead.is_dead.return_value = True

        def slow_open(_groups):
            time.sleep(0.05)
            return dead

        with patch(
            "app.core.capturer.open_screen_backend", side_effect=slow_open
        ) as opener:
            backend, first = capturer._reopen(dead, 0.0)
            capturer._reopen(backend, first)

        self.assertEqual(opener.call_count, 1)
        self.assertGreater(first, 0.0)

    def test_dead_backend_is_reopened(self):
        capturer = self._make_capturer()
        capturer.current_position = (10, 10)
        capturer.capturing.set()
        capturer.screenshot_callback = MagicMock(
            side_effect=lambda *_: capturer.capturing.clear()
        )
        dead = MagicMock()
        dead.is_dead.return_value = True
        dead.grab.return_value = [None]
        fresh = MagicMock()
        fresh.is_dead.return_value = False
        fresh.grab.return_value = [make_image_frame(4, 4, channels=4)]

        with (
            patch(
                "app.core.capturer.open_screen_backend", side_effect=[dead, fresh]
            ) as opener,
            patch("app.core.capturer.time.sleep", return_value=None),
        ):
            capturer.capture_screenshot()

        self.assertEqual(opener.call_count, 2)
        dead.close.assert_called()
        capturer.screenshot_callback.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
