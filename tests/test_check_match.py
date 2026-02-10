import unittest

import numpy as np

from keystroke_processor import KeystrokeProcessor


def _make_processor_stub() -> KeystrokeProcessor:
    return KeystrokeProcessor.__new__(KeystrokeProcessor)


class TestCheckMatchPixelMode(unittest.TestCase):
    """_check_match: 픽셀 모드 테스트"""

    def setUp(self):
        self.proc = _make_processor_stub()

    def test_pixel_exact_match(self):
        """픽셀이 ref_bgr과 정확히 일치하면 True"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[3, 5] = [255, 0, 0]
        evt = {
            "mode": "pixel",
            "rel_x": 5,
            "rel_y": 3,
            "ref_bgr": np.array([255, 0, 0], dtype=np.uint8),
            "invert": False,
        }
        self.assertTrue(self.proc._check_match(img, evt, is_independent=False))

    def test_pixel_mismatch(self):
        """픽셀이 ref_bgr과 다르면 False"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        evt = {
            "mode": "pixel",
            "rel_x": 5,
            "rel_y": 3,
            "ref_bgr": np.array([255, 0, 0], dtype=np.uint8),
            "invert": False,
        }
        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))

    def test_pixel_invert_match_becomes_false(self):
        """invert=True: 실제 일치 시 False 반환"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[3, 5] = [255, 0, 0]
        evt = {
            "mode": "pixel",
            "rel_x": 5,
            "rel_y": 3,
            "ref_bgr": np.array([255, 0, 0], dtype=np.uint8),
            "invert": True,
        }
        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))

    def test_pixel_invert_mismatch_becomes_true(self):
        """invert=True: 실제 불일치 시 True 반환"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        evt = {
            "mode": "pixel",
            "rel_x": 5,
            "rel_y": 3,
            "ref_bgr": np.array([255, 0, 0], dtype=np.uint8),
            "invert": True,
        }
        self.assertTrue(self.proc._check_match(img, evt, is_independent=False))

    def test_pixel_out_of_bounds_returns_false(self):
        """좌표가 이미지 범위 밖이면 False"""
        img = np.zeros((5, 5, 3), dtype=np.uint8)
        evt = {
            "mode": "pixel",
            "rel_x": 10,
            "rel_y": 10,
            "ref_bgr": np.array([0, 0, 0], dtype=np.uint8),
            "invert": False,
        }
        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))

    def test_pixel_out_of_bounds_invert_still_false(self):
        """좌표가 범위 밖이면 invert와 무관하게 False (evaluated=False이므로 invert 미적용)"""
        img = np.zeros((5, 5, 3), dtype=np.uint8)
        evt = {
            "mode": "pixel",
            "rel_x": 10,
            "rel_y": 10,
            "ref_bgr": np.array([0, 0, 0], dtype=np.uint8),
            "invert": True,
        }
        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))

    def test_pixel_independent_mode_uses_origin(self):
        """독립 모드에서는 img[0,0]을 사용"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[0, 0] = [100, 200, 50]
        evt = {
            "mode": "pixel",
            "rel_x": 99,
            "rel_y": 99,
            "ref_bgr": np.array([100, 200, 50], dtype=np.uint8),
            "invert": False,
        }
        self.assertTrue(self.proc._check_match(img, evt, is_independent=True))


class TestCheckMatchRegionMode(unittest.TestCase):
    """_check_match: 영역 모드 테스트"""

    def setUp(self):
        self.proc = _make_processor_stub()

    def test_region_all_checkpoints_match(self):
        """모든 체크포인트 색상이 일치하면 True"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[3:7, 3:7] = [10, 20, 30]
        evt = {
            "mode": "region",
            "rel_x": 5,
            "rel_y": 5,
            "region_w": 4,
            "region_h": 4,
            "invert": False,
            "check_points": [
                {"pos": (0, 0), "color": np.array([10, 20, 30], dtype=np.uint8)},
                {"pos": (3, 3), "color": np.array([10, 20, 30], dtype=np.uint8)},
            ],
        }
        self.assertTrue(self.proc._check_match(img, evt, is_independent=False))

    def test_region_checkpoint_mismatch(self):
        """체크포인트 중 하나라도 다르면 False"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[3:7, 3:7] = [10, 20, 30]
        evt = {
            "mode": "region",
            "rel_x": 5,
            "rel_y": 5,
            "region_w": 4,
            "region_h": 4,
            "invert": False,
            "check_points": [
                {"pos": (0, 0), "color": np.array([10, 20, 30], dtype=np.uint8)},
                {"pos": (1, 1), "color": np.array([99, 99, 99], dtype=np.uint8)},
            ],
        }
        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))

    def test_region_invert_all_match_becomes_false(self):
        """invert=True + 모든 체크포인트 일치 → False"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[3:7, 3:7] = [10, 20, 30]
        evt = {
            "mode": "region",
            "rel_x": 5,
            "rel_y": 5,
            "region_w": 4,
            "region_h": 4,
            "invert": True,
            "check_points": [
                {"pos": (0, 0), "color": np.array([10, 20, 30], dtype=np.uint8)},
            ],
        }
        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))

    def test_region_invert_mismatch_becomes_true(self):
        """invert=True + 체크포인트 불일치 → True"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[3:7, 3:7] = [10, 20, 30]
        evt = {
            "mode": "region",
            "rel_x": 5,
            "rel_y": 5,
            "region_w": 4,
            "region_h": 4,
            "invert": True,
            "check_points": [
                {"pos": (0, 0), "color": np.array([99, 99, 99], dtype=np.uint8)},
            ],
        }
        self.assertTrue(self.proc._check_match(img, evt, is_independent=False))

    def test_region_out_of_bounds_returns_false(self):
        """ROI가 이미지 범위를 벗어나면 False"""
        img = np.zeros((5, 5, 3), dtype=np.uint8)
        evt = {
            "mode": "region",
            "rel_x": 3,
            "rel_y": 3,
            "region_w": 10,
            "region_h": 10,
            "invert": False,
            "check_points": [],
        }
        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))

    def test_region_no_checkpoints_matches(self):
        """체크포인트가 비어 있으면 for-else에 의해 True"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        evt = {
            "mode": "region",
            "rel_x": 5,
            "rel_y": 5,
            "region_w": 4,
            "region_h": 4,
            "invert": False,
            "check_points": [],
        }
        self.assertTrue(self.proc._check_match(img, evt, is_independent=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
