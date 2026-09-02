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
# kCVPixelBufferLock_ReadOnly — 읽기만 하므로 IOSurface 비용이 낮다.
_LOCK_READ_ONLY = 1
# 백엔드가 죽었을 때 다시 여는 최소 간격. 디스플레이 슬립처럼 원인이 지속되는
# 동안 매 사이클 재시도하지 않도록 한다.
BACKEND_RETRY_INTERVAL_S = 2.0
_STREAM_FPS = 30
# 편집기 미리보기는 화면 전체를 스트리밍하므로 프레임당 복사량이 크다. 소비
# 주기가 0.2초라 30fps는 대부분 낭비다. 실측(3440x1440): 30fps 9.4% CPU →
# 10fps 2.5%, 그 아래로는 CPU가 더 줄지 않고 프레임 나이만 나빠진다.
PREVIEW_STREAM_FPS = 10
_START_TIMEOUT_S = 12.0
# 콜백 도착은 생존 신호로 쓸 수 없다. 화면이 오래 정지해 있으면 macOS가
# Idle 샘플 전달을 아예 멈춘다(실측: 정지 영역에서 30초 넘는 공백, 화면이
# 다시 바뀌면 즉시 재개). 공백 길이가 예측 불가라 임계값을 올려도 오탐이
# 남으므로, 생존은 명시 신호(Stopped/에러/Blank/프레임 고장)로만 판정한다.
# Idle 침묵은 "마지막 프레임이 그대로 유효하다"는 뜻 그대로 받아들인다.
#
# 쓸 수 있는 프레임이 아예 없는 상태를 무매칭으로 방치하지 않기 위한 상한.
_NO_FRAME_TIMEOUT_S = 2.0
# Blank/Suspended(보여줄 화면이 없는 상태)에서 빠져나올 때 감시 영역의 내용이
# 그대로면 SCStream은 Idle만 보내고 Complete를 주지 않아 프레임이 영영 돌아오지
# 않는다(실측 확인). 그래서 상한을 두고, 넘기면 사망 처리해 스트림을 다시 연다.
# 잠금이 길어지는 동안 불필요하게 자주 다시 열지 않도록 넉넉히 잡는다.
# (참고: 디스플레이 슬립은 이 경로가 아니라 didStopWithError로 관측됐다.)
_BLANK_TIMEOUT_S = 90.0

# 프레임이 없는 이유. 기한을 얼마로 걸지, 이미 걸린 기한을 덮어써도 되는지가
# 이유마다 다르다. 기동 직후는 이유 없이 기한만 걸린 상태다.
_GAP_BLANK = "blank"
_GAP_FAULT = "fault"

# SCStreamFrameInfoStatus
_FRAME_IDLE = 1
_FRAME_BLANK = 2
_FRAME_SUSPENDED = 3
_FRAME_STOPPED = 5
_SCK_CLASSES: dict[str, Any] = {}
# 실행 루프와 편집기가 동시에 첫 스트림을 열면 ObjC 클래스가 중복 정의된다.
_SCK_CLASSES_LOCK = threading.Lock()
_WARNED: set[str] = set()


class ScreenBackend(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def grab(self, groups: Sequence[Any]) -> list[ImageFrame | None]: ...

    def is_dead(self) -> bool: ...


class NullScreenBackend:
    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def grab(self, groups: Sequence[Any]) -> list[ImageFrame | None]:
        return [None] * len(groups)

    def is_dead(self) -> bool:
        return False


class MssScreenBackend:
    def __init__(self) -> None:
        self._sct: Any = None
        self._lock = threading.Lock()

    def open(self) -> None:
        # Quartz/ScreenCaptureKit 과 같은 이유로 동적 import 한다. mss 는
        # Windows 전용 의존성이라 macOS 에는 설치되지 않는다.
        mss: Any = _framework("mss")
        self._sct = mss.mss()

    def close(self) -> None:
        with self._lock:
            sct = self._sct
            self._sct = None
        if sct is None:
            return
        try:
            sct.close()
        except Exception as exc:
            # mss 의 Windows 백엔드는 핸들을 threading.local 에 둬서, 만든
            # 스레드가 아닌 곳에서 닫으면 AttributeError 가 난다. 실제 정리는
            # 그 스레드가 끝날 때 이뤄지므로 여기서 막지 않는다.
            logger.debug(f"mss close failed: {exc}")

    def grab(self, groups: Sequence[Any]) -> list[ImageFrame | None]:
        from app.core.processor import ImageFrame

        with self._lock:
            sct = self._sct
            if sct is None:
                return [None] * len(groups)
            return [
                ImageFrame.from_screenshot(sct.grab(group["rect"])) for group in groups
            ]

    def is_dead(self) -> bool:
        return False


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


def _framework(name: str) -> Any:
    return importlib.import_module(name)


def _warn_once(key: str, message: str) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    logger.warning(message)


def _buffer_view(base: Any, nbytes: int) -> memoryview:
    """픽셀 버퍼를 복사 없이 바이트 단위로 읽는 뷰."""
    source: Any = base
    as_buffer = getattr(source, "as_buffer", None)
    if callable(as_buffer):
        source = as_buffer(nbytes)
    try:
        return memoryview(source).cast("B")[:nbytes]
    except TypeError:
        import ctypes

        buf = (ctypes.c_ubyte * nbytes).from_address(int(source))
        return memoryview(buf).cast("B")


def frame_from_region(
    view: memoryview, stride: int, x: int, y: int, width: int, height: int
) -> ImageFrame:
    """픽셀 버퍼에서 요청한 영역만 잘라 담는다."""
    from app.core.processor import ImageFrame

    packed = width * 4
    dest = bytearray(height * packed)
    start = y * stride + x * 4
    for row in range(height):
        src_row = start + row * stride
        dest_row = row * packed
        dest[dest_row : dest_row + packed] = view[src_row : src_row + packed]
    return ImageFrame(
        width=width, height=height, data=dest, row_stride=packed, pixel_stride=4
    )


def copy_rects(
    buffer: Any, union: Rect, groups: Sequence[Any]
) -> list[ImageFrame | None] | None:
    """붙잡아 둔 프레임에서 요청한 영역들만 복사한다.

    콜백에서 union 전체를 복사하면 대부분을 버리게 된다. 편집기 미리보기는
    화면 전체를 스트리밍하면서 100x100만 쓰므로 차이가 크고, 영역이 마우스를
    따라 바뀌어도 읽는 시점에 자르므로 어긋나지 않는다.

    프레임을 쓸 수 없으면(크기 불일치 등) None을 돌려준다.
    """
    quartz: Any = _framework("Quartz")
    quartz.CVPixelBufferLockBaseAddress(buffer, _LOCK_READ_ONLY)
    try:
        src_w = int(quartz.CVPixelBufferGetWidth(buffer))
        src_h = int(quartz.CVPixelBufferGetHeight(buffer))
        stride = int(quartz.CVPixelBufferGetBytesPerRow(buffer))
        base = quartz.CVPixelBufferGetBaseAddress(buffer)
        if not base or stride < src_w * 4:
            return None
        if src_w != union["width"] or src_h != union["height"]:
            # 리샘플하면 색이 달라져 완전 일치 매칭이 조용히 어긋난다.
            _warn_once(
                f"size-{src_w}x{src_h}-{union['width']}x{union['height']}",
                f"SCStream frame {src_w}x{src_h} does not match requested "
                f"{union['width']}x{union['height']}; dropping frame",
            )
            return None
        view = _buffer_view(base, stride * src_h)
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
                or x + width > src_w
                or y + height > src_h
            ):
                frames.append(None)
                continue
            frames.append(frame_from_region(view, stride, x, y, width, height))
        return frames
    finally:
        quartz.CVPixelBufferUnlockBaseAddress(buffer, _LOCK_READ_ONLY)


def _handle_sample_buffer(
    backend: Any, sample_buffer: Any, core_media: Any, status_key: Any
) -> None:
    # 샘플 버퍼가 실린 이유(Complete/Idle/Blank/Suspended/Stopped).
    attachments = core_media.CMSampleBufferGetSampleAttachmentsArray(
        sample_buffer, False
    )
    raw_status = attachments[0].get(status_key) if attachments else None
    status = None if raw_status is None else int(raw_status)

    if status == _FRAME_STOPPED:
        backend.mark_dead()
        return

    if status == _FRAME_IDLE:
        # 화면이 바뀌지 않았다는 뜻. 마지막 프레임이 그대로 유효하다.
        return
    if status in (_FRAME_BLANK, _FRAME_SUSPENDED):
        # 잠금 화면·디스플레이 슬립처럼 보여줄 화면이 없는 상태. 대개 스스로
        # 복구되므로 프레임만 버리고 넉넉한 기한을 준다. 앱이 멈춘 것처럼
        # 보이는 구간이라 이유는 한 번 남긴다.
        _warn_once(
            "blank-frame",
            f"SCStream has no displayable content (status={status}); "
            "matching paused until it returns",
        )
        backend.drop_frame(fault=False)
        return

    buffer = core_media.CMSampleBufferGetImageBuffer(sample_buffer)
    if buffer is None:
        # 상태를 읽을 수 없는 환경에서의 idle 프레임과 같다.
        return
    # 여기서 복사하지 않는다. 읽는 쪽이 필요한 영역만 잘라 가면 되고,
    # 그래야 마우스를 따라 움직이는 미리보기 영역도 어긋나지 않는다.
    backend.hold_buffer(buffer)


def _sck_classes() -> dict[str, Any]:
    with _SCK_CLASSES_LOCK:
        return _sck_classes_locked()


def _sck_classes_locked() -> dict[str, Any]:
    if _SCK_CLASSES:
        return _SCK_CLASSES

    core_media: Any = _framework("CoreMedia")
    sck: Any = _framework("ScreenCaptureKit")
    ns_object: Any = _framework("Foundation").NSObject
    status_key: Any = sck.SCStreamFrameInfoStatus

    class SCStreamOutput(ns_object):
        backend: Any = None

        def stream_didOutputSampleBuffer_ofType_(
            self, _stream: Any, sample_buffer: Any, _output_type: int
        ) -> None:
            backend: Any = self.backend
            if backend is None:
                return
            # 콜백에서 예외가 새어 나가면 ObjC 예외로 승격돼 프로세스가 죽는다.
            try:
                _handle_sample_buffer(backend, sample_buffer, core_media, status_key)
            except Exception as exc:
                _warn_once("sample-buffer", f"SCStream frame dropped: {exc}")
                # 프레임을 못 받는 상태가 이어지면 정체로 인식돼 승계되도록
                # 마지막 프레임을 버린다. 두면 옛 화면으로 계속 매칭한다.
                try:
                    backend.drop_frame(fault=True)
                except Exception:
                    pass

    class SCStreamDelegate(ns_object):
        backend: Any = None

        def stream_didStopWithError_(self, _stream: Any, error: Any) -> None:
            backend: Any = self.backend
            if backend is None:
                return
            try:
                if error is not None:
                    logger.warning(f"SCStream stopped: {error}")
                backend.mark_dead()
            except Exception as exc:
                logger.warning(f"SCStream stop handler failed: {exc}")

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
    def __init__(self, union: Rect, fps: int = _STREAM_FPS) -> None:
        self.union = union
        self.fps = fps
        self.lock = threading.Lock()
        self.buffer: Any = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error: str | None = None
        self._stream: Any = None
        self._output: Any = None
        self._delegate: Any = None
        self._closed = False
        self._dead = False
        self.frame_deadline = 0.0
        self.frame_gap = ""

    @classmethod
    def from_groups(
        cls, groups: Sequence[Any], fps: int = _STREAM_FPS
    ) -> MacStreamBackend:
        return cls(union_group_rects(groups), fps)

    def open(self) -> None:
        self._closed = False
        # 진단 경고는 실행 단위로 다시 볼 수 있어야 한다.
        _WARNED.clear()
        with self.lock:
            self._dead = False
            self._replace_buffer_locked(None)
            self.frame_deadline = 0.0
            self.frame_gap = ""
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
        self._arm_initial_deadline()

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
            self._replace_buffer_locked(None)
            self.frame_deadline = 0.0
            self.frame_gap = ""

    def _mark_dead_locked(self) -> None:
        self._dead = True
        self._replace_buffer_locked(None)
        self.frame_deadline = 0.0
        self.frame_gap = ""

    def mark_dead(self) -> None:
        with self.lock:
            self._mark_dead_locked()

    def _arm_initial_deadline(self) -> None:
        """기동 직후 프레임이 오지 않는 경우의 기한.

        정체 판정은 스트림이 살아난 시점부터 센다. open() 진입 시각을 쓰면
        기동에 걸린 시간이 예산을 먹어 멀쩡한 스트림을 죽인다. 기동을 기다리는
        동안 이미 Blank나 고장이 도착했다면 그쪽 기한을 존중한다 — 덮어쓰면
        잠금 화면에서 2초마다 죽고 재기동을 반복한다.
        """
        with self.lock:
            if self.buffer is None and not self.frame_deadline:
                self.frame_deadline = time.perf_counter() + _NO_FRAME_TIMEOUT_S

    def hold_buffer(self, buffer: Any) -> None:
        """콜백이 새 프레임을 넘겨준다. 복사는 읽는 쪽에서 한다."""
        quartz: Any = _framework("Quartz")
        quartz.CVPixelBufferRetain(buffer)
        with self.lock:
            if self._dead:
                # 사망 처리 뒤 늦게 도착한 프레임. 보관하면 죽은 백엔드가
                # 화면을 들고 있는 상태가 된다.
                quartz.CVPixelBufferRelease(buffer)
                return
            self._replace_buffer_locked(buffer)
            self.frame_deadline = 0.0
            self.frame_gap = ""

    def _replace_buffer_locked(self, buffer: Any) -> None:
        old = self.buffer
        self.buffer = buffer
        if old is not None:
            _framework("Quartz").CVPixelBufferRelease(old)

    def drop_frame(self, *, fault: bool) -> None:
        """현재 프레임을 버리고, 언제까지 못 받으면 사망으로 볼지 기한을 건다.

        잠금 화면·슬립(fault=False)은 스스로 복구되므로 훨씬 긴 기한을 준다.
        기한은 이유가 바뀔 때만 다시 건다 — 프레임마다 연장하면 복구되지 않는
        스트림에 영원히 매달리고, Blank와 고장이 번갈아 와도 마찬가지가 된다.
        고장은 잠금보다 급해서 Blank 기한을 당기지만, 그 반대는 없다.
        """
        now = time.perf_counter()
        with self.lock:
            self._replace_buffer_locked(None)
            if fault:
                if self.frame_gap != _GAP_FAULT:
                    self.frame_gap = _GAP_FAULT
                    self.frame_deadline = now + _NO_FRAME_TIMEOUT_S
            elif self.frame_gap not in (_GAP_BLANK, _GAP_FAULT):
                self.frame_gap = _GAP_BLANK
                self.frame_deadline = now + _BLANK_TIMEOUT_S

    def is_dead(self) -> bool:
        with self.lock:
            return self._dead

    def is_dead_locked(self) -> bool:
        """락을 이미 쥔 쪽에서 쓰는 사망 여부."""
        return self._dead

    def grab(self, groups: Sequence[Any]) -> list[ImageFrame | None]:
        now = time.perf_counter()
        died = False
        quartz: Any = _framework("Quartz")
        # 판정과 사망 처리를 한 락 안에서 끝낸다. 락을 놓고 처리하면 그 사이에
        # 도착한 프레임을 무시하고 멀쩡한 스트림을 죽일 수 있다.
        with self.lock:
            buffer = None if self._dead else self.buffer
            if buffer is not None:
                quartz.CVPixelBufferRetain(buffer)
            elif not self._dead:
                # 쓸 수 있는 프레임이 없는 상태가 기한을 넘기면 사망으로
                # 승격시킨다. 그래야 재기동이 걸린다.
                if self.frame_deadline and now > self.frame_deadline:
                    self._mark_dead_locked()
                    died = True
        if died:
            logger.warning("SCStream has no usable frame; marking backend dead")
        if buffer is None:
            return [None] * len(groups)
        try:
            frames = copy_rects(buffer, self.union, groups)
        finally:
            quartz.CVPixelBufferRelease(buffer)
        if frames is None:
            # 프레임이 실려 왔는데 쓸 수 없다. 그대로 두면 옛 화면 기준으로
            # 키가 나가므로 버리고 기한을 건다.
            self.drop_frame(fault=True)
            return [None] * len(groups)
        return frames

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
        core_media: Any = _framework("CoreMedia")
        quartz: Any = _framework("Quartz")
        sck: Any = _framework("ScreenCaptureKit")

        content = _wait_shareable(5.0)
        displays = list(content.displays())
        if not displays:
            raise RuntimeError("no shareable displays")
        display = _display_for_union(displays, self.union)
        frame = display.frame()
        left = self.union["left"] - float(frame.origin.x)
        top = self.union["top"] - float(frame.origin.y)
        if (
            left < 0
            or top < 0
            or left + self.union["width"] > float(frame.size.width)
            or top + self.union["height"] > float(frame.size.height)
        ):
            # 그대로 넘기면 SCStream이 "invalid parameter"만 돌려줘 원인을
            # 알 수 없다. 다른 해상도에서 만든 프로필을 열면 흔히 생긴다.
            raise RuntimeError(
                f"capture area {self.union['width']}x{self.union['height']} at "
                f"({self.union['left']},{self.union['top']}) is outside the display "
                f"({int(frame.size.width)}x{int(frame.size.height)})"
            )
        source = quartz.CGRectMake(
            left, top, self.union["width"], self.union["height"]
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
        cfg.setMinimumFrameInterval_(core_media.CMTimeMake(1, self.fps))
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
        delegate = self._delegate
        self._stream = None
        self._output = None
        self._delegate = None
        if output is not None:
            output.backend = None
        if delegate is not None:
            delegate.backend = None
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
    fps: int = _STREAM_FPS,
) -> ScreenBackend:
    if not groups:
        return NullScreenBackend()
    name = os_name if os_name is not None else platform.system()
    if name == "Darwin":
        # macOS에서는 mss를 쓰지 않는다. 두 경로는 픽셀값이 달라, 기준색을
        # SCStream으로 찍은 프로필이 mss에서는 아무것도 매칭되지 않는다.
        return MacStreamBackend.from_groups(groups, fps)
    return MssScreenBackend()


def open_screen_backend(
    groups: Sequence[Any],
    *,
    os_name: str | None = None,
    fps: int = _STREAM_FPS,
) -> ScreenBackend:
    """백엔드를 열어 돌려준다.

    SCStream 기동에 실패하면(디스플레이 슬립, 권한 등) 사망 상태로 표시해
    돌려준다. 실행 루프가 그걸 보고 주기적으로 다시 열어보므로, 원인이
    사라지면 스스로 복구된다.
    """
    backend = create_screen_backend(groups, os_name=os_name, fps=fps)
    try:
        backend.open()
        return backend
    except Exception as exc:
        if not isinstance(backend, MacStreamBackend):
            raise
        logger.warning(f"SCStream unavailable, will retry: {exc}")
        backend.close()
        backend.mark_dead()
        return backend
