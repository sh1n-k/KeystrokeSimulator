import unittest
from unittest.mock import patch, MagicMock

from keystroke_capturer import ScreenshotCapturer


class TestSetCaptureSize(unittest.TestCase):
    """set_capture_size() 기능 테스트"""

    def _make_capturer(self, screen_w=1920, screen_h=1080):
        monitor = MagicMock()
        monitor.width = screen_w
        monitor.height = screen_h
        with patch("keystroke_capturer.screeninfo.get_monitors", return_value=[monitor]):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
