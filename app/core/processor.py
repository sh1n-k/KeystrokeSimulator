import asyncio
import ctypes
import importlib
import os
import platform
import random
import re
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, Protocol, TypedDict, cast

from loguru import logger
from mss.screenshot import ScreenShot
from PIL import Image

from app.core.models import EventModel, ModificationKeys, UserSettings
from app.core.screen_backend import (
    BACKEND_RETRY_INTERVAL_S as _BACKEND_RETRY_INTERVAL_S,
)
from app.core.screen_backend import (
    ScreenBackend,
    create_screen_backend,
    open_screen_backend,
)
from app.utils.keys import KeyUtils
from app.utils.system import MonitorUtils, ProcessUtils

Pixel = tuple[int, int, int]
Rect = dict[str, int]
KeyAction = Callable[[int], None]
ImageBytes = bytes | bytearray | memoryview


@dataclass(frozen=True)
class ImageFrame:
    width: int
    height: int
    data: ImageBytes
    row_stride: int
    pixel_stride: int
    offset: int = 0

    @classmethod
    def from_screenshot(cls, screenshot: ScreenShot) -> "ImageFrame":
        return cls(
            width=screenshot.width,
            height=screenshot.height,
            data=memoryview(screenshot.raw),
            row_stride=screenshot.width * 4,
            pixel_stride=4,
        )

    @classmethod
    def from_rgb_image(cls, img: Image.Image) -> "ImageFrame":
        rgb_img = img.convert("RGB")
        return cls(
            width=rgb_img.width,
            height=rgb_img.height,
            data=rgb_img.tobytes("raw", "BGR"),
            row_stride=rgb_img.width * 3,
            pixel_stride=3,
        )

    def crop(self, x: int, y: int, width: int, height: int) -> "ImageFrame":
        return ImageFrame(
            width=width,
            height=height,
            data=self.data,
            row_stride=self.row_stride,
            pixel_stride=self.pixel_stride,
            offset=self.offset + y * self.row_stride + x * self.pixel_stride,
        )

    def to_rgb_image(self) -> Image.Image:
        """편집기 미리보기용 RGB 이미지. crop된 프레임의 패딩을 걷어낸다."""
        packed = self.width * self.pixel_stride
        rows = bytearray(self.height * packed)
        for y in range(self.height):
            start = self.offset + y * self.row_stride
            rows[y * packed : (y + 1) * packed] = self.data[start : start + packed]
        raw_mode = "BGRX" if self.pixel_stride == 4 else "BGR"
        return Image.frombytes(
            "RGB", (self.width, self.height), bytes(rows), "raw", raw_mode
        )

    def pixel_bgr(self, x: int, y: int) -> Pixel:
        idx = self.offset + y * self.row_stride + x * self.pixel_stride
        return (
            int(self.data[idx]),
            int(self.data[idx + 1]),
            int(self.data[idx + 2]),
        )


def _pixel_from_object(value: object) -> Pixel | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    sequence = cast(Sequence[object], value)
    if len(sequence) < 3:
        return None

    channels: list[int] = []
    for channel in sequence[:3]:
        if not isinstance(channel, (int, float, str)):
            return None
        try:
            channels.append(int(channel))
        except (TypeError, ValueError, OverflowError):
            return None
    return (channels[0], channels[1], channels[2])


class CheckPoint(TypedDict):
    pos: tuple[int, int]
    color: Pixel


class EventData(TypedDict):
    name: str
    mode: str
    invert: bool
    key: str | None
    center_x: int
    center_y: int
    dur: float | None
    rand: float | None
    exec: bool
    group: str | None
    priority: int
    conds: dict[str, bool]
    runtime_toggle_member: bool
    region_w: int
    region_h: int
    rel_x: int
    rel_y: int
    screenless: NotRequired[bool]
    ref_img: NotRequired[ImageFrame]
    check_points: NotRequired[list[CheckPoint]]
    ref_bgr: NotRequired[Pixel]
    capture_rect: NotRequired[Rect]


class CaptureGroup(TypedDict):
    rect: Rect
    events: list[EventData]


class AppWithSettings(Protocol):
    settings: UserSettings


def _processor_perf_enabled() -> bool:
    return os.getenv("KEYSIM_PROFILE_PERF") == "1"


def _log_perf(label: str, start: float) -> None:
    if _processor_perf_enabled():
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        print(f"[perf] {label}: {elapsed_ms:.3f}ms")


def _normalize_key_name(
    key_codes: dict[str, int], key_name: str | None
) -> str | None:
    """Return the key name that exists in key_codes (case-insensitive)."""
    if not key_name:
        return None

    raw = key_name.strip()
    if not raw:
        return None

    if raw in key_codes:
        return raw

    upper = raw.upper()
    if upper in key_codes:
        return upper

    # Fallback: linear search with lower-case comparison to catch mixed case keys like "Space"
    lower = raw.lower()
    for k in key_codes:
        if k.lower() == lower:
            return k
    return None


def _noop_key_action(_code: int) -> None:
    return None


# user32 SendInput / MapVirtualKey constants
_INPUT_KEYBOARD = 1
_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008
_MAPVK_VK_TO_VSC = 0

# Navigation / editing VKs that require KEYEVENTF_EXTENDEDKEY on many layouts.
_WINDOWS_EXTENDED_VKS = frozenset(
    {
        0x21,  # Page Up
        0x22,  # Page Down
        0x23,  # End
        0x24,  # Home
        0x25,  # Left
        0x26,  # Up
        0x27,  # Right
        0x28,  # Down
        0x2D,  # Insert
        0x2E,  # Delete
    }
)

# Fixed Win32 widths so MSVC layout holds on both LLP64 (Windows) and LP64 hosts.
_WIN_WORD = ctypes.c_uint16
_WIN_DWORD = ctypes.c_uint32
_WIN_LONG = ctypes.c_int32
_WIN_ULONG_PTR = (
    ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32
)

_win_user32_ready = False


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", _WIN_WORD),
        ("wScan", _WIN_WORD),
        ("dwFlags", _WIN_DWORD),
        ("time", _WIN_DWORD),
        ("dwExtraInfo", _WIN_ULONG_PTR),
    )


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", _WIN_LONG),
        ("dy", _WIN_LONG),
        ("mouseData", _WIN_DWORD),
        ("dwFlags", _WIN_DWORD),
        ("time", _WIN_DWORD),
        ("dwExtraInfo", _WIN_ULONG_PTR),
    )


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", _WIN_DWORD),
        ("wParamL", _WIN_WORD),
        ("wParamH", _WIN_WORD),
    )


class _INPUT_UNION(ctypes.Union):
    _fields_ = (
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    )


class _INPUT(ctypes.Structure):
    _fields_ = (
        ("type", _WIN_DWORD),
        ("union", _INPUT_UNION),
    )


def _windows_use_scancode_path() -> bool:
    """Optional KEYEVENTF_SCANCODE-centric inject path (KEYSIM_WIN_SCANCODE=1)."""
    raw = os.getenv("KEYSIM_WIN_SCANCODE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _windows_is_extended_vk(code: int) -> bool:
    return code in _WINDOWS_EXTENDED_VKS


def _windows_expected_input_sizeof() -> int:
    """MSVC sizeof(INPUT): 40 on 64-bit, 28 on 32-bit."""
    return 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28


def _windows_user32() -> Any:
    return ctypes.__dict__["windll"].user32


def _configure_windows_input_apis() -> None:
    """Bind SendInput/MapVirtualKey prototypes once."""
    global _win_user32_ready
    if _win_user32_ready:
        return
    user32 = _windows_user32()
    map_virtual_key = user32.MapVirtualKeyW
    send_input = user32.SendInput
    map_virtual_key.argtypes = [ctypes.c_uint, ctypes.c_uint]
    map_virtual_key.restype = ctypes.c_uint
    send_input.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
    send_input.restype = ctypes.c_uint
    _win_user32_ready = True


def _windows_map_vk_to_scan(code: int) -> int:
    _configure_windows_input_apis()
    map_virtual_key = cast(
        Callable[[int, int], int], _windows_user32().MapVirtualKeyW
    )
    return int(map_virtual_key(int(code) & 0xFFFF, _MAPVK_VK_TO_VSC)) & 0xFF


def _windows_build_keybdinput(code: int, *, key_up: bool) -> _KEYBDINPUT:
    vk = int(code) & 0xFFFF
    scan = _windows_map_vk_to_scan(vk)
    flags = 0
    if _windows_is_extended_vk(vk):
        flags |= _KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= _KEYEVENTF_KEYUP

    prefer_scancode = _windows_use_scancode_path()
    if prefer_scancode and scan == 0:
        logger.warning(
            f"MapVirtualKey returned 0 for vk=0x{vk:02X}; falling back to VK path"
        )
        prefer_scancode = False

    if prefer_scancode:
        # Scan-code path for titles that ignore virtual-key-only events.
        flags |= _KEYEVENTF_SCANCODE
        return _KEYBDINPUT(0, scan, flags, 0, 0)

    # Default: SendInput with VK + scan code (still user32 low-level).
    return _KEYBDINPUT(vk, scan, flags, 0, 0)


def _windows_send_key(code: int, *, key_up: bool) -> None:
    _configure_windows_input_apis()
    send_input = cast(Callable[..., int], _windows_user32().SendInput)
    inp = _INPUT(
        type=_INPUT_KEYBOARD,
        union=_INPUT_UNION(ki=_windows_build_keybdinput(code, key_up=key_up)),
    )
    cb_size = ctypes.sizeof(_INPUT)
    expected = _windows_expected_input_sizeof()
    if cb_size != expected:
        logger.error(
            f"INPUT sizeof mismatch: got {cb_size}, expected {expected} for this pointer width"
        )
    sent = int(send_input(1, ctypes.byref(inp), cb_size))
    if sent != 1:
        logger.warning(
            f"SendInput returned {sent} for vk=0x{int(code) & 0xFFFF:02X} key_up={key_up}"
        )


def _windows_key_press(code: int) -> None:
    _windows_send_key(code, key_up=False)


def _windows_key_release(code: int) -> None:
    _windows_send_key(code, key_up=True)


def _darwin_key_event(code: int, pressed: bool) -> None:
    quartz = importlib.import_module("Quartz")
    source_create = cast(Callable[[object], object], quartz.CGEventSourceCreate)
    create_event = cast(
        Callable[[object, int, bool], object], quartz.CGEventCreateKeyboardEvent
    )
    post_event = cast(Callable[[object, object], None], quartz.CGEventPost)
    source = source_create(quartz.kCGEventSourceStateHIDSystemState)
    event = create_event(source, code, pressed)
    if event is None:
        logger.warning(
            f"CGEventCreateKeyboardEvent failed for code={code} pressed={pressed}"
        )
        return
    post_event(quartz.kCGHIDEventTap, event)


def _darwin_key_press(code: int) -> None:
    _darwin_key_event(code, True)


def _darwin_key_release(code: int) -> None:
    _darwin_key_event(code, False)


class KeySimulator:
    def __init__(self, os_type: str) -> None:
        self.os_type = os_type
        if os_type == "Windows":
            self.press: KeyAction = _windows_key_press
            self.release: KeyAction = _windows_key_release
        elif os_type == "Darwin":
            self.press = _darwin_key_press
            self.release = _darwin_key_release
        else:
            self.press = self.release = _noop_key_action


class ModificationKeyHandler:
    def __init__(
        self,
        key_codes: dict[str, int],
        default_press_times: tuple[float, float],
        mod_keys: ModificationKeys,
        os_type: str,
        *,
        sim: KeySimulator | None = None,
        key_lock: threading.Lock | None = None,
        pressed_keys: set[str] | None = None,
        pressed_key_codes: dict[str, int] | None = None,
        term_event: threading.Event | None = None,
    ) -> None:
        self.key_codes = key_codes
        # press_time: (min_sec, max_sec) 튜플
        self.press_time = default_press_times
        # 설정에서 enabled된 키만 필터링
        self.mod_keys = {k: v for k, v in mod_keys.items() if v.get("enabled")}
        self.sim = sim if sim is not None else KeySimulator(os_type)
        self.key_lock = key_lock
        self.pressed_keys = pressed_keys
        self.pressed_key_codes = pressed_key_codes
        self.term_event = term_event
        self.event = threading.Event()

    async def check_and_process(self) -> bool:
        if not self.mod_keys:
            return False

        active = False
        tasks: list[Awaitable[None]] = []

        # 설정된 ModKey들을 순회하며 물리적 눌림 확인
        for k, v in self.mod_keys.items():
            if KeyUtils.mod_key_pressed(k):
                active = True
                # 'Pass' 설정이 아닐 경우(다른 키로 매핑된 경우) 키 입력 시뮬레이션
                if not v.get("pass") and (val := v.get("value")):
                    if isinstance(val, str):
                        tasks.append(self._sim_key(val))

        # 매핑된 키 입력 병렬 실행
        if tasks:
            await asyncio.gather(*tasks)

        if active:
            self.event.set()
        else:
            self.event.clear()

        return active

    async def _sim_key(self, key_name: str) -> None:
        norm_key = _normalize_key_name(self.key_codes, key_name)
        if not norm_key:
            return
        code = self.key_codes.get(norm_key)
        if code is None:
            return

        tracked = False
        lock = self.key_lock
        pressed_keys = self.pressed_keys
        pressed_key_codes = self.pressed_key_codes
        if lock is not None and pressed_keys is not None and pressed_key_codes is not None:
            with lock:
                if norm_key in pressed_keys:
                    return
                pressed_keys.add(norm_key)
                pressed_key_codes[norm_key] = code
            tracked = True

        down = False
        release_failed = False
        try:
            self.sim.press(code)
            down = True
            await self._wait_hold_async(random.uniform(*self.press_time))
        finally:
            if down:
                try:
                    self.sim.release(code)
                except Exception as exc:
                    release_failed = True
                    logger.warning(
                        f"Modification key release failed for {norm_key!r}: {exc}"
                    )
            if tracked and lock is not None and pressed_keys is not None and pressed_key_codes is not None:
                with lock:
                    if release_failed:
                        pressed_keys.add(norm_key)
                        pressed_key_codes[norm_key] = code
                    else:
                        pressed_keys.discard(norm_key)
                        pressed_key_codes.pop(norm_key, None)

    async def _wait_hold_async(
        self, duration: float, check_interval: float = 0.02
    ) -> None:
        """Hold duration, aborting early when processor term_event is set."""
        if duration <= 0:
            return
        end_time = time.time() + duration
        term = self.term_event
        while time.time() < end_time:
            if term is not None and term.is_set():
                break
            remaining = end_time - time.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(check_interval, remaining))


class KeystrokeProcessor:
    PID_REGEX = re.compile(r"\((\d+)\)")
    # While Pass/mod is held, skip capture but poll often so release leads
    # promptly into a fresh grab/match (not an extra 100ms back-off).
    MOD_ACTIVE_POLL_INTERVAL = 0.02
    # 백엔드가 죽었을 때 다시 여는 최소 간격. 디스플레이 슬립처럼 원인이
    # 지속되는 동안 매 사이클 재시도하지 않도록 한다.
    BACKEND_RETRY_INTERVAL_S = _BACKEND_RETRY_INTERVAL_S

    def __init__(
        self,
        main_app: AppWithSettings,
        target_proc: str,
        events: list[EventModel],
        mod_keys: ModificationKeys,
        term_event: threading.Event,
    ) -> None:
        self.main_app = main_app
        self.term_event = term_event
        self.os_type = platform.system()

        # PID Parsing
        match = self.PID_REGEX.search(target_proc)
        self.pid = int(match.group(1)) if match else None

        # Settings (초 단위로 저장)
        s = main_app.settings
        self.delays = (s.delay_between_loop_min / 1000, s.delay_between_loop_max / 1000)
        self.default_press_times = (
            s.key_pressed_time_min / 1000,
            s.key_pressed_time_max / 1000,
        )

        self.key_codes = KeyUtils.get_key_list()
        self.sim = KeySimulator(self.os_type)

        # Thread Safety & State
        self.key_lock = threading.Lock()
        self.state_lock = threading.Lock()

        self.pressed_keys: set[str] = set()
        # Tracks key name → code for force-release on stop.
        self.pressed_key_codes: dict[str, int] = {}
        self.current_states: dict[str, bool] = {}
        self.runtime_toggle_active = False
        self._roi_warn_logged: set[str] = set()
        self._unsupported_key_warned: set[str] = set()

        self.mod_handler = ModificationKeyHandler(
            self.key_codes,
            self.default_press_times,
            mod_keys,
            self.os_type,
            sim=self.sim,
            key_lock=self.key_lock,
            pressed_keys=self.pressed_keys,
            pressed_key_codes=self.pressed_key_codes,
            term_event=self.term_event,
        )

        self.event_data_list: list[EventData] = self._init_event_data(events)
        self.main_capture_groups: list[CaptureGroup] = self._build_capture_groups(
            self.event_data_list
        )

        self._screen_backend: ScreenBackend | None = None
        self._backend_retry_failed = False
        self._last_backend_retry = 0.0
        # term_event는 앱이 재시작할 때 clear한다(simulator_app). 그 사이 이
        # 프로세서가 아직 살아 있으면 되살아나 새 프로세서와 동시에 키를
        # 누르게 되므로, 자기 자신의 종료는 별도로 기억한다.
        self._stopped = threading.Event()
        self._backend_closers: list[threading.Thread] = []
        self.loop = asyncio.new_event_loop()
        self.main_thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self) -> None:
        logger.info(f"Processor starting... PID: {self.pid}")
        self.main_thread.start()

    def _should_stop(self) -> bool:
        return self._stopped.is_set() or self.term_event.is_set()

    def stop(self) -> None:
        logger.info("Processor stopping...")
        self._stopped.set()
        self.term_event.set()

        if self.main_thread.is_alive():
            self.main_thread.join(timeout=1.0)
            if self.main_thread.is_alive():
                logger.warning(
                    "Processor thread did not stop within timeout; force-releasing keys"
                )
        # 루프가 백엔드 교체 중이었다면 join 타임아웃 뒤에 _screen_backend가
        # 되살아날 수 있다. 스레드가 끝난 뒤 한 번 더 확인한다.
        for _ in range(2):
            backend = getattr(self, "_screen_backend", None)
            if backend is not None:
                # 닫기 실패가 아래 force-release 를 막으면 키가 눌린 채 남는다.
                try:
                    backend.close()
                except Exception as exc:
                    logger.warning(f"Screen backend close failed: {exc}")
                self._screen_backend = None
            if not self.main_thread.is_alive():
                break
            self.main_thread.join(timeout=1.0)
        self._join_backend_closers()
        self._force_release_pressed_keys()

    def _force_release_pressed_keys(self) -> None:
        """Best-effort OS key-up for any keys still tracked as down."""
        with self.key_lock:
            pending = list(self.pressed_key_codes.items())
            self.pressed_key_codes.clear()
            self.pressed_keys.clear()

        failed: dict[str, int] = {}
        for key_name, code in pending:
            try:
                self.sim.release(code)
                logger.debug(f"Force-released key {key_name!r} (code={code})")
            except Exception as exc:
                failed[key_name] = code
                logger.warning(f"Force-release failed for {key_name!r}: {exc}")

        if failed:
            with self.key_lock:
                self.pressed_key_codes.update(failed)
                self.pressed_keys.update(failed)

    def _warn_unsupported_key(self, event_name: str, raw_key: str) -> None:
        if not hasattr(self, "_unsupported_key_warned"):
            self._unsupported_key_warned = set()
        warn_key = f"{event_name}\0{raw_key}"
        if warn_key in self._unsupported_key_warned:
            return
        self._unsupported_key_warned.add(warn_key)
        os_label = getattr(self, "os_type", platform.system())
        logger.warning(
            f"Event '{event_name}': unsupported key {raw_key!r} on {os_label}; "
            "key press will be skipped"
        )

    def _init_event_data(self, raw_events: list[EventModel]) -> list[EventData]:
        events_data: list[EventData] = []

        for e in raw_events:
            if not e.use_event:
                continue

            if e.is_screenless_input():
                raw_key = e.key_to_enter
                key = (
                    _normalize_key_name(self.key_codes, raw_key) if raw_key else None
                )
                if raw_key and raw_key.strip() and key is None:
                    self._warn_unsupported_key(
                        e.event_name or "Unknown", raw_key.strip()
                    )
                events_data.append(
                    {
                        "name": e.event_name or "Unknown",
                        "mode": "none",
                        "invert": False,
                        "key": key,
                        "center_x": 0,
                        "center_y": 0,
                        "dur": e.press_duration_ms,
                        "rand": e.randomization_ms,
                        "exec": True,
                        "group": e.group_id,
                        "priority": e.priority,
                        "conds": e.conditions,
                        "runtime_toggle_member": bool(e.runtime_toggle_member),
                        "region_w": 1,
                        "region_h": 1,
                        "rel_x": 0,
                        "rel_y": 0,
                        "screenless": True,
                    }
                )
                continue

            mode = e.match_mode or "pixel"
            latest_position = e.latest_position
            clicked_position = e.clicked_position
            if latest_position is None or clicked_position is None:
                continue

            if mode == "pixel":
                if not e.ref_pixel_value or len(e.ref_pixel_value) < 3:
                    continue

            center_x = latest_position[0] + clicked_position[0]
            center_y = latest_position[1] + clicked_position[1]
            raw_key = e.key_to_enter
            key = (
                _normalize_key_name(self.key_codes, raw_key) if raw_key else None
            )
            if raw_key and raw_key.strip() and key is None:
                self._warn_unsupported_key(e.event_name or "Unknown", raw_key.strip())

            evt_data: EventData = {
                "name": e.event_name or "Unknown",
                "mode": mode,
                "invert": e.invert_match,
                "key": key,
                "center_x": center_x,
                "center_y": center_y,
                "dur": e.press_duration_ms,
                "rand": e.randomization_ms,
                "exec": e.execute_action,
                "group": e.group_id,
                "priority": e.priority,
                "conds": e.conditions,
                "runtime_toggle_member": bool(e.runtime_toggle_member),
                "region_w": 1,
                "region_h": 1,
                "rel_x": 0,
                "rel_y": 0,
            }

            if evt_data["mode"] == "region":
                if e.held_screenshot is None:
                    continue
                r_size = e.region_size
                w, h = r_size if r_size else (20, 20)
                evt_data["region_w"], evt_data["region_h"] = w, h

                if e.held_screenshot:
                    full_img = ImageFrame.from_rgb_image(e.held_screenshot)
                    cx, cy = clicked_position
                    y1, y2 = (
                        max(0, cy - h // 2),
                        min(full_img.height, cy + h // 2 + (h % 2)),
                    )
                    x1, x2 = (
                        max(0, cx - w // 2),
                        min(full_img.width, cx + w // 2 + (w % 2)),
                    )
                    evt_data["ref_img"] = full_img.crop(x1, y1, x2 - x1, y2 - y1)

                    ref_img = evt_data["ref_img"]
                    rh, rw = ref_img.height, ref_img.width
                    if rh > 0 and rw > 0:
                        # Target count (actual may be less after dedup for very small ROIs)
                        n = max(5, min(25, (rw * rh) // 100))
                        cols = max(2, int(n**0.5))
                        rows = max(2, (n + cols - 1) // cols)
                        pts = list(
                            dict.fromkeys(
                                (
                                    int((rw - 1) * c / (cols - 1)),
                                    int((rh - 1) * r / (rows - 1)),
                                )
                                for r in range(rows)
                                for c in range(cols)
                            )
                        )
                        evt_data["check_points"] = [
                            {
                                "pos": (px, py),
                                "color": ref_img.pixel_bgr(px, py),
                            }
                            for px, py in pts
                        ]
                if "check_points" not in evt_data:
                    continue
            else:
                if e.ref_pixel_value is None:
                    continue
                ref_rgb = e.ref_pixel_value[:3]
                evt_data["ref_bgr"] = (
                    int(ref_rgb[2]),
                    int(ref_rgb[1]),
                    int(ref_rgb[0]),
                )

            events_data.append(evt_data)

        return events_data

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._process_main())
        except Exception as e:
            logger.error(f"Main loop crashed: {e}")
        finally:
            self.loop.close()

    async def _process_main(self) -> None:
        if not self.event_data_list:
            return

        last_proc_check_time = 0
        is_proc_active_cached = True
        proc_check_interval = 0.3
        backend = open_screen_backend(self.main_capture_groups)
        self._screen_backend = backend
        try:
            while not self._should_stop():
                current_time = time.time()
                if self.pid and (
                    current_time - last_proc_check_time > proc_check_interval
                ):
                    is_proc_active_cached = ProcessUtils.is_process_active(self.pid)
                    last_proc_check_time = current_time
                    if not is_proc_active_cached:
                        await asyncio.sleep(0.5)
                        continue

                if self.pid and not is_proc_active_cached:
                    await asyncio.sleep(0.1)
                    continue

                if await self.mod_handler.check_and_process():
                    await asyncio.sleep(self.MOD_ACTIVE_POLL_INTERVAL)
                    continue

                try:
                    cycle_started = time.perf_counter()
                    if backend.is_dead():
                        backend = self._replace_dead_backend(backend)
                    local_match_states = self._capture_match_states(backend)
                    if local_match_states is not None:
                        await self._apply_local_match_states(local_match_states)
                    _log_perf("processor_main_cycle", cycle_started)
                except Exception as e:
                    logger.error(f"Capture failed: {e}")

                await asyncio.sleep(random.uniform(*self.delays))
        finally:
            backend.close()
            if self._screen_backend is backend:
                self._screen_backend = None
            self._join_backend_closers()

    @staticmethod
    def _clamp_to_screen(rect: Rect, screen_w: int, screen_h: int) -> Rect | None:
        """화면 안으로 잘라낸 캡처 영역. 완전히 벗어나면 None."""
        left = max(0, rect["left"])
        top = max(0, rect["top"])
        right = min(screen_w, rect["left"] + rect["width"])
        bottom = min(screen_h, rect["top"] + rect["height"])
        if right - left < 1 or bottom - top < 1:
            return None
        return {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }

    @staticmethod
    def _rect_area(rect: Rect) -> int:
        return max(1, rect["width"]) * max(1, rect["height"])

    @staticmethod
    def _merge_rects(rect_a: Rect, rect_b: Rect) -> Rect:
        left = min(rect_a["left"], rect_b["left"])
        top = min(rect_a["top"], rect_b["top"])
        right = max(rect_a["left"] + rect_a["width"], rect_b["left"] + rect_b["width"])
        bottom = max(rect_a["top"] + rect_a["height"], rect_b["top"] + rect_b["height"])
        return {
            "left": left,
            "top": top,
            "width": max(1, right - left),
            "height": max(1, bottom - top),
        }

    def _assign_group_relative_coords(self, group: CaptureGroup) -> None:
        rect = group["rect"]
        for evt in group["events"]:
            evt["rel_x"] = evt["center_x"] - rect["left"]
            evt["rel_y"] = evt["center_y"] - rect["top"]

    def _build_capture_groups(self, events_data: list[EventData]) -> list[CaptureGroup]:
        if not events_data:
            return []

        max_group_area = 250_000
        max_gap = 160
        sorted_events = sorted(
            events_data,
            key=lambda evt: (evt["center_x"], evt["center_y"], evt.get("name", "")),
        )
        groups: list[CaptureGroup] = []

        # 화면 밖 영역을 거부하는 것은 SCStream 제약이다. mss 는 전역 좌표를
        # 그대로 잡으므로 Windows 에서는 손대지 않는다.
        bounds = (
            MonitorUtils.get_primary_size() if self.os_type == "Darwin" else None
        )
        for evt in sorted_events:
            if evt.get("screenless"):
                continue
            clamped = (
                self._clamp_to_screen(self._build_capture_rect(evt), *bounds)
                if bounds
                else self._build_capture_rect(evt)
            )
            if clamped is None:
                # 화면 밖 좌표를 그대로 캡처 영역에 넣으면 스트림이 아예 열리지
                # 않아 프로필 전체가 무매칭이 된다. 해당 이벤트만 뺀다.
                size = f"{bounds[0]}x{bounds[1]}" if bounds else "screen"
                logger.warning(
                    f"Event '{evt.get('name', '?')}': capture point is outside the "
                    f"screen ({size}); event will never match"
                )
                continue
            evt_rect = clamped
            evt["capture_rect"] = evt_rect
            if not groups:
                groups.append({"rect": evt_rect.copy(), "events": [evt]})
                continue

            current = groups[-1]
            current_rect = current["rect"]
            merged = self._merge_rects(current_rect, evt_rect)
            gap_x = max(
                evt_rect["left"] - (current_rect["left"] + current_rect["width"]),
                current_rect["left"] - (evt_rect["left"] + evt_rect["width"]),
                0,
            )
            gap_y = max(
                evt_rect["top"] - (current_rect["top"] + current_rect["height"]),
                current_rect["top"] - (evt_rect["top"] + evt_rect["height"]),
                0,
            )
            merged_area = self._rect_area(merged)
            if merged_area > max_group_area or gap_x > max_gap or gap_y > max_gap:
                groups.append({"rect": evt_rect.copy(), "events": [evt]})
                continue

            current["rect"] = merged
            current["events"].append(evt)

        for group in groups:
            self._assign_group_relative_coords(group)
        return groups

    def _select_by_group_priority(self, events: list[EventData]) -> list[EventData]:
        """그룹별 우선순위로 이벤트 선택"""
        groups: dict[str, list[EventData]] = {}
        no_group: list[EventData] = []

        for evt in events:
            if evt["group"]:
                groups.setdefault(evt["group"], []).append(evt)
            else:
                no_group.append(evt)

        # 각 그룹에서 최고 우선순위 이벤트만 선택
        final_events = [
            min(
                grp_evts,
                key=lambda e: (e["priority"], str(e.get("name") or "").strip()),
            )
            for grp_evts in groups.values()
        ]
        final_events.extend(no_group)

        return final_events

    @staticmethod
    def _event_execution_signature(evt: EventData) -> tuple[object, ...]:
        """실행 직전 dedupe에 사용할 서명(동일 입력만 병합)."""
        mode = evt.get("mode")
        if mode == "region":
            checkpoints = tuple(
                (
                    tuple(pt.get("pos", (None, None))),
                    _pixel_from_object(pt.get("color")),
                )
                for pt in evt.get("check_points", [])
            )
            match_sig: tuple[object, ...] = (
                "region",
                evt.get("region_w"),
                evt.get("region_h"),
                checkpoints,
            )
        else:
            ref = evt.get("ref_bgr")
            ref_bgr = _pixel_from_object(ref) if ref is not None else None
            match_sig = ("pixel", ref_bgr)

        conds = evt.get("conds", {})
        cond_sig = tuple(sorted((str(k), bool(v)) for k, v in conds.items()))

        return (
            evt.get("center_x"),
            evt.get("center_y"),
            match_sig,
            evt.get("invert", False),
            evt.get("key"),
            evt.get("dur"),
            evt.get("rand"),
            evt.get("group"),
            evt.get("priority"),
            cond_sig,
        )

    def _dedupe_events_for_execution(
        self, events: list[EventData]
    ) -> list[EventData]:
        seen: set[tuple[object, ...]] = set()
        deduped: list[EventData] = []
        for evt in events:
            signature = self._event_execution_signature(evt)
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(evt)
        return deduped

    def set_runtime_toggle_active(self, active: bool) -> bool:
        active = bool(active)
        with self.state_lock:
            self.runtime_toggle_active = active
            if not active:
                for evt in self.event_data_list:
                    if evt.get("runtime_toggle_member"):
                        self.current_states[evt["name"]] = False
        return active

    def _resolve_effective_states(
        self, local_match_states: dict[str, bool]
    ) -> dict[str, bool]:
        """
        조건 체인을 포함한 '실제 활성 상태' 계산.
        - raw match가 False면 비활성
        - raw match가 True여도 조건 불일치면 비활성
        - 같은 루프 내 이벤트 조건은 재귀적으로 해석(엄격 체인)
        """
        events_by_name = {evt["name"]: evt for evt in self.event_data_list}
        with self.state_lock:
            base_states = dict(self.current_states)
            runtime_toggle_active = bool(self.runtime_toggle_active)

        resolved: dict[str, bool] = {}
        visiting: set[str] = set()

        def resolve(name: str) -> bool:
            if name in resolved:
                return resolved[name]
            if name in visiting:
                # 편집기에서 순환을 막지만, 방어적으로 False 처리
                return False

            evt = events_by_name.get(name)
            if not evt:
                return base_states.get(name, False)

            if evt.get("runtime_toggle_member") and not runtime_toggle_active:
                resolved[name] = False
                return False

            if not local_match_states.get(name, False):
                resolved[name] = False
                return False

            visiting.add(name)
            for cond_name, expected in evt["conds"].items():
                if cond_name in events_by_name:
                    cond_value = resolve(cond_name)
                else:
                    cond_value = base_states.get(cond_name, False)

                if cond_value != expected:
                    visiting.discard(name)
                    resolved[name] = False
                    return False

            visiting.discard(name)
            resolved[name] = True
            return True

        for evt_name in events_by_name:
            resolve(evt_name)

        return resolved

    def _join_backend_closers(self) -> None:
        """교체 직후 중지하면 이전 스트림이 정리되기 전에 끝날 수 있다."""
        for closer in getattr(self, "_backend_closers", []):
            closer.join(timeout=2.5)
        self._backend_closers = []

    def _replace_dead_backend(self, backend: ScreenBackend) -> ScreenBackend:
        """죽은 백엔드를 다시 연다. 그대로 두면 조용히 무매칭이 된다.

        macOS에서는 mss로 내려가지 않는다. 픽셀값이 달라 기준색과 맞지 않아
        강등이 곧 무매칭이기 때문이다. 원인이 사라질 때까지 계속 다시 연다.
        """
        if self._should_stop():
            # 종료 중에는 새 스트림을 열지 않는다. stop()이 이미 정리를 끝낸
            # 뒤에 백엔드가 되살아나면 스트림이 정리되지 않은 채 남는다.
            return backend
        now = time.monotonic()
        if now - self._last_backend_retry < self.BACKEND_RETRY_INTERVAL_S:
            return backend
        try:
            replacement = create_screen_backend(self.main_capture_groups)
            replacement.open()
        except Exception as exc:
            # 다음 주기에 다시 시도하되 로그는 한 번만 남긴다.
            if not self._backend_retry_failed:
                self._backend_retry_failed = True
                logger.error(f"Screen backend restart failed: {exc}")
            return backend
        finally:
            # 실패 경로가 수 초 걸릴 수 있다. 간격은 시도가 '끝난' 뒤부터
            # 세야 루프가 open() 안에 갇히지 않는다.
            self._last_backend_retry = time.monotonic()
        if self._should_stop():
            # 여는 동안 중지됐다. stop()이 이미 정리를 끝냈을 수 있으므로
            # 새 백엔드를 남기지 않는다.
            replacement.close()
            return backend
        # 죽은 백엔드의 close()는 스트림 스레드 조인으로 최대 2초가 걸린다.
        # 실행 루프를 그동안 멈춰 세우지 않도록 분리한다. 여기서 이전 closer를
        # 기다리면(join) 연속 교체 때 루프가 멈춰 눌린 키가 늘어지므로,
        # 끝난 것만 걷어내고 정리는 중지 시점에 몰아서 한다.
        self._backend_closers = [
            closer for closer in self._backend_closers if closer.is_alive()
        ]
        closer = threading.Thread(target=backend.close, daemon=True)
        self._backend_closers.append(closer)
        closer.start()
        logger.warning("Screen backend stopped; restarted")
        self._backend_retry_failed = False
        self._screen_backend = replacement
        return replacement

    def _capture_match_states(self, backend: ScreenBackend) -> dict[str, bool] | None:
        """캡처가 온전한 사이클의 매칭 상태. 한 그룹이라도 못 읽으면 None."""
        local_match_states: dict[str, bool] = {}
        frames = backend.grab(self.main_capture_groups)
        for group, img in zip(self.main_capture_groups, frames, strict=True):
            if img is None:
                # 못 읽은 화면을 '불일치'로 단정하면 부정 조건(conds=False)이
                # 참이 되어 screenless 이벤트의 키가 잘못 나간다.
                return None
            local_match_states.update(
                self._evaluate_capture_group(img, group["events"])
            )
        return local_match_states

    def _evaluate_capture_group(
        self, img: ImageFrame, events: list[EventData]
    ) -> dict[str, bool]:
        local_match_states: dict[str, bool] = {}
        for evt in events:
            local_match_states[evt["name"]] = self._check_match(img, evt)
        return local_match_states

    async def _apply_local_match_states(
        self, local_match_states: dict[str, bool]
    ) -> None:
        match_states = dict(local_match_states)
        for evt in self.event_data_list:
            if evt.get("screenless"):
                match_states[evt["name"]] = True
        local_states = self._resolve_effective_states(match_states)

        with self.state_lock:
            self.current_states.update(local_states)

        # 3. 활성 이벤트 선별
        active_candidates = [
            evt for evt in self.event_data_list if local_states.get(evt["name"], False)
        ]

        # 4. 키 입력 실행 후보에만 그룹 우선순위를 적용
        executable_candidates = [evt for evt in active_candidates if evt["exec"]]
        final_events = self._select_by_group_priority(executable_candidates)
        final_events = self._dedupe_events_for_execution(final_events)

        # 5. 키 입력 실행
        tasks = [
            self._press_key_async(evt, local_states)
            for evt in final_events
            if not self.term_event.is_set()
        ]

        if tasks:
            await asyncio.gather(*tasks)

    def _build_capture_rect(self, evt: EventData) -> Rect:
        """이벤트에 대한 캡처 영역 생성"""
        cx, cy = evt["center_x"], evt["center_y"]
        if evt["mode"] == "region":
            w, h = evt["region_w"], evt["region_h"]
            return {"top": cy - h // 2, "left": cx - w // 2, "width": w, "height": h}
        return {"top": cy, "left": cx, "width": 1, "height": 1}

    def _extract_roi(self, img: ImageFrame, evt: EventData) -> ImageFrame | None:
        """이미지에서 관심 영역(ROI) 추출"""
        w, h = evt["region_w"], evt["region_h"]
        x, y = evt["rel_x"] - w // 2, evt["rel_y"] - h // 2

        # 경계 검사
        if x < 0 or y < 0 or x + w > img.width or y + h > img.height:
            name = evt.get("name", "?")
            if not hasattr(self, "_roi_warn_logged"):
                self._roi_warn_logged = set()
            if name not in self._roi_warn_logged:
                self._roi_warn_logged.add(name)
                logger.warning(
                    f"Event '{name}': ROI extraction failed — "
                    f"region_size({w}×{h}) exceeds capture area "
                    f"({img.width}×{img.height}). Matching will always return False."
                )
            return None

        return img.crop(x, y, w, h)

    def _check_match(self, img: ImageFrame, evt: EventData) -> bool:
        if evt.get("screenless"):
            return True
        matched = False
        evaluated = False
        try:
            if evt["mode"] == "region":
                check_points = evt.get("check_points")
                if not check_points:
                    return False
                roi = self._extract_roi(img, evt)
                if roi is None:
                    return False

                # 체크포인트 검증
                for pt in check_points:
                    px, py = pt["pos"]
                    if py >= roi.height or px >= roi.width:
                        continue
                    # 색상 비교
                    if roi.pixel_bgr(px, py) != pt["color"]:
                        matched = False
                        evaluated = True
                        break
                else:
                    matched = True
                    evaluated = True
            else:
                ref_bgr = evt.get("ref_bgr")
                if ref_bgr is None:
                    return False
                # 픽셀 모드
                py, px = evt["rel_y"], evt["rel_x"]
                if py >= img.height or px >= img.width:
                    return False
                pixel = img.pixel_bgr(px, py)
                matched = pixel == ref_bgr
                evaluated = True
        except Exception:
            return False
        if evt.get("invert") and evaluated:
            return not matched
        return matched

    def _calculate_press_duration(self, evt: EventData) -> float:
        """목표 키 누름 지속 시간 계산 (초 단위)"""
        duration_ms = evt["dur"]
        randomization_ms = evt["rand"]
        duration = (
            duration_ms / 1000.0
            if duration_ms
            else random.uniform(*self.default_press_times)
        )
        if randomization_ms:
            duration += (
                random.uniform(-randomization_ms, randomization_ms) / 1000.0
            )
        return max(0.05, duration)

    def _snapshot_condition_states(
        self, evt: EventData, state_snapshot: dict[str, bool] | None = None
    ) -> dict[str, bool]:
        conds = evt.get("conds", {})
        if not conds:
            return {}

        if state_snapshot is not None:
            return {
                cond_name: bool(state_snapshot.get(cond_name, False))
                for cond_name in conds
            }

        with self.state_lock:
            return {
                cond_name: bool(self.current_states.get(cond_name, False))
                for cond_name in conds
            }

    @staticmethod
    def _format_condition_states(
        evt: EventData, condition_states: dict[str, bool] | None = None
    ) -> str:
        conds = evt.get("conds", {})
        if not conds:
            return ""

        states = condition_states or {}
        parts = [
            f"{cond_name}={bool(states.get(cond_name, False))}"
            for cond_name in conds
        ]
        return f" conds[{', '.join(parts)}]"

    def _log_key_execution(
        self,
        mode: str,
        evt: EventData,
        target_duration: float,
        state_snapshot: dict[str, bool] | None = None,
    ) -> None:
        condition_states = self._snapshot_condition_states(evt, state_snapshot)
        cond_suffix = self._format_condition_states(evt, condition_states)
        logger.debug(
            f"{mode} Key Pressed: {evt['key']} Evt: '{evt['name']}' "
            f"(Duration: {target_duration:.3f}s){cond_suffix}"
        )

    async def _wait_until_async(
        self, end_time: float, check_interval: float = 0.02
    ) -> None:
        """절대 종료 시간까지 비동기 대기"""
        while time.time() < end_time and not self.term_event.is_set():
            remaining = end_time - time.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(check_interval, remaining))

    async def _press_key_async(
        self, evt: EventData, state_snapshot: dict[str, bool] | None = None
    ) -> None:
        """비동기 키 입력 실행 (메인 루프용)"""
        if self.term_event.is_set():
            return

        key = evt["key"]
        if not key:
            return
        code = self.key_codes.get(key)
        if code is None:
            return

        with self.key_lock:
            if key in self.pressed_keys:
                return
            self.pressed_keys.add(key)
            self.pressed_key_codes[key] = code

        down = False
        release_failed = False
        try:
            self.sim.press(code)
            down = True
            target_duration = self._calculate_press_duration(evt)
            await self._wait_until_async(time.time() + target_duration)
            self._log_key_execution("Async", evt, target_duration, state_snapshot)
        finally:
            if down:
                try:
                    self.sim.release(code)
                except Exception as exc:
                    release_failed = True
                    logger.warning(f"Key release failed for {key!r}: {exc}")
            with self.key_lock:
                if release_failed:
                    # Keep tracking so stop()/force-release can retry key-up.
                    self.pressed_keys.add(key)
                    self.pressed_key_codes[key] = code
                else:
                    self.pressed_keys.discard(key)
                    self.pressed_key_codes.pop(key, None)
