import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.core.screen_backend import (
    MacStreamBackend,
    MssScreenBackend,
    NullScreenBackend,
    _handle_sample_buffer,
    _sck_classes,
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

    def test_large_union_still_uses_scstream(self):
        """macOS에서는 크기와 무관하게 mss로 내려가지 않는다."""
        self.assertIsInstance(
            create_screen_backend([_group(0, 0, 3440, 1440)], os_name="Darwin"),
            MacStreamBackend,
        )

    def test_failed_stream_open_returns_dead_backend(self):
        """mss로 대체하지 않고, 실행 루프가 다시 열 수 있도록 사망 상태로 준다."""
        with patch(
            "app.core.screen_backend.MacStreamBackend.open",
            side_effect=RuntimeError("no permission"),
        ):
            backend = open_screen_backend([_group(1, 1, 2, 2)], os_name="Darwin")

        self.assertIsInstance(backend, MacStreamBackend)
        self.assertTrue(backend.is_dead())
        self.assertEqual(backend.grab([_group(1, 1, 2, 2)]), [None])

    def test_windows_open_failure_propagates(self):
        with patch.object(MssScreenBackend, "open", side_effect=OSError("nope")):
            with self.assertRaises(OSError):
                open_screen_backend([_group(1, 1, 2, 2)], os_name="Windows")


class TestMacStreamGrab(unittest.TestCase):
    def test_grab_returns_none_before_first_frame(self):
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 4, "height": 4})
        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])

    def test_grab_crops_latest_union_frame(self):
        backend = MacStreamBackend({"left": 10, "top": 20, "width": 8, "height": 6})
        frame = make_image_frame(8, 6)
        fill_frame_rect(frame, 2, 1, 1, 1, (4, 5, 6))
        backend.frame = frame
        cropped = backend.grab([_group(12, 21, 1, 1)])
        self.assertEqual(len(cropped), 1)
        assert cropped[0] is not None
        self.assertEqual(cropped[0].pixel_bgr(0, 0), (4, 5, 6))

    def test_static_screen_keeps_last_frame(self):
        """화면이 오래 정지하면 콜백 자체가 끊긴다. 그래도 마지막 프레임을 쓴다."""
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
        frame = make_image_frame(2, 2)
        fill_frame_rect(frame, 0, 0, 1, 1, (7, 7, 7))
        backend.frame = frame

        grabbed = backend.grab([_group(0, 0, 1, 1)])

        self.assertEqual(len(grabbed), 1)
        assert grabbed[0] is not None
        self.assertEqual(grabbed[0].pixel_bgr(0, 0), (7, 7, 7))
        self.assertFalse(backend.is_dead())

    def test_dead_stream_returns_none(self):
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
        backend.frame = make_image_frame(2, 2)
        backend.mark_dead()
        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])
        self.assertTrue(backend.is_dead())
        self.assertIsNone(backend.frame)

    def test_mss_and_null_backends_are_never_dead(self):
        self.assertFalse(MssScreenBackend().is_dead())
        self.assertFalse(NullScreenBackend().is_dead())


class TestProcessorCaptureStates(unittest.IsolatedAsyncioTestCase):
    def test_incomplete_capture_skips_cycle(self):
        proc = make_processor_stub()
        group = _group(0, 0, 2, 2, "Pix")
        proc.main_capture_groups = [group]
        backend = MagicMock()
        backend.grab.return_value = [None]

        states = proc._capture_match_states(backend)

        self.assertIsNone(states)
        backend.grab.assert_called_once_with([group])

    def test_partial_capture_skips_cycle(self):
        proc = make_processor_stub()
        first = _group(0, 0, 2, 2, "A")
        second = _group(50, 50, 2, 2, "B")
        proc.main_capture_groups = [first, second]
        backend = MagicMock()
        backend.grab.return_value = [make_image_frame(2, 2), None]

        self.assertIsNone(proc._capture_match_states(backend))

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


class _FakeCoreMedia:
    """샘플 버퍼 상태/이미지 유무만 흉내내는 CoreMedia 대역."""

    def __init__(self, status, image=None):
        self._status = status
        self._image = image

    def CMSampleBufferGetSampleAttachmentsArray(self, _sbuf, _create):
        if self._status is None:
            return None
        return [{"status": self._status}]

    def CMSampleBufferGetImageBuffer(self, _sbuf):
        return self._image


def _live_backend(frame=None):
    backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
    backend.frame = frame
    backend.frame_deadline = 0.0 if frame is not None else time.perf_counter() + 2.0
    return backend


class TestSampleBufferStatus(unittest.TestCase):
    def test_idle_status_keeps_last_frame(self):
        frame = make_image_frame(2, 2)
        backend = _live_backend(frame)

        _handle_sample_buffer(backend, object(), _FakeCoreMedia(1), "status")

        self.assertIs(backend.frame, frame)
        self.assertEqual(backend.frame_deadline, 0.0)

    def test_blank_status_drops_frame_without_escalating(self):
        """잠금 화면·슬립은 스스로 복구되므로 사망 승격 대상이 아니다."""
        backend = _live_backend(make_image_frame(2, 2))

        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")

        self.assertIsNone(backend.frame)
        # 짧은 fault 기한이 아니라 넉넉한 blank 기한이 걸려야 한다.
        self.assertGreater(backend.frame_deadline - time.perf_counter(), 60.0)
        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])
        self.assertFalse(backend.is_dead())

    def test_suspended_status_drops_frame_without_escalating(self):
        backend = _live_backend(make_image_frame(2, 2))

        _handle_sample_buffer(backend, object(), _FakeCoreMedia(3), "status")

        self.assertIsNone(backend.frame)
        self.assertGreater(backend.frame_deadline - time.perf_counter(), 60.0)
        self.assertFalse(backend.is_dead())

    def test_content_returns_after_blank(self):
        backend = _live_backend(make_image_frame(2, 2))
        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")
        restored = make_image_frame(2, 2)
        fill_frame_rect(restored, 0, 0, 1, 1, (3, 3, 3))

        with patch(
            "app.core.screen_backend._copy_pixelbuffer", return_value=restored
        ):
            _handle_sample_buffer(
                backend, object(), _FakeCoreMedia(0, image=object()), "status"
            )

        grabbed = backend.grab([_group(0, 0, 1, 1)])
        assert grabbed[0] is not None
        self.assertEqual(grabbed[0].pixel_bgr(0, 0), (3, 3, 3))

    def test_stopped_status_marks_dead(self):
        backend = _live_backend(make_image_frame(2, 2))

        _handle_sample_buffer(backend, object(), _FakeCoreMedia(5), "status")

        self.assertTrue(backend.is_dead())

    def test_complete_status_stores_frame(self):
        backend = _live_backend()
        new_frame = make_image_frame(2, 2)
        with patch(
            "app.core.screen_backend._copy_pixelbuffer", return_value=new_frame
        ):
            _handle_sample_buffer(
                backend, object(), _FakeCoreMedia(0, image=object()), "status"
            )

        self.assertIs(backend.frame, new_frame)
        self.assertEqual(backend.frame_deadline, 0.0)

    def test_unusable_image_escalates(self):
        backend = _live_backend(make_image_frame(2, 2))
        with patch("app.core.screen_backend._copy_pixelbuffer", return_value=None):
            _handle_sample_buffer(
                backend, object(), _FakeCoreMedia(0, image=object()), "status"
            )

        self.assertIsNone(backend.frame)
        # 고장이므로 짧은 기한이 걸린다.
        self.assertLess(backend.frame_deadline - time.perf_counter(), 3.0)

    def test_frame_after_death_is_discarded(self):
        backend = _live_backend()
        backend.mark_dead()

        with patch(
            "app.core.screen_backend._copy_pixelbuffer",
            return_value=make_image_frame(2, 2),
        ):
            _handle_sample_buffer(
                backend, object(), _FakeCoreMedia(0, image=object()), "status"
            )

        self.assertIsNone(backend.frame)

    def test_missing_status_falls_back_to_image_presence(self):
        frame = make_image_frame(2, 2)
        backend = _live_backend(frame)

        _handle_sample_buffer(backend, object(), _FakeCoreMedia(None), "status")

        self.assertIs(backend.frame, frame)

    def test_screenless_only_profile_has_no_capture_groups(self):
        proc = make_processor_stub()
        proc.main_capture_groups = []
        backend = MagicMock()
        backend.grab.return_value = []

        self.assertEqual(proc._capture_match_states(backend), {})

    def test_repeated_fault_keeps_first_stall_timestamp(self):
        backend = _live_backend(make_image_frame(2, 2))
        backend.drop_frame(fault=True)
        first = backend.frame_deadline
        backend.drop_frame(fault=True)

        self.assertEqual(backend.frame_deadline, first)

    def test_callback_exception_drops_stale_frame(self):
        classes = _sck_classes()
        output = classes["output"].alloc().init()
        backend = _live_backend(make_image_frame(2, 2))
        output.backend = backend

        with patch(
            "app.core.screen_backend._handle_sample_buffer",
            side_effect=RuntimeError("boom"),
        ):
            output.stream_didOutputSampleBuffer_ofType_(None, object(), 0)

        self.assertIsNone(backend.frame)
        self.assertGreater(backend.frame_deadline, 0.0)

    def test_callback_exception_does_not_escape(self):
        classes = _sck_classes()
        output = classes["output"].alloc().init()
        broken = MagicMock()
        broken.lock = MagicMock(side_effect=RuntimeError("boom"))
        type(broken).union = property(
            lambda _self: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        output.backend = broken

        output.stream_didOutputSampleBuffer_ofType_(None, object(), 0)


class TestStallEscalation(unittest.TestCase):
    def test_missing_frame_eventually_marks_dead(self):
        """기동 후든 도중이든, 쓸 수 있는 프레임이 없는 채 기한을 넘기면 승격."""
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
        backend.frame_deadline = time.perf_counter() - 1.0

        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])
        self.assertTrue(backend.is_dead())

    def test_callback_silence_alone_never_marks_dead(self):
        """콜백 침묵은 정상이다(정지 화면에서 30초 넘게 끊기는 것을 실측)."""
        backend = _live_backend(make_image_frame(2, 2))

        for _ in range(5):
            self.assertIsNotNone(backend.grab([_group(0, 0, 1, 1)])[0])

        self.assertFalse(backend.is_dead())

    def test_repeated_blank_does_not_extend_deadline(self):
        """blank 기한은 진입 시 한 번만 건다. 매번 연장하면 탈출구가 없다."""
        backend = _live_backend(make_image_frame(2, 2))
        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")
        first = backend.frame_deadline

        for _ in range(3):
            _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")

        self.assertEqual(backend.frame_deadline, first)
        self.assertFalse(backend.is_dead())

    def test_blank_does_not_extend_fault_deadline(self):
        """Blank와 고장이 번갈아 와도 기한이 무한 연장되면 안 된다."""
        backend = _live_backend(make_image_frame(2, 2))
        backend.drop_frame(fault=True)
        fault_deadline = backend.frame_deadline

        for _ in range(3):
            _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")
            backend.drop_frame(fault=True)

        self.assertEqual(backend.frame_deadline, fault_deadline)
        self.assertEqual(backend.frame_gap, "fault")

    def test_startup_deadline_is_replaced_by_blank(self):
        """잠금 화면에서 기동하면 open()의 2초 기한이 blank 기한으로 바뀐다."""
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
        backend.frame_deadline = time.perf_counter() + 2.0

        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")

        self.assertGreater(backend.frame_deadline - time.perf_counter(), 60.0)

    def test_startup_deadline_does_not_override_blank(self):
        """Blank가 기동 완료보다 먼저 도착해도 2초 기한으로 깎이면 안 된다."""
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")
        blank_deadline = backend.frame_deadline

        backend._arm_initial_deadline()

        self.assertEqual(backend.frame_deadline, blank_deadline)

    def test_startup_deadline_is_armed_without_blank(self):
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})

        backend._arm_initial_deadline()

        gap = backend.frame_deadline - time.perf_counter()
        self.assertTrue(0.0 < gap <= 2.0, gap)

    def test_fault_during_blank_shortens_deadline(self):
        """잠금 중 고장이 나면 90초를 기다리지 않고 짧은 기한으로 당긴다."""
        backend = _live_backend(make_image_frame(2, 2))
        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")
        self.assertGreater(backend.frame_deadline - time.perf_counter(), 60.0)

        backend.drop_frame(fault=True)

        self.assertLess(backend.frame_deadline - time.perf_counter(), 3.0)
        self.assertEqual(backend.frame_gap, "fault")

    def test_persistent_blank_eventually_marks_dead(self):
        """복구되지 않는 잠금 상태에서 빠져나올 수 있어야 한다(재기동으로)."""
        backend = _live_backend(make_image_frame(2, 2))
        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")
        backend.frame_deadline = time.perf_counter() - 1.0

        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])
        self.assertTrue(backend.is_dead())

    def test_complete_frame_clears_blank_state(self):
        backend = _live_backend(make_image_frame(2, 2))
        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")
        self.assertEqual(backend.frame_gap, "blank")

        with patch(
            "app.core.screen_backend._copy_pixelbuffer",
            return_value=make_image_frame(2, 2),
        ):
            _handle_sample_buffer(
                backend, object(), _FakeCoreMedia(0, image=object()), "status"
            )

        self.assertEqual(backend.frame_gap, "")
        self.assertEqual(backend.frame_deadline, 0.0)

    def test_fresh_backend_is_not_immediately_dead(self):
        backend = MacStreamBackend({"left": 0, "top": 0, "width": 2, "height": 2})
        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])
        self.assertFalse(backend.is_dead())

    def test_blank_within_deadline_does_not_mark_dead(self):
        backend = _live_backend(make_image_frame(2, 2))
        _handle_sample_buffer(backend, object(), _FakeCoreMedia(2), "status")

        self.assertEqual(backend.grab([_group(0, 0, 1, 1)]), [None])
        self.assertFalse(backend.is_dead())


class TestOffscreenCaptureRects(unittest.TestCase):
    """화면 밖 좌표가 프로필 전체를 죽이면 안 된다."""

    def _proc(self, events):
        proc = make_processor_stub(events)
        return proc

    def test_offscreen_event_is_dropped_not_fatal(self):
        proc = make_processor_stub()
        good = {
            "name": "GOOD", "mode": "pixel", "invert": False, "key": None,
            "center_x": 100, "center_y": 100, "dur": None, "rand": None,
            "exec": False, "group": None, "priority": 1, "conds": {},
            "runtime_toggle_member": False, "region_w": 1, "region_h": 1,
            "rel_x": 0, "rel_y": 0,
        }
        offscreen = dict(good, name="OFFSCREEN", center_x=-50, center_y=-50)

        with patch(
            "app.core.processor.MonitorUtils.get_primary_size",
            return_value=(1000, 800),
        ):
            groups = proc._build_capture_groups([good, offscreen])

        names = [e["name"] for g in groups for e in g["events"]]
        self.assertEqual(names, ["GOOD"])
        for g in groups:
            r = g["rect"]
            self.assertGreaterEqual(r["left"], 0)
            self.assertGreaterEqual(r["top"], 0)

    def test_edge_region_is_clamped_into_the_screen(self):
        proc = make_processor_stub()
        edge = {
            "name": "EDGE", "mode": "region", "invert": False, "key": None,
            "center_x": 10, "center_y": 10, "dur": None, "rand": None,
            "exec": False, "group": None, "priority": 1, "conds": {},
            "runtime_toggle_member": False, "region_w": 100, "region_h": 100,
            "rel_x": 0, "rel_y": 0,
        }

        with patch(
            "app.core.processor.MonitorUtils.get_primary_size",
            return_value=(1000, 800),
        ):
            groups = proc._build_capture_groups([edge])

        self.assertEqual(len(groups), 1)
        rect = groups[0]["rect"]
        self.assertEqual(rect["left"], 0)
        self.assertEqual(rect["top"], 0)
        self.assertLessEqual(rect["left"] + rect["width"], 1000)
        self.assertLessEqual(rect["top"] + rect["height"], 800)


class TestDeadBackendRecovery(unittest.TestCase):
    def _stub(self):
        proc = make_processor_stub()
        proc._screen_backend = None
        proc._backend_retry_failed = False
        proc._last_backend_retry = 0.0
        proc._backend_closers = []
        proc.term_event = threading.Event()
        proc._stopped = threading.Event()
        proc.main_capture_groups = [_group(0, 0, 2, 2)]
        return proc

    def test_dead_backend_is_reopened(self):
        proc = self._stub()
        dead = MagicMock()
        fresh = MagicMock()

        with patch(
            "app.core.processor.create_screen_backend", return_value=fresh
        ) as reopen:
            replacement = proc._replace_dead_backend(dead)

        reopen.assert_called_once_with(proc.main_capture_groups)
        fresh.open.assert_called_once()
        self.assertIs(replacement, fresh)
        self.assertIs(proc._screen_backend, fresh)
        # close는 데몬 스레드로 분리되므로 기다린 뒤 확인한다.
        proc._join_backend_closers()
        dead.close.assert_called_once()

    def test_retry_is_throttled(self):
        """원인이 지속되는 동안 매 사이클 다시 열지 않는다."""
        proc = self._stub()

        with patch(
            "app.core.processor.create_screen_backend", return_value=MagicMock()
        ) as reopen:
            proc._replace_dead_backend(MagicMock())
            for _ in range(5):
                proc._replace_dead_backend(MagicMock())

        self.assertEqual(reopen.call_count, 1)
        proc._join_backend_closers()

    def test_retry_interval_starts_after_the_attempt(self):
        """실패 경로가 수 초 걸려도 루프가 open() 안에 갇히면 안 된다."""
        proc = self._stub()

        def slow_fail(_groups):
            proc._last_backend_retry -= 10.0   # open()이 오래 걸린 상황
            raise OSError("slow failure")

        with patch(
            "app.core.processor.create_screen_backend", side_effect=slow_fail
        ) as reopen:
            proc._replace_dead_backend(MagicMock())
            proc._replace_dead_backend(MagicMock())

        self.assertEqual(reopen.call_count, 1)

    def test_retry_resumes_after_interval(self):
        proc = self._stub()

        with patch(
            "app.core.processor.create_screen_backend", return_value=MagicMock()
        ) as reopen:
            proc._replace_dead_backend(MagicMock())
            proc._last_backend_retry -= proc.BACKEND_RETRY_INTERVAL_S + 1.0
            proc._replace_dead_backend(MagicMock())

        self.assertEqual(reopen.call_count, 2)
        proc._join_backend_closers()

    def test_failed_reopen_keeps_old_backend_and_logs_once(self):
        proc = self._stub()
        dead = MagicMock()

        with patch(
            "app.core.processor.create_screen_backend", side_effect=OSError("nope")
        ):
            self.assertIs(proc._replace_dead_backend(dead), dead)
            self.assertTrue(proc._backend_retry_failed)
            proc._last_backend_retry -= proc.BACKEND_RETRY_INTERVAL_S + 1.0
            self.assertIs(proc._replace_dead_backend(dead), dead)

        dead.close.assert_not_called()

    def test_shutdown_does_not_reopen_backend(self):
        proc = self._stub()
        proc.term_event.set()
        self._assert_no_reopen(proc)

    def test_own_stop_survives_shared_event_reset(self):
        """앱이 재시작하며 term_event를 clear해도 멈춘 프로세서는 되살아나면 안 된다."""
        proc = self._stub()
        proc._stopped.set()
        proc.term_event.clear()
        self._assert_no_reopen(proc)

    def _assert_no_reopen(self, proc):
        dead = MagicMock()

        with patch("app.core.processor.create_screen_backend") as reopen:
            self.assertIs(proc._replace_dead_backend(dead), dead)

        reopen.assert_not_called()
        dead.close.assert_not_called()

    def test_replacement_is_discarded_when_stopping(self):
        """여는 사이에 중지되면 새 백엔드를 남기지 않는다."""
        proc = self._stub()
        dead = MagicMock()
        fresh = MagicMock()

        def opening(_groups):
            proc.term_event.set()
            return fresh

        with patch("app.core.processor.create_screen_backend", side_effect=opening):
            replacement = proc._replace_dead_backend(dead)

        self.assertIs(replacement, dead)
        fresh.close.assert_called_once()
        self.assertIsNone(proc._screen_backend)

    def test_consecutive_replacements_close_every_backend(self):
        proc = self._stub()
        first_dead = MagicMock()
        second_dead = MagicMock()

        with patch("app.core.processor.create_screen_backend", return_value=MagicMock()):
            proc._replace_dead_backend(first_dead)
            proc._last_backend_retry -= proc.BACKEND_RETRY_INTERVAL_S + 1.0
            proc._replace_dead_backend(second_dead)

        proc._join_backend_closers()
        first_dead.close.assert_called_once()
        second_dead.close.assert_called_once()
        self.assertEqual(proc._backend_closers, [])

    def test_replacement_does_not_wait_for_previous_closer(self):
        """연속 교체에서 이전 close를 기다리면 눌린 키가 그만큼 늘어진다."""
        proc = self._stub()
        release = threading.Event()
        slow = MagicMock()
        slow.close.side_effect = lambda: release.wait(5.0)

        with patch("app.core.processor.create_screen_backend", return_value=MagicMock()):
            proc._replace_dead_backend(slow)
            proc._last_backend_retry -= proc.BACKEND_RETRY_INTERVAL_S + 1.0
            started = time.perf_counter()
            proc._replace_dead_backend(MagicMock())
            elapsed = time.perf_counter() - started

        release.set()
        proc._join_backend_closers()
        self.assertLess(elapsed, 0.5, elapsed)


class TestCopyPixelbufferScale(unittest.TestCase):
    def test_buffer_view_is_zero_copy_slice(self):
        from app.core.screen_backend import _buffer_view

        data = bytearray(range(16))
        view = _buffer_view(data, 8)
        self.assertEqual(list(view), list(range(8)))
        data[0] = 200
        self.assertEqual(view[0], 200)

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

    def test_memoryview_source_is_accepted(self):
        width, height, stride = 2, 1, 16
        src = bytearray(stride * height)
        src[0:4] = b"\x01\x02\x03\xff"
        frame = frame_from_bgra(
            memoryview(src), width, height, stride, width, height
        )
        assert frame is not None
        self.assertEqual(frame.pixel_bgr(0, 0), (1, 2, 3))

    def test_size_mismatch_drops_frame(self):
        src = bytes(4 * 4 * 4)
        self.assertIsNone(frame_from_bgra(src, 4, 4, 16, 2, 2))


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
