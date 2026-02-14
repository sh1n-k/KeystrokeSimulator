import unittest

import numpy as np

from keystroke_processor import KeystrokeProcessor


def _make_processor_stub() -> KeystrokeProcessor:
    return KeystrokeProcessor.__new__(KeystrokeProcessor)


class TestExtractROI(unittest.TestCase):
    """_extract_roi: 이미지에서 관심 영역 추출"""

    def setUp(self):
        self.proc = _make_processor_stub()

    def test_normal_extraction(self):
        """정상 좌표에서 ROI가 올바르게 추출됨"""
        img = np.arange(100 * 100 * 4, dtype=np.uint8).reshape(100, 100, 4)
        evt = {"region_w": 10, "region_h": 10, "rel_x": 50, "rel_y": 50}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNotNone(roi)
        self.assertEqual(roi.shape, (10, 10, 3))  # 알파 채널 제거됨

    def test_roi_pixel_values(self):
        """ROI의 픽셀 값이 원본 이미지와 일치"""
        img = np.zeros((20, 20, 3), dtype=np.uint8)
        img[5:15, 5:15] = [100, 200, 50]
        evt = {"region_w": 10, "region_h": 10, "rel_x": 10, "rel_y": 10}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNotNone(roi)
        np.testing.assert_array_equal(roi[0, 0], [100, 200, 50])

    def test_out_of_bounds_returns_none(self):
        """ROI가 이미지 범위를 벗어나면 None 반환"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        evt = {"region_w": 20, "region_h": 20, "rel_x": 5, "rel_y": 5}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNone(roi)

    def test_negative_start_returns_none(self):
        """ROI 시작점이 음수면 None 반환"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        evt = {"region_w": 10, "region_h": 10, "rel_x": 2, "rel_y": 2}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNone(roi)

    def test_exact_boundary_fit(self):
        """ROI가 이미지 경계에 정확히 맞는 경우"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        # w=4, h=4, rel_x=7, rel_y=7 → x=7-2=5, y=7-2=5, 5+4=9 ≤ 10
        evt = {"region_w": 4, "region_h": 4, "rel_x": 7, "rel_y": 7}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNotNone(roi)
        self.assertEqual(roi.shape, (4, 4, 3))

    def test_boundary_exceeded_by_one(self):
        """ROI가 이미지 경계를 1픽셀 초과하면 None"""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        # w=4, h=4, rel_x=8, rel_y=8 → x=8-2=6, y=8-2=6, 6+4=10 ≤ 10 → OK
        # w=4, h=4, rel_x=9, rel_y=9 → x=9-2=7, y=9-2=7, 7+4=11 > 10 → None
        evt = {"region_w": 4, "region_h": 4, "rel_x": 9, "rel_y": 9}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNone(roi)

    def test_independent_mode_returns_full_image(self):
        """독립 모드에서는 전체 이미지를 반환 (알파 채널 제거)"""
        img = np.ones((10, 10, 4), dtype=np.uint8) * 128
        evt = {"region_w": 5, "region_h": 5, "rel_x": 99, "rel_y": 99}

        roi = self.proc._extract_roi(img, evt, is_independent=True)

        self.assertIsNotNone(roi)
        self.assertEqual(roi.shape, (10, 10, 3))

    def test_independent_mode_3_channel_image(self):
        """독립 모드: 3채널 이미지도 정상 처리"""
        img = np.ones((5, 5, 3), dtype=np.uint8) * 50
        evt = {"region_w": 2, "region_h": 2, "rel_x": 0, "rel_y": 0}

        roi = self.proc._extract_roi(img, evt, is_independent=True)

        self.assertEqual(roi.shape, (5, 5, 3))


class TestBuildCaptureRect(unittest.TestCase):
    """_build_capture_rect: 독립 이벤트 캡처 영역 생성"""

    def setUp(self):
        self.proc = _make_processor_stub()

    def test_pixel_mode_single_pixel_rect(self):
        """픽셀 모드: 1x1 캡처 영역"""
        evt = {"center_x": 100, "center_y": 200, "mode": "pixel"}
        rect = self.proc._build_capture_rect(evt)

        self.assertEqual(rect, {
            "top": 200,
            "left": 100,
            "width": 1,
            "height": 1,
        })

    def test_region_mode_centered_rect(self):
        """영역 모드: 중심점 기준 영역"""
        evt = {
            "center_x": 100,
            "center_y": 200,
            "mode": "region",
            "region_w": 20,
            "region_h": 30,
        }
        rect = self.proc._build_capture_rect(evt)

        self.assertEqual(rect, {
            "top": 200 - 15,  # cy - h//2
            "left": 100 - 10,  # cx - w//2
            "width": 20,
            "height": 30,
        })

    def test_region_mode_odd_size(self):
        """영역 모드: 홀수 크기"""
        evt = {
            "center_x": 50,
            "center_y": 50,
            "mode": "region",
            "region_w": 11,
            "region_h": 7,
        }
        rect = self.proc._build_capture_rect(evt)

        self.assertEqual(rect["left"], 50 - 5)   # 11 // 2 = 5
        self.assertEqual(rect["top"], 50 - 3)    # 7 // 2 = 3
        self.assertEqual(rect["width"], 11)
        self.assertEqual(rect["height"], 7)

    def test_pixel_mode_at_origin(self):
        """픽셀 모드: 좌표 (0, 0)"""
        evt = {"center_x": 0, "center_y": 0, "mode": "pixel"}
        rect = self.proc._build_capture_rect(evt)

        self.assertEqual(rect, {"top": 0, "left": 0, "width": 1, "height": 1})


class TestCheckMatchRegionROIIntegration(unittest.TestCase):
    """_check_match + _extract_roi 통합: 영역 매칭 시 ROI 추출 후 체크포인트 검증"""

    def setUp(self):
        self.proc = _make_processor_stub()

    def test_region_match_with_roi_extraction(self):
        """영역 매칭: ROI 추출 → 체크포인트 검증 전체 경로"""
        img = np.zeros((20, 20, 3), dtype=np.uint8)
        img[3:13, 3:13] = [42, 84, 126]

        evt = {
            "mode": "region",
            "rel_x": 8,
            "rel_y": 8,
            "region_w": 10,
            "region_h": 10,
            "invert": False,
            "check_points": [
                {"pos": (0, 0), "color": np.array([42, 84, 126], dtype=np.uint8)},
                {"pos": (4, 4), "color": np.array([42, 84, 126], dtype=np.uint8)},
                {"pos": (9, 9), "color": np.array([42, 84, 126], dtype=np.uint8)},
            ],
        }

        self.assertTrue(self.proc._check_match(img, evt, is_independent=False))

    def test_region_mismatch_with_roi(self):
        """영역 매칭: ROI 내 체크포인트 불일치"""
        img = np.zeros((20, 20, 3), dtype=np.uint8)
        img[3:13, 3:13] = [42, 84, 126]

        evt = {
            "mode": "region",
            "rel_x": 8,
            "rel_y": 8,
            "region_w": 10,
            "region_h": 10,
            "invert": False,
            "check_points": [
                {"pos": (0, 0), "color": np.array([99, 99, 99], dtype=np.uint8)},
            ],
        }

        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
