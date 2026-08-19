import time
import unittest
from unittest.mock import MagicMock, patch

from app.core.screen_backend import (
    MacStreamBackend,
    MssScreenBackend,
    NullScreenBackend,
    _MAX_UNION_AREA,
    create_screen_backend,
    crop_groups_from_union,
    frame_from_bgra,
    open_screen_backend,
    union_group_rects,
)
from tests.helpers import fill_frame_rect, make_image_frame, make_processor_stub


def _group(left: int, top: int, width: int, height: int, name: str = "A"):
    return {
        "rect": {"left": left, "top": top, "width": width, "height": height},
        "events": [
            {
                "name": name,
                "mode": "pixel",
                "rel_x": 0,
                "rel_y": 0,
                "invert": False,
                "ref_bgr": (1, 2, 3),
            }
        ],
    }


class TestUnionAndCrop(unittest.TestCase):
    def test_union_group_rects(self):
        union = union_group_rects(
            [_group(10, 20, 4, 2), _group(30, 18, 5, 8)]
        )
        self.assertEqual(union, {"left": 10, "top": 18, "width": 25, "height": 8})

    def test_crop_keeps_group_relative_pixels(self):
        union = {"left": 10, "top": 20, "width": 20, "height": 10}
        frame = make_image_frame(20, 10)
        fill_frame_rect(frame, 5, 2, 1, 1, (9, 8, 7))
        groups = [_group(15, 22, 3, 3)]

        cropped = crop_groups_from_union(frame, union, groups)

        self.assertEqual(len(cropped), 1)
        self.assertIsNotNone(cropped[0])
        assert cropped[0] is not None
        self.assertEqual(cropped[0].pixel_bgr(0, 0), (9, 8, 7))

    def test_crop_out_of_bounds_returns_none(self):
        union = {"left": 0, "top": 0, "width": 4, "height": 4}
        frame = make_image_frame(4, 4)
        cropped = crop_groups_from_union(frame, union, [_group(0, 0, 8, 8)])
        self.assertEqual(cropped, [None])


class TestCreateScreenBackend(unittest.TestCase):
    def test_empty_groups_are_null(self):
        self.assertIsInstance(create_screen_backend([]), NullScreenBackend)

    def test_windows_uses_mss(self):
        self.assertIsInstance(
            create_screen_backend([_group(0, 0, 1, 1)], os_name="Windows"),
            MssScreenBackend,
        )

    def test_darwin_uses_scstream(self):
        self.assertIsInstance(
            create_screen_backend([_group(0, 0, 1, 1)], os_name="Darwin"),
            MacStreamBackend,
        )

    def test_oversized_union_uses_mss(self):
        side = int(_MAX_UNION_AREA**0.5) + 2
        self.assertIsInstance(
            create_screen_backend([_group(0, 0, side, side)], os_name="Darwin"),
            MssScreenBackend,
        )

    def test_open_falls_back_to_mss_when_stream_fails(self):
        with (
            patch(
                "app.core.screen_backend.MacStreamBackend.open",
                side_effect=RuntimeError("no permission"),
            ),
            patch.object(MssScreenBackend, "open") as mss_open,
        ):
            backend = open_screen_backend([_group(1, 1, 2, 2)], os_name="Darwin")
        self.assertIsInstance(backend, MssScreenBackend)
        mss_open.assert_called_once()


class TestMacStreamGrab(unittest.TestCase):
    def test_grab_returns_none_before_first_frame(self):
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 4, "height": 4})
        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])

    def test_grab_crops_latest_union_frame(self):
        backend = MacStreamBackend({"left": 10, "top": 20, "width": 8, "height": 6})
        frame = make_image_frame(8, 6)
        fill_frame_rect(frame, 2, 1, 1, 1, (4, 5, 6))
        backend.frame = frame
        backend.frame_time = time.perf_counter()
        cropped = backend.grab([_group(12, 21, 1, 1)])
        self.assertEqual(len(cropped), 1)
        assert cropped[0] is not None
        self.assertEqual(cropped[0].pixel_bgr(0, 0), (4, 5, 6))

    def test_stale_frame_is_ignored(self):
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
        backend.frame = make_image_frame(2, 2)
        backend.frame_time = time.perf_counter() - 5.0
        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])

    def test_dead_stream_returns_none(self):
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
        backend.frame = make_image_frame(2, 2)
        backend.frame_time = time.perf_counter()
        backend.mark_dead()
        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])
        self.assertIsNone(backend.frame)


class TestProcessorCaptureStates(unittest.IsolatedAsyncioTestCase):
    def test_skips_none_frames(self):
        proc = make_processor_stub()
        group = _group(0, 0, 2, 2, "Pix")
        proc.main_capture_groups = [group]
        backend = MagicMock()
        backend.grab.return_value = [None]

        states = proc._capture_match_states(backend)

        self.assertEqual(states, {})
        backend.grab.assert_called_once_with([group])

    def test_evaluates_available_frames(self):
        proc = make_processor_stub()
        group = _group(0, 0, 2, 2, "Pix")
        proc.main_capture_groups = [group]
        frame = make_image_frame(2, 2)
        fill_frame_rect(frame, 0, 0, 1, 1, (1, 2, 3))
        backend = MagicMock()
        backend.grab.return_value = [frame]

        states = proc._capture_match_states(backend)

        self.assertEqual(states, {"Pix": True})


class TestCopyPixelbufferScale(unittest.TestCase):
    def test_copy_same_size_roundtrip(self):
        from app.core.screen_backend import _copy_bytes

        data = bytearray(range(16))
        self.assertEqual(list(_copy_bytes(data, 8)), list(range(8)))

    def test_padded_rows_unpacked(self):
        width, height, stride = 2, 2, 16
        src = bytearray(stride * height)
        src[0:4] = b"\x01\x02\x03\xff"
        src[4:8] = b"\x04\x05\x06\xff"
        src[stride : stride + 4] = b"\x07\x08\x09\xff"
        src[stride + 4 : stride + 8] = b"\x0a\x0b\x0c\xff"
        frame = frame_from_bgra(bytes(src), width, height, stride, width, height)
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.pixel_bgr(0, 0), (1, 2, 3))
        self.assertEqual(frame.pixel_bgr(1, 1), (10, 11, 12))
        self.assertEqual(frame.row_stride, width * 4)


class TestMssGrabImportsImageFrame(unittest.TestCase):
    def test_grab_returns_screenshot_frame(self):
        backend = MssScreenBackend()
        fake_shot = MagicMock()
        fake_shot.width = 1
        fake_shot.height = 1
        fake_shot.raw = bytearray(b"\x09\x08\x07\xff")
        fake_sct = MagicMock()
        fake_sct.grab.return_value = fake_shot
        backend._sct = fake_sct

        frames = backend.grab([_group(3, 4, 1, 1)])

        self.assertEqual(len(frames), 1)
        assert frames[0] is not None
        self.assertEqual(frames[0].pixel_bgr(0, 0), (9, 8, 7))
        fake_sct.grab.assert_called_once_with(
            {"left": 3, "top": 4, "width": 1, "height": 1}
        )


if __name__ == "__main__":
    unittest.main()
