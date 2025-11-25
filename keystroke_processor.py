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

# OS-specific imports (기존과 동일)
if platform.system() == "Windows":
    import win32gui, win32process
elif platform.system() == "Darwin":
    from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap


class KeySimulator:
    # (기존과 동일)
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
        if code := self.key_codes.get(key_name.upper()):
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

    # ... (start, stop, _init_event_data, _run_loop, _process_main, _evaluate_and_execute_main 메서드는 기존 유지) ...
    # ... (_check_match 메서드에서 주석 해제한 부분은 이전 답변 적용 유지) ...

    # 생략된 부분들은 이전 코드와 동일하게 유지한다고 가정하고,
    # 문제가 된 press_key 메서드들만 수정합니다.

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
        # ... (이전 코드와 동일하되, 주석 해제된 Region 매칭 로직 적용 필요) ...
        # (편의상 중략, 이전 답변의 수정 사항이 적용되어 있어야 함)
        events_data = []
        independent_data = []
        all_coords = []
        seen_signatures = set()

        for e in raw_events:
            if not e.use_event or not e.key_to_enter:
                continue

            if getattr(e, "match_mode", "pixel") == "pixel":
                if not e.ref_pixel_value or len(e.ref_pixel_value) < 3:
                    continue

            center_x = e.latest_position[0] + e.clicked_position[0]
            center_y = e.latest_position[1] + e.clicked_position[1]
            is_indep = getattr(e, "independent_thread", False)
            mode = getattr(e, "match_mode", "pixel")
            key = e.key_to_enter.upper()

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

                # [수정] 랜덤 딜레이 적용 시 루프 간 지연
                await asyncio.sleep(random.uniform(*self.delays))

    async def _evaluate_and_execute_main(self, img: np.ndarray):
        active_candidates = []
        local_states = {}

        for evt in self.event_data_list:
            is_active = self._check_match(img, evt, is_independent=False)
            local_states[evt["name"]] = is_active
            if is_active:
                active_candidates.append(evt)

        with self.state_lock:
            self.current_states.update(local_states)

        final_events = []
        filtered_by_cond = []

        for evt in active_candidates:
            passed = True
            if evt["conds"]:
                for cond_name, expected in evt["conds"].items():
                    actual = local_states.get(
                        cond_name, self.current_states.get(cond_name, False)
                    )
                    if actual != expected:
                        passed = False
                        break
            if passed:
                filtered_by_cond.append(evt)

        groups = {}
        no_group = []
        for evt in filtered_by_cond:
            if evt["group"]:
                groups.setdefault(evt["group"], []).append(evt)
            else:
                no_group.append(evt)

        for grp_evts in groups.values():
            grp_evts.sort(key=lambda e: e["priority"])
            final_events.append(grp_evts[0])

        final_events.extend(no_group)

        tasks = []
        for evt in final_events:
            if self.term_event.is_set():
                break
            if evt["exec"]:
                tasks.append(self._press_key_async(evt))

        if tasks:
            await asyncio.gather(*tasks)

    def _run_independent_loop(self, evt: Dict):
        cx, cy = evt["center_x"], evt["center_y"]
        if evt["mode"] == "region":
            w, h = evt["region_w"], evt["region_h"]
            capture_rect = {
                "top": cy - h // 2,
                "left": cx - w // 2,
                "width": w,
                "height": h,
            }
        else:
            capture_rect = {"top": cy, "left": cx, "width": 1, "height": 1}

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

                    should_execute = True
                    if evt["conds"]:
                        with self.state_lock:
                            for cond_name, expected in evt["conds"].items():
                                if (
                                    self.current_states.get(cond_name, False)
                                    != expected
                                ):
                                    should_execute = False
                                    break

                    if is_active and should_execute and evt["exec"]:
                        self._sync_press_key(evt)

                except Exception as e:
                    logger.error(f"Error in indep thread {evt['name']}: {e}")

                # [수정] 사용자 설정 딜레이 사용
                time.sleep(random.uniform(*self.delays))

    def _check_match(self, img: np.ndarray, evt: Dict, is_independent: bool) -> bool:
        try:
            if evt["mode"] == "region":
                if is_independent:
                    roi = img[:, :, :3]
                else:
                    w, h = evt["region_w"], evt["region_h"]
                    x, y = evt["rel_x"] - w // 2, evt["rel_y"] - h // 2
                    if x < 0 or y < 0 or x + w > img.shape[1] or y + h > img.shape[0]:
                        return False
                    roi = img[y : y + h, x : x + w, :3]

                for pt in evt.get("check_points", []):
                    px, py = pt["pos"]
                    if py >= roi.shape[0] or px >= roi.shape[1]:
                        continue
                    # 색상 비교 일시 정지
                    # if not np.array_equal(roi[py, px], pt["color"]):
                    #     return False
                return True
            else:
                if is_independent:
                    pixel = img[0, 0, :3]
                else:
                    py, px = evt["rel_y"], evt["rel_x"]
                    if py >= img.shape[0] or px >= img.shape[1]:
                        return False
                    pixel = img[py, px][:3]
                return np.array_equal(pixel, evt["ref_bgr"])
        except Exception:
            return False

    async def _press_key_async(self, evt: Dict):
        """
        [수정] 절대 시간(Deadline) 기반 대기 방식으로 변경
        시스템 렉이나 sleep 오차와 관계없이 정해진 시간만 누르도록 보장
        """
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

            # 1. 목표 지속 시간 계산 (초 단위)
            if evt["dur"]:
                target_duration = evt["dur"] / 1000.0
            else:
                target_duration = random.uniform(*self.default_press_times)

            if evt["rand"]:
                target_duration += random.uniform(-evt["rand"], evt["rand"]) / 1000.0

            # 최소 안전 시간 (0.05초)
            target_duration = max(0.05, target_duration)

            # 2. 절대 종료 시간 계산
            end_time = time.time() + target_duration

            # 3. 종료 시간까지 대기 (Deadline Check)
            while time.time() < end_time and not self.term_event.is_set():
                remaining = end_time - time.time()
                if remaining <= 0:
                    break
                # 짧게 자서 반응성 확보 (최대 0.02초)
                await asyncio.sleep(min(0.02, remaining))

            self.sim.release(code)
            logger.debug(f"Async Key Pressed: {key} Evt: '{evt['name'][:5]:5}' (Duration: {target_duration:.3f}s)")

        finally:
            with self.key_lock:
                self.pressed_keys.discard(key)

    def _sync_press_key(self, evt: Dict):
        """
        [수정] 독립 스레드용 절대 시간 기반 대기
        """
        key = evt["key"]
        if not key or not (code := self.key_codes.get(key)):
            return

        with self.key_lock:
            if key in self.pressed_keys:
                return
            self.pressed_keys.add(key)

        try:
            self.sim.press(code)

            # 1. 목표 지속 시간 계산 (초 단위)
            if evt["dur"]:
                target_duration = evt["dur"] / 1000.0
            else:
                target_duration = random.uniform(*self.default_press_times)

            if evt["rand"]:
                target_duration += random.uniform(-evt["rand"], evt["rand"]) / 1000.0

            target_duration = max(0.05, target_duration)

            # 2. 절대 종료 시간 계산
            end_time = time.time() + target_duration

            # 3. 종료 시간까지 대기
            while time.time() < end_time and not self.term_event.is_set():
                remaining = end_time - time.time()
                if remaining <= 0:
                    break
                time.sleep(min(0.02, remaining))

            self.sim.release(code)
            logger.debug(f"Sync Key Pressed: {key} Evt: '{evt['name'][:5]:5}' (Duration: {target_duration:.3f}s)")
        finally:
            with self.key_lock:
                self.pressed_keys.discard(key)
