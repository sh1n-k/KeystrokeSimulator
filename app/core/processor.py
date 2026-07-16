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
from typing import NotRequired, Protocol, TypedDict, cast

import mss
from loguru import logger
from mss.screenshot import ScreenShot
from PIL import Image

from app.core.models import EventModel, ModificationKeys, UserSettings
from app.utils.system import KeyUtils, ProcessUtils

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


def _windows_key_event(code: int, flags: int) -> None:
    windll = ctypes.__dict__["windll"]
    keybd_event = cast(Callable[[int, int, int, int], None], windll.user32.keybd_event)
    keybd_event(code, 0, flags, 0)


def _windows_key_press(code: int) -> None:
    _windows_key_event(code, 0)


def _windows_key_release(code: int) -> None:
    _windows_key_event(code, 2)


def _darwin_key_event(code: int, pressed: bool) -> None:
    quartz = importlib.import_module("Quartz")
    symbols = quartz.__dict__
    create_event = cast(Callable[[object, int, bool], object], symbols["CGEventCreateKeyboardEvent"])
    post_event = cast(Callable[[object, object], None], symbols["CGEventPost"])
    event_tap = symbols["kCGHIDEventTap"]
    post_event(event_tap, create_event(None, code, pressed))


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
    ) -> None:
        self.key_codes = key_codes
        # press_time: (min_sec, max_sec) 튜플
        self.press_time = default_press_times
        # 설정에서 enabled된 키만 필터링
        self.mod_keys = {k: v for k, v in mod_keys.items() if v.get("enabled")}
        self.sim = KeySimulator(os_type)
        self.event = threading.Event()

    async def check_and_process(self) -> bool:
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
        if norm_key and (code := self.key_codes.get(norm_key)):
            self.sim.press(code)
            await asyncio.sleep(random.uniform(*self.press_time))
            self.sim.release(code)


class KeystrokeProcessor:
    PID_REGEX = re.compile(r"\((\d+)\)")

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
        self.mod_handler = ModificationKeyHandler(
            self.key_codes, self.default_press_times, mod_keys, self.os_type
        )

        # Thread Safety & State
        self.key_lock = threading.Lock()
        self.state_lock = threading.Lock()

        self.pressed_keys: set[str] = set()
        self.current_states: dict[str, bool] = {}
        self.runtime_toggle_active = False
        self._roi_warn_logged: set[str] = set()

        self.event_data_list: list[EventData] = self._init_event_data(events)
        self.main_capture_groups: list[CaptureGroup] = self._build_capture_groups(
            self.event_data_list
        )

        self.loop = asyncio.new_event_loop()
        self.main_thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self) -> None:
        logger.info(f"Processor starting... PID: {self.pid}")
        self.main_thread.start()

    def stop(self) -> None:
        logger.info("Processor stopping...")
        self.term_event.set()

        if self.main_thread.is_alive():
            self.main_thread.join(timeout=1.0)

    def _init_event_data(self, raw_events: list[EventModel]) -> list[EventData]:
        events_data: list[EventData] = []

        for e in raw_events:
            if not e.use_event:
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
            key = (
                _normalize_key_name(self.key_codes, e.key_to_enter)
                if e.key_to_enter
                else None
            )

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
        if not self.event_data_list or not self.main_capture_groups:
            return

        last_proc_check_time = 0
        is_proc_active_cached = True
        proc_check_interval = 0.3

        with mss.mss() as sct:
            while not self.term_event.is_set():
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
                    await asyncio.sleep(0.1)
                    continue

                try:
                    cycle_started = time.perf_counter()
                    local_match_states: dict[str, bool] = {}
                    for group in self.main_capture_groups:
                        img = ImageFrame.from_screenshot(sct.grab(group["rect"]))
                        local_match_states.update(
                            self._evaluate_capture_group(img, group["events"])
                        )
                    await self._apply_local_match_states(local_match_states)
                    _log_perf("processor_main_cycle", cycle_started)
                except Exception as e:
                    logger.error(f"Capture failed: {e}")

                await asyncio.sleep(random.uniform(*self.delays))

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

        for evt in sorted_events:
            evt_rect = self._build_capture_rect(evt)
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
        local_states = self._resolve_effective_states(local_match_states)

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
        logger.info(
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
        if not key or not (code := self.key_codes.get(key)):
            return

        with self.key_lock:
            if key in self.pressed_keys:
                return
            self.pressed_keys.add(key)

        try:
            self.sim.press(code)
            target_duration = self._calculate_press_duration(evt)
            await self._wait_until_async(time.time() + target_duration)
            self.sim.release(code)
            self._log_key_execution("Async", evt, target_duration, state_snapshot)
        finally:
            with self.key_lock:
                self.pressed_keys.discard(key)
