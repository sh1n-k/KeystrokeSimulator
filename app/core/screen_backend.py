from __future__ import annotations

import importlib
import platform
import threading
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

if TYPE_CHECKING:
    from app.core.processor import ImageFrame

Rect = dict[str, int]

BGRA = 0x42475241
_STREAM_FPS = 30
_START_TIMEOUT_S = 8.0
_MAX_FRAME_AGE_S = 0.5
_MAX_UNION_AREA = 2_000_000
_SCK_CLASSES: dict[str, Any] = {}


class ScreenBackend(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def grab(self, groups: Sequence[Any]) -> list[ImageFrame | None]: ...


class NullScreenBackend:
    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def grab(self, groups: Sequence[Any]) -> list[ImageFrame | None]:
        return [None] * len(groups)


class MssScreenBackend:
    def __init__(self) -> None:
        self._sct: Any = None
        self._lock = threading.Lock()

    def open(self) -> None:
        import mss

        self._sct = mss.mss()

    def close(self) -> None:
        with self._lock:
            sct = self._sct
            self._sct = None
        if sct is not None:
            sct.close()

    def grab(self, groups: Sequence[Any]) -> list[ImageFrame | None]:
        from app.core.processor import ImageFrame

        with self._lock:
            sct = self._sct
            if sct is None:
                return [None] * len(groups)
            return [
                ImageFrame.from_screenshot(sct.grab(group["rect"])) for group in groups
            ]


def union_group_rects(groups: Sequence[Any]) -> Rect:
    rects = [group["rect"] for group in groups]
    left = min(rect["left"] for rect in rects)
    top = min(rect["top"] for rect in rects)
    right = max(rect["left"] + rect["width"] for rect in rects)
    bottom = max(rect["top"] + rect["height"] for rect in rects)
    return {
        "left": left,
        "top": top,
        "width": max(1, right - left),
        "height": max(1, bottom - top),
    }


def crop_groups_from_union(
    frame: ImageFrame, union: Rect, groups: Sequence[Any]
) -> list[ImageFrame | None]:
    frames: list[ImageFrame | None] = []
    for group in groups:
        rect = group["rect"]
        x = rect["left"] - union["left"]
        y = rect["top"] - union["top"]
        width = rect["width"]
        height = rect["height"]
        if (
            x < 0
            or y < 0
            or width < 1
            or height < 1
            or x + width > frame.width
            or y + height > frame.height
        ):
            frames.append(None)
            continue
        frames.append(frame.crop(x, y, width, height))
    return frames


def _framework(name: str) -> Any:
    return importlib.import_module(name)


def frame_from_bgra(
    src: bytes,
    src_w: int,
    src_h: int,
    stride: int,
    dest_w: int,
    dest_h: int,
) -> ImageFrame | None:
    from app.core.processor import ImageFrame

    if src_w < 1 or src_h < 1 or dest_w < 1 or dest_h < 1 or stride < src_w * 4:
        return None
    packed = dest_w * 4
    if src_w == dest_w and src_h == dest_h:
        if stride == packed:
            return ImageFrame(
                width=dest_w,
                height=dest_h,
                data=bytearray(src[: dest_h * packed]),
                row_stride=packed,
                pixel_stride=4,
            )
        dest = bytearray(dest_h * packed)
        for y in range(dest_h):
            start = y * stride
            dest_row = y * packed
            dest[dest_row : dest_row + packed] = src[start : start + packed]
        return ImageFrame(
            width=dest_w,
            height=dest_h,
            data=dest,
            row_stride=packed,
            pixel_stride=4,
        )
    dest = bytearray(dest_h * packed)
    for y in range(dest_h):
        src_y = min(src_h - 1, y * src_h // dest_h)
        src_row = src_y * stride
        dest_row = y * packed
        for x in range(dest_w):
            src_x = min(src_w - 1, x * src_w // dest_w)
            src_i = src_row + src_x * 4
            dest_i = dest_row + x * 4
            dest[dest_i : dest_i + 4] = src[src_i : src_i + 4]
    return ImageFrame(
        width=dest_w,
        height=dest_h,
        data=dest,
        row_stride=packed,
        pixel_stride=4,
    )


def _copy_bytes(base: Any, nbytes: int) -> bytes:
    source: Any = base
    as_buffer = getattr(source, "as_buffer", None)
    if callable(as_buffer):
        source = as_buffer(nbytes)
    elif hasattr(source, "__getitem__"):
        source = source[:nbytes]
    else:
        import ctypes

        source = (ctypes.c_ubyte * nbytes).from_address(int(source))
    copied: bytes = bytes(source)
    return copied


def _copy_pixelbuffer(buffer: Any, dest_w: int, dest_h: int) -> ImageFrame | None:
    quartz: Any = _framework("Quartz")
    if buffer is None or dest_w < 1 or dest_h < 1:
        return None
    quartz.CVPixelBufferLockBaseAddress(buffer, 0)
    try:
        src_w = int(quartz.CVPixelBufferGetWidth(buffer))
        src_h = int(quartz.CVPixelBufferGetHeight(buffer))
        stride = int(quartz.CVPixelBufferGetBytesPerRow(buffer))
        base = quartz.CVPixelBufferGetBaseAddress(buffer)
        if not base or src_w < 1 or src_h < 1:
            return None
        src = _copy_bytes(base, stride * src_h)
        return frame_from_bgra(src, src_w, src_h, stride, dest_w, dest_h)
    finally:
        quartz.CVPixelBufferUnlockBaseAddress(buffer, 0)


def _sck_classes() -> dict[str, Any]:
    if _SCK_CLASSES:
        return _SCK_CLASSES

    core_media: Any = _framework("CoreMedia")
    ns_object: Any = _framework("Foundation").NSObject

    class SCStreamOutput(ns_object):
        backend: Any = None

        def stream_didOutputSampleBuffer_ofType_(
            self, _stream: Any, sample_buffer: Any, _output_type: int
        ) -> None:
            backend: Any = self.backend
            if backend is None:
                return
            buffer = core_media.CMSampleBufferGetImageBuffer(sample_buffer)
            frame = _copy_pixelbuffer(
                buffer, backend.union["width"], backend.union["height"]
            )
            if frame is None:
                return
            with backend.lock:
                backend.frame = frame
                backend.frame_time = time.perf_counter()

    class SCStreamDelegate(ns_object):
        backend: Any = None

        def stream_didStopWithError_(self, _stream: Any, error: Any) -> None:
            backend: Any = self.backend
            if backend is None or error is None:
                return
            logger.warning(f"SCStream stopped: {error}")
            backend.mark_dead()

    _SCK_CLASSES["output"] = SCStreamOutput
    _SCK_CLASSES["delegate"] = SCStreamDelegate
    return _SCK_CLASSES


def _pump(seconds: float) -> None:
    quartz: Any = _framework("Quartz")
    quartz.CFRunLoopRunInMode(quartz.kCFRunLoopDefaultMode, seconds, False)


def _wait_shareable(timeout: float) -> Any:
    sck: Any = _framework("ScreenCaptureKit")
    box: dict[str, Any] = {}

    def done(content: Any, error: Any) -> None:
        box["content"] = content
        box["error"] = error

    sck.SCShareableContent.getShareableContentWithCompletionHandler_(done)
    deadline = time.perf_counter() + timeout
    while "content" not in box and time.perf_counter() < deadline:
        _pump(0.05)
    if box.get("error"):
        raise RuntimeError(str(box["error"]))
    if box.get("content") is None:
        raise TimeoutError("SCShareableContent timed out")
    return box["content"]


def _display_for_union(displays: Sequence[Any], union: Rect) -> Any:
    cx = union["left"] + union["width"] // 2
    cy = union["top"] + union["height"] // 2
    for display in displays:
        frame = display.frame()
        left = float(frame.origin.x)
        top = float(frame.origin.y)
        width = float(frame.size.width)
        height = float(frame.size.height)
        if left <= cx < left + width and top <= cy < top + height:
            return display
    return displays[0]


class MacStreamBackend:
    def __init__(self, union: Rect) -> None:
        self.union = union
        self.lock = threading.Lock()
        self.frame: ImageFrame | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error: str | None = None
        self._stream: Any = None
        self._output: Any = None
        self._delegate: Any = None
        self._closed = False
        self._dead = False
        self.frame_time = 0.0

    @classmethod
    def from_groups(cls, groups: Sequence[Any]) -> MacStreamBackend:
        return cls(union_group_rects(groups))

    def open(self) -> None:
        self._closed = False
        self._dead = False
        self.frame_time = 0.0
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run, name="scstream-backend", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(_START_TIMEOUT_S):
            self.close()
            raise TimeoutError("SCStream start timed out")
        if self._error:
            message = self._error
            self.close()
            raise RuntimeError(message)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        with self.lock:
            self.frame = None
            self.frame_time = 0.0

    def mark_dead(self) -> None:
        self._dead = True
        with self.lock:
            self.frame = None
            self.frame_time = 0.0

    def grab(self, groups: Sequence[Any]) -> list[ImageFrame | None]:
        with self.lock:
            frame = self.frame
            frame_time = self.frame_time
        if (
            self._dead
            or frame is None
            or (time.perf_counter() - frame_time) > _MAX_FRAME_AGE_S
        ):
            return [None] * len(groups)
        return crop_groups_from_union(frame, self.union, groups)

    def _run(self) -> None:
        try:
            self._start_stream()
            self._ready.set()
            while not self._stop.wait(0.25):
                continue
        except Exception as exc:
            self._error = str(exc)
            self._ready.set()
        finally:
            self._stop_stream()

    def _start_stream(self) -> None:
        appkit: Any = _framework("AppKit")
        core_media: Any = _framework("CoreMedia")
        quartz: Any = _framework("Quartz")
        sck: Any = _framework("ScreenCaptureKit")

        appkit.NSApplication.sharedApplication()
        content = _wait_shareable(5.0)
        displays = list(content.displays())
        if not displays:
            raise RuntimeError("no shareable displays")
        display = _display_for_union(displays, self.union)
        frame = display.frame()
        source = quartz.CGRectMake(
            self.union["left"] - float(frame.origin.x),
            self.union["top"] - float(frame.origin.y),
            self.union["width"],
            self.union["height"],
        )
        filt = sck.SCContentFilter.alloc().initWithDisplay_excludingWindows_(
            display, []
        )
        cfg = sck.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(self.union["width"])
        cfg.setHeight_(self.union["height"])
        cfg.setSourceRect_(source)
        cfg.setShowsCursor_(False)
        cfg.setPixelFormat_(BGRA)
        cfg.setQueueDepth_(3)
        cfg.setMinimumFrameInterval_(core_media.CMTimeMake(1, _STREAM_FPS))
        classes = _sck_classes()
        output = classes["output"].alloc().init()
        output.backend = self
        delegate = classes["delegate"].alloc().init()
        delegate.backend = self
        self._output = output
        self._delegate = delegate
        stream = sck.SCStream.alloc().initWithFilter_configuration_delegate_(
            filt, cfg, delegate
        )
        ok, error = stream.addStreamOutput_type_sampleHandlerQueue_error_(
            output, sck.SCStreamOutputTypeScreen, None, None
        )
        if not ok:
            raise RuntimeError(f"addStreamOutput failed: {error}")
        started: dict[str, Any] = {}

        def started_cb(err: Any) -> None:
            started["error"] = err
            started["done"] = True

        stream.startCaptureWithCompletionHandler_(started_cb)
        deadline = time.perf_counter() + 5.0
        while "done" not in started and time.perf_counter() < deadline:
            _pump(0.05)
        if "done" not in started:
            raise TimeoutError("SCStream startCapture timed out")
        if started.get("error"):
            raise RuntimeError(str(started["error"]))
        self._stream = stream

    def _stop_stream(self) -> None:
        stream = self._stream
        output = self._output
        self._stream = None
        self._output = None
        self._delegate = None
        if output is not None:
            output.backend = None
        if stream is None:
            return
        stopped: dict[str, bool] = {}

        def stopped_cb(_err: Any) -> None:
            stopped["done"] = True

        try:
            stream.stopCaptureWithCompletionHandler_(stopped_cb)
        except Exception as exc:
            logger.debug(f"SCStream stop failed: {exc}")
            return
        deadline = time.perf_counter() + 2.0
        while "done" not in stopped and time.perf_counter() < deadline:
            _pump(0.05)


def create_screen_backend(
    groups: Sequence[Any],
    *,
    os_name: str | None = None,
) -> ScreenBackend:
    if not groups:
        return NullScreenBackend()
    name = os_name if os_name is not None else platform.system()
    if name == "Darwin":
        union = union_group_rects(groups)
        area = union["width"] * union["height"]
        if area > _MAX_UNION_AREA:
            logger.warning(
                f"SCStream union {union['width']}x{union['height']} exceeds "
                f"{_MAX_UNION_AREA}; using mss"
            )
            return MssScreenBackend()
        return MacStreamBackend(union)
    return MssScreenBackend()


def open_screen_backend(
    groups: Sequence[Any],
    *,
    os_name: str | None = None,
) -> ScreenBackend:
    backend = create_screen_backend(groups, os_name=os_name)
    try:
        backend.open()
        return backend
    except Exception as exc:
        if isinstance(backend, MssScreenBackend):
            raise
        logger.warning(f"SCStream unavailable, falling back to mss: {exc}")
        backend.close()
        fallback = MssScreenBackend()
        fallback.open()
        return fallback
