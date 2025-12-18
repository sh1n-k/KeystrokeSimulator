import asyncio
import ctypes
import platform
import random
import re
import threading
import time
from typing import List, Dict, Optional, Any, Set, Tuple

import numpy as np
import mss
from loguru import logger

from keystroke_models import EventModel
from keystroke_utils import KeyUtils, ProcessUtils

# OS-specific imports
if platform.system() == "Windows":
    import win32gui, win32process
elif platform.system() == "Darwin":
    from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap


def _normalize_key_name(
    key_codes: Dict[str, int], key_name: Optional[str]
) -> Optional[str]:
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


class KeySimulator:
    def __init__(self, os_type: str):
        self.os_type = os_type
        if os_type == "Windows":
            self.press = lambda c: ctypes.windll.user32.keybd_event(c, 0, 0, 0)
            self.release = lambda c: ctypes.windll.user32.keybd_event(c, 0, 2, 0)
        elif os_type == "Darwin":
            self.press = lambda c: CGEventPost(
                kCGHIDEventTap, CGEventCreateKeyboardEvent(None, c, True)
            )
            self.release = lambda c: CGEventPost(
                kCGHIDEventTap, CGEventCreateKeyboardEvent(None, c, False)
            )
        else:
            self.press = self.release = lambda c: None


class ModificationKeyHandler:
    def __init__(self, key_codes, default_press_times, mod_keys, os_type):
        self.key_codes = key_codes
        # press_time: (min_sec, max_sec) 튜플
        self.press_time = default_press_times
        # 설정에서 enabled된 키만 필터링
        self.mod_keys = {k: v for k, v in mod_keys.items() if v.get("enabled")}
        self.sim = KeySimulator(os_type)
        self.event = threading.Event()

    async def check_and_process(self) -> bool:
        active = False
        tasks = []

        # 설정된 ModKey들을 순회하며 물리적 눌림 확인
        for k, v in self.mod_keys.items():
            if KeyUtils.mod_key_pressed(k):
                active = True
                # 'Pass' 설정이 아닐 경우(다른 키로 매핑된 경우) 키 입력 시뮬레이션
                if not v.get("pass") and (val := v.get("value")):
                    tasks.append(self._sim_key(val))

        # 매핑된 키 입력 병렬 실행
        if tasks:
            await asyncio.gather(*tasks)

        if active:
            self.event.set()
        else:
            self.event.clear()

        return active

    async def _sim_key(self, key_name: str):
        norm_key = _normalize_key_name(self.key_codes, key_name)
        if norm_key and (code := self.key_codes.get(norm_key)):
            self.sim.press(code)
            await asyncio.sleep(random.uniform(*self.press_time))
            self.sim.release(code)


class KeystrokeProcessor:
    PID_REGEX = re.compile(r"\((\d+)\)")

    def __init__(
        self,
        main_app,
        target_proc: str,
        events: List[EventModel],
        mod_keys: Dict,
        term_event: threading.Event,
    ):
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

        self.pressed_keys: Set[str] = set()
        self.current_states: Dict[str, bool] = {}

        self.event_data_list, self.independent_events, self.mega_rect = (
            self._init_event_data(events)
        )

        self.loop = asyncio.new_event_loop()
        self.main_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.indep_threads: List[threading.Thread] = []

    def start(self):
        logger.info(f"Processor starting... PID: {self.pid}")
        self.main_thread.start()

        for evt in self.independent_events:
            t = threading.Thread(
                target=self._run_independent_loop, args=(evt,), daemon=True
            )
            t.start()
            self.indep_threads.append(t)

    def stop(self):
        logger.info("Processor stopping...")
        self.term_event.set()

        if self.main_thread.is_alive():
            self.main_thread.join(timeout=1.0)
        for t in self.indep_threads:
            if t.is_alive():
                t.join(timeout=0.5)

    def _init_event_data(
        self, raw_events: List[EventModel]
    ) -> Tuple[List[Dict], List[Dict], Optional[Dict]]:
        events_data = []
        independent_data = []
        all_coords = []
        seen_signatures = set()

        for e in raw_events:
            if not e.use_event:
                continue

            if getattr(e, "match_mode", "pixel") == "pixel":
                if not e.ref_pixel_value or len(e.ref_pixel_value) < 3:
                    continue

            center_x = e.latest_position[0] + e.clicked_position[0]
            center_y = e.latest_position[1] + e.clicked_position[1]
            is_indep = getattr(e, "independent_thread", False)
            mode = getattr(e, "match_mode", "pixel")
            key = (
                _normalize_key_name(self.key_codes, e.key_to_enter)
                if e.key_to_enter
                else None
            )

            ref_sig = None
            if mode == "pixel":
                ref_sig = tuple(e.ref_pixel_value[:3])
            else:
                if e.held_screenshot:
                    ref_sig = (
                        e.held_screenshot.size,
                        e.held_screenshot.getpixel((0, 0)),
                    )

            signature = (mode, center_x, center_y, key, is_indep, ref_sig)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            evt_data = {
                "name": e.event_name or "Unknown",
                "mode": mode,
                "invert": getattr(e, "invert_match", False),
                "key": key,
                "center_x": center_x,
                "center_y": center_y,
                "dur": getattr(e, "press_duration_ms", None),
                "rand": getattr(e, "randomization_ms", None),
                "exec": getattr(e, "execute_action", True),
                "group": getattr(e, "group_id", None),
                "priority": getattr(e, "priority", 0),
                "conds": getattr(e, "conditions", {}),
                "independent": is_indep,
            }

            if evt_data["mode"] == "region":
                r_size = getattr(e, "region_size", (20, 20))
                w, h = r_size if r_size else (20, 20)
                evt_data["region_w"], evt_data["region_h"] = w, h

                if e.held_screenshot:
                    full_img = np.array(e.held_screenshot.convert("RGB"))
                    cx, cy = e.clicked_position
                    y1, y2 = max(0, cy - h // 2), min(
                        full_img.shape[0], cy + h // 2 + (h % 2)
                    )
                    x1, x2 = max(0, cx - w // 2), min(
                        full_img.shape[1], cx + w // 2 + (w % 2)
                    )
                    evt_data["ref_img"] = full_img[y1:y2, x1:x2][:, :, ::-1].copy()

                    rh, rw = evt_data["ref_img"].shape[:2]
                    if rh > 0 and rw > 0:
                        pts = [
                            (0, 0),
                            (rw - 1, 0),
                            (0, rh - 1),
                            (rw - 1, rh - 1),
                            (rw // 2, rh // 2),
                        ]
                        evt_data["check_points"] = [
                            {"pos": (px, py), "color": evt_data["ref_img"][py, px]}
                            for px, py in pts
                            if 0 <= px < rw and 0 <= py < rh
                        ]
            else:
                ref_rgb = e.ref_pixel_value[:3]
                evt_data["ref_bgr"] = np.array(ref_rgb[::-1], dtype=np.uint8)

            if is_indep:
                independent_data.append(evt_data)
            else:
                events_data.append(evt_data)
                if evt_data["mode"] == "region":
                    w, h = evt_data["region_w"], evt_data["region_h"]
                    all_coords.extend(
                        [
                            (center_x - w // 2, center_y - h // 2),
                            (center_x + w // 2, center_y + h // 2),
                        ]
                    )
                else:
                    all_coords.append((center_x, center_y))

        mega_rect = None
        if events_data and all_coords:
            coords = np.array(all_coords)
            x_min, y_min = coords.min(axis=0)
            x_max, y_max = coords.max(axis=0)
            mega_rect = {
                "left": int(x_min),
                "top": int(y_min),
                "width": int(x_max - x_min + 1),
                "height": int(y_max - y_min + 1),
            }
            for evt in events_data:
                evt["rel_x"] = evt["center_x"] - mega_rect["left"]
                evt["rel_y"] = evt["center_y"] - mega_rect["top"]

        return events_data, independent_data, mega_rect

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._process_main())
        except Exception as e:
            logger.error(f"Main loop crashed: {e}")
        finally:
            self.loop.close()

    async def _process_main(self):
        if not self.event_data_list:
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

                if self.mega_rect:
                    try:
                        img = np.array(sct.grab(self.mega_rect))
                        await self._evaluate_and_execute_main(img)
                    except Exception as e:
                        logger.error(f"Capture failed: {e}")

                await asyncio.sleep(random.uniform(*self.delays))

    def _filter_by_conditions(
        self, candidates: List[Dict], local_states: Dict
    ) -> List[Dict]:
        """조건 필터링"""
        filtered = []
        for evt in candidates:
            if not evt["conds"]:
                filtered.append(evt)
                continue

            if all(
                local_states.get(cond_name, self.current_states.get(cond_name, False))
                == expected
                for cond_name, expected in evt["conds"].items()
            ):
                filtered.append(evt)

        return filtered

    def _select_by_group_priority(self, events: List[Dict]) -> List[Dict]:
        """그룹별 우선순위로 이벤트 선택"""
        groups = {}
        no_group = []

        for evt in events:
            if evt["group"]:
                groups.setdefault(evt["group"], []).append(evt)
            else:
                no_group.append(evt)

        # 각 그룹에서 최고 우선순위 이벤트만 선택
        final_events = [
            min(grp_evts, key=lambda e: e["priority"]) for grp_evts in groups.values()
        ]
        final_events.extend(no_group)

        return final_events

    async def _evaluate_and_execute_main(self, img: np.ndarray):
        # 1. 활성 이벤트 찾기 및 상태 업데이트
        local_states = {}
        active_candidates = []

        for evt in self.event_data_list:
            is_active = self._check_match(img, evt, is_independent=False)
            local_states[evt["name"]] = is_active
            if is_active:
                active_candidates.append(evt)

        with self.state_lock:
            self.current_states.update(local_states)

        # 2. 조건 필터링
        filtered_events = self._filter_by_conditions(active_candidates, local_states)

        # 3. 그룹 우선순위 적용
        final_events = self._select_by_group_priority(filtered_events)

        # 4. 키 입력 실행
        tasks = [
            self._press_key_async(evt)
            for evt in final_events
            if evt["exec"] and not self.term_event.is_set()
        ]

        if tasks:
            await asyncio.gather(*tasks)

    def _build_capture_rect(self, evt: Dict) -> Dict[str, int]:
        """이벤트에 대한 캡처 영역 생성"""
        cx, cy = evt["center_x"], evt["center_y"]
        if evt["mode"] == "region":
            w, h = evt["region_w"], evt["region_h"]
            return {"top": cy - h // 2, "left": cx - w // 2, "width": w, "height": h}
        return {"top": cy, "left": cx, "width": 1, "height": 1}

    def _check_conditions(self, evt: Dict) -> bool:
        """이벤트 조건 검사"""
        if not evt["conds"]:
            return True

        with self.state_lock:
            return all(
                self.current_states.get(cond_name, False) == expected
                for cond_name, expected in evt["conds"].items()
            )

    def _run_independent_loop(self, evt: Dict):
        capture_rect = self._build_capture_rect(evt)

        with mss.mss() as sct:
            while not self.term_event.is_set():
                if self.pid and not ProcessUtils.is_process_active(self.pid):
                    time.sleep(0.5)
                    continue

                try:
                    img = np.array(sct.grab(capture_rect))
                    is_active = self._check_match(img, evt, is_independent=True)

                    with self.state_lock:
                        self.current_states[evt["name"]] = is_active

                    if is_active and self._check_conditions(evt) and evt["exec"]:
                        self._sync_press_key(evt)

                except Exception as e:
                    logger.error(f"Error in indep thread {evt['name']}: {e}")

                time.sleep(random.uniform(*self.delays))

    def _extract_roi(
        self, img: np.ndarray, evt: Dict, is_independent: bool
    ) -> Optional[np.ndarray]:
        """이미지에서 관심 영역(ROI) 추출"""
        if is_independent:
            return img[:, :, :3]

        w, h = evt["region_w"], evt["region_h"]
        x, y = evt["rel_x"] - w // 2, evt["rel_y"] - h // 2

        # 경계 검사
        if x < 0 or y < 0 or x + w > img.shape[1] or y + h > img.shape[0]:
            return None

        return img[y : y + h, x : x + w, :3]

    def _check_match(self, img: np.ndarray, evt: Dict, is_independent: bool) -> bool:
        matched = False
        evaluated = False
        try:
            if evt["mode"] == "region":
                roi = self._extract_roi(img, evt, is_independent)
                if roi is None:
                    return False

                # 체크포인트 검증
                for pt in evt.get("check_points", []):
                    px, py = pt["pos"]
                    if py >= roi.shape[0] or px >= roi.shape[1]:
                        continue
                    # 색상 비교
                    if not np.array_equal(roi[py, px], pt["color"]):
                        matched = False
                        evaluated = True
                        break
                else:
                    matched = True
                    evaluated = True
            else:
                # 픽셀 모드
                if is_independent:
                    pixel = img[0, 0, :3]
                else:
                    py, px = evt["rel_y"], evt["rel_x"]
                    if py >= img.shape[0] or px >= img.shape[1]:
                        return False
                    pixel = img[py, px][:3]
                matched = np.array_equal(pixel, evt["ref_bgr"])
                evaluated = True
        except Exception:
            return False
        if evt.get("invert") and evaluated:
            return not matched
        return matched

    def _calculate_press_duration(self, evt: Dict) -> float:
        """목표 키 누름 지속 시간 계산 (초 단위)"""
        duration = (
            evt["dur"] / 1000.0
            if evt["dur"]
            else random.uniform(*self.default_press_times)
        )
        if evt["rand"]:
            duration += random.uniform(-evt["rand"], evt["rand"]) / 1000.0
        return max(0.05, duration)

    async def _wait_until_async(self, end_time: float, check_interval: float = 0.02):
        """절대 종료 시간까지 비동기 대기"""
        while time.time() < end_time and not self.term_event.is_set():
            remaining = end_time - time.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(check_interval, remaining))

    def _wait_until_sync(self, end_time: float, check_interval: float = 0.02):
        """절대 종료 시간까지 동기 대기"""
        while time.time() < end_time and not self.term_event.is_set():
            remaining = end_time - time.time()
            if remaining <= 0:
                break
            time.sleep(min(check_interval, remaining))

    async def _press_key_async(self, evt: Dict):
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
            logger.debug(
                f"Async Key Pressed: {key} Evt: '{evt['name'][:5]:5}' (Duration: {target_duration:.3f}s)"
            )
        finally:
            with self.key_lock:
                self.pressed_keys.discard(key)

    def _sync_press_key(self, evt: Dict):
        """동기 키 입력 실행 (독립 스레드용)"""
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
            self._wait_until_sync(time.time() + target_duration)
            self.sim.release(code)
            logger.debug(
                f"Sync Key Pressed: {key} Evt: '{evt['name'][:5]:5}' (Duration: {target_duration:.3f}s)"
            )
        finally:
            with self.key_lock:
                self.pressed_keys.discard(key)
