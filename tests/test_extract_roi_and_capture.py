import unittest
from unittest.mock import patch

from app.core.processor import ImageFrame
from helpers import fill_frame_rect, make_image_frame, make_processor_stub


class TestExtractROI(unittest.TestCase):
    """_extract_roi: 이미지에서 관심 영역 추출"""

    def setUp(self):
        self.proc = make_processor_stub()

    def test_normal_extraction(self):
        """정상 좌표에서 ROI가 올바르게 추출됨"""
        img = ImageFrame(
            width=100,
            height=100,
            data=bytearray(i % 256 for i in range(100 * 100 * 4)),
            row_stride=100 * 4,
            pixel_stride=4,
        )
        evt = {"region_w": 10, "region_h": 10, "rel_x": 50, "rel_y": 50}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNotNone(roi)
        self.assertEqual((roi.width, roi.height), (10, 10))

    def test_roi_pixel_values(self):
        """ROI의 픽셀 값이 원본 이미지와 일치"""
        img = make_image_frame(20, 20)
        fill_frame_rect(img, 5, 5, 10, 10, (100, 200, 50))
        evt = {"region_w": 10, "region_h": 10, "rel_x": 10, "rel_y": 10}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNotNone(roi)
        self.assertEqual(roi.pixel_bgr(0, 0), (100, 200, 50))

    def test_out_of_bounds_returns_none(self):
        """ROI가 이미지 범위를 벗어나면 None 반환"""
        img = make_image_frame(10, 10)
        evt = {"region_w": 20, "region_h": 20, "rel_x": 5, "rel_y": 5}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNone(roi)

    def test_negative_start_returns_none(self):
        """ROI 시작점이 음수면 None 반환"""
        img = make_image_frame(10, 10)
        evt = {"region_w": 10, "region_h": 10, "rel_x": 2, "rel_y": 2}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNone(roi)

    def test_exact_boundary_fit(self):
        """ROI가 이미지 경계에 정확히 맞는 경우"""
        img = make_image_frame(10, 10)
        # w=4, h=4, rel_x=7, rel_y=7 → x=7-2=5, y=7-2=5, 5+4=9 ≤ 10
        evt = {"region_w": 4, "region_h": 4, "rel_x": 7, "rel_y": 7}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNotNone(roi)
        self.assertEqual((roi.width, roi.height), (4, 4))

    def test_boundary_exceeded_by_one(self):
        """ROI가 이미지 경계를 1픽셀 초과하면 None"""
        img = make_image_frame(10, 10)
        # w=4, h=4, rel_x=8, rel_y=8 → x=8-2=6, y=8-2=6, 6+4=10 ≤ 10 → OK
        # w=4, h=4, rel_x=9, rel_y=9 → x=9-2=7, y=9-2=7, 7+4=11 > 10 → None
        evt = {"region_w": 4, "region_h": 4, "rel_x": 9, "rel_y": 9}

        roi = self.proc._extract_roi(img, evt, is_independent=False)

        self.assertIsNone(roi)

    def test_independent_mode_returns_full_image(self):
        """독립 모드에서는 전체 이미지를 반환 (알파 채널 제거)"""
        img = make_image_frame(10, 10, (128, 128, 128), channels=4)
        evt = {"region_w": 5, "region_h": 5, "rel_x": 99, "rel_y": 99}

        roi = self.proc._extract_roi(img, evt, is_independent=True)

        self.assertIsNotNone(roi)
        self.assertEqual((roi.width, roi.height), (10, 10))

    def test_independent_mode_3_channel_image(self):
        """독립 모드: 3채널 이미지도 정상 처리"""
        img = make_image_frame(5, 5, (50, 50, 50))
        evt = {"region_w": 2, "region_h": 2, "rel_x": 0, "rel_y": 0}

        roi = self.proc._extract_roi(img, evt, is_independent=True)

        self.assertEqual((roi.width, roi.height), (5, 5))


class TestBuildCaptureRect(unittest.TestCase):
    """_build_capture_rect: 독립 이벤트 캡처 영역 생성"""

    def setUp(self):
        self.proc = make_processor_stub()

    def test_pixel_mode_single_pixel_rect(self):
        """픽셀 모드: 1x1 캡처 영역"""
        evt = {"center_x": 100, "center_y": 200, "mode": "pixel"}
        rect = self.proc._build_capture_rect(evt)

        self.assertEqual(
            rect,
            {
                "top": 200,
                "left": 100,
                "width": 1,
                "height": 1,
            },
        )

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

        self.assertEqual(
            rect,
            {
                "top": 200 - 15,  # cy - h//2
                "left": 100 - 10,  # cx - w//2
                "width": 20,
                "height": 30,
            },
        )

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

        self.assertEqual(rect["left"], 50 - 5)  # 11 // 2 = 5
        self.assertEqual(rect["top"], 50 - 3)  # 7 // 2 = 3
        self.assertEqual(rect["width"], 11)
        self.assertEqual(rect["height"], 7)

    def test_pixel_mode_at_origin(self):
        """픽셀 모드: 좌표 (0, 0)"""
        evt = {"center_x": 0, "center_y": 0, "mode": "pixel"}
        rect = self.proc._build_capture_rect(evt)

        self.assertEqual(rect, {"top": 0, "left": 0, "width": 1, "height": 1})


class TestBuildCaptureGroups(unittest.TestCase):
    def setUp(self):
        self.proc = make_processor_stub()

    def test_nearby_events_share_group(self):
        events = [
            {"name": "A", "center_x": 10, "center_y": 10, "mode": "pixel"},
            {"name": "B", "center_x": 30, "center_y": 25, "mode": "pixel"},
        ]

        groups = self.proc._build_capture_groups(events)

        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["events"]), 2)

    def test_distant_events_split_groups(self):
        events = [
            {"name": "A", "center_x": 10, "center_y": 10, "mode": "pixel"},
            {"name": "B", "center_x": 500, "center_y": 500, "mode": "pixel"},
        ]

        groups = self.proc._build_capture_groups(events)

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["events"][0]["name"], "A")
        self.assertEqual(groups[1]["events"][0]["name"], "B")


class TestCheckMatchRegionROIIntegration(unittest.TestCase):
    """_check_match + _extract_roi 통합: 영역 매칭 시 ROI 추출 후 체크포인트 검증"""

    def setUp(self):
        self.proc = make_processor_stub()

    def test_region_match_with_roi_extraction(self):
        """영역 매칭: ROI 추출 → 체크포인트 검증 전체 경로"""
        img = make_image_frame(20, 20)
        fill_frame_rect(img, 3, 3, 10, 10, (42, 84, 126))

        evt = {
            "mode": "region",
            "rel_x": 8,
            "rel_y": 8,
            "region_w": 10,
            "region_h": 10,
            "invert": False,
            "check_points": [
                {"pos": (0, 0), "color": (42, 84, 126)},
                {"pos": (4, 4), "color": (42, 84, 126)},
                {"pos": (9, 9), "color": (42, 84, 126)},
            ],
        }

        self.assertTrue(self.proc._check_match(img, evt, is_independent=False))

    def test_region_mismatch_with_roi(self):
        """영역 매칭: ROI 내 체크포인트 불일치"""
        img = make_image_frame(20, 20)
        fill_frame_rect(img, 3, 3, 10, 10, (42, 84, 126))

        evt = {
            "mode": "region",
            "rel_x": 8,
            "rel_y": 8,
            "region_w": 10,
            "region_h": 10,
            "invert": False,
            "check_points": [
                {"pos": (0, 0), "color": (99, 99, 99)},
            ],
        }

        self.assertFalse(self.proc._check_match(img, evt, is_independent=False))


class TestExtractROIWarning(unittest.TestCase):
    """_extract_roi: 경계 초과 시 경고 로깅 검증"""

    def setUp(self):
        self.proc = make_processor_stub()

    def _out_of_bounds_evt(self, name="TestEvt"):
        return {"name": name, "region_w": 50, "region_h": 50, "rel_x": 5, "rel_y": 5}

    def test_warning_logged_on_first_failure(self):
        """경계 초과 최초 발생 시 logger.warning이 호출됨"""
        img = make_image_frame(10, 10)
        with patch("app.core.processor.logger") as mock_log:
            self.proc._extract_roi(img, self._out_of_bounds_evt(), is_independent=False)
            mock_log.warning.assert_called_once()

    def test_warning_logged_only_once_per_event(self):
        """동일 이벤트명은 두 번째 호출부터 경고를 출력하지 않음"""
        img = make_image_frame(10, 10)
        evt = self._out_of_bounds_evt("OnceOnly")
        with patch("app.core.processor.logger") as mock_log:
            self.proc._extract_roi(img, evt, is_independent=False)
            self.proc._extract_roi(img, evt, is_independent=False)
            self.proc._extract_roi(img, evt, is_independent=False)
            mock_log.warning.assert_called_once()

    def test_different_events_each_warn_once(self):
        """이벤트명이 다르면 각각 1회씩 경고"""
        img = make_image_frame(10, 10)
        with patch("app.core.processor.logger") as mock_log:
            self.proc._extract_roi(
                img, self._out_of_bounds_evt("EvtA"), is_independent=False
            )
            self.proc._extract_roi(
                img, self._out_of_bounds_evt("EvtB"), is_independent=False
            )
            self.assertEqual(mock_log.warning.call_count, 2)

    def test_warning_message_contains_event_name_and_sizes(self):
        """경고 메시지에 이벤트명과 크기 정보가 포함됨"""
        img = make_image_frame(10, 10)
        with patch("app.core.processor.logger") as mock_log:
            self.proc._extract_roi(
                img, self._out_of_bounds_evt("MyEvent"), is_independent=False
            )
            msg = mock_log.warning.call_args[0][0]
            self.assertIn("MyEvent", msg)
            self.assertIn("50", msg)  # region_w / region_h

    def test_no_warning_on_successful_extraction(self):
        """정상 ROI 추출 시 경고 없음"""
        img = make_image_frame(100, 100)
        evt = {
            "name": "OkEvt",
            "region_w": 10,
            "region_h": 10,
            "rel_x": 50,
            "rel_y": 50,
        }
        with patch("app.core.processor.logger") as mock_log:
            self.proc._extract_roi(img, evt, is_independent=False)
            mock_log.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
