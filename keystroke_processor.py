import asyncio
import ctypes
import platform
import random
import re
import threading
import time
import numpy as np
import mss
from typing import List, Dict, Optional, Any
from loguru import logger

from keystroke_models import EventModel
from keystroke_utils import KeyUtils, ProcessUtils

# OS-specific imports
if platform.system() == "Windows":
    import win32gui, win32process
elif platform.system() == "Darwin":
    from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap


class KeySimulator:
    def __init__(self, os_type: str):
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
    def __init__(self, key_codes, loop_delay, press_time, mod_keys, os_type):
        self.key_codes, self.loop_delay, self.press_time = (
            key_codes,
            loop_delay,
            press_time,
        )
        self.mod_keys = {k: v for k, v in mod_keys.items() if v.get("enabled")}
        self.sim = KeySimulator(os_type)
        self.event = threading.Event()

    async def check_and_process(self) -> bool:
        active = False
        tasks = []
        for k, v in self.mod_keys.items():
            if KeyUtils.mod_key_pressed(k):
                active = True
                if not v.get("pass"):
                    tasks.append(self._sim_key(v["value"]))

        if tasks:
            await asyncio.gather(*tasks)
        self.event.set() if active else self.event.clear()
        return active

    async def _sim_key(self, key: str):
        if code := self.key_codes.get(key.upper()):
            self.sim.press(code)
            await asyncio.sleep(random.uniform(*self.press_time))
            self.sim.release(code)


class KeystrokeProcessor:
    PID_REGEX = re.compile(r"\((\d+)\)")

    def __init__(self, main_app, target_proc, events, mod_keys, term_event):
        self.main_app, self.term_event = main_app, term_event
        self.pid = (
            int(m.group(1)) if (m := self.PID_REGEX.search(target_proc)) else None
        )
        self.os_type = platform.system()

        s = main_app.settings
        self.delays = (s.delay_between_loop_min / 1000, s.delay_between_loop_max / 1000)
        self.default_press_times = (
            s.key_pressed_time_min / 1000,
            s.key_pressed_time_max / 1000,
        )

        self.key_codes = KeyUtils.get_key_list()
        self.sim = KeySimulator(self.os_type)
        self.mod_handler = ModificationKeyHandler(
            self.key_codes,
            self.delays,
            self.default_press_times,
            mod_keys,
            self.os_type,
        )

        # 상태 공유 및 락
        self.pressed_keys = set()
        self.lock = threading.Lock()
        self.current_states = {}  # 조건 체크용 전역 상태 (메인 루프 기준)

        # 이벤트 데이터 초기화 (메인 / 독립 분리)
        self.event_data_list, self.independent_events, self.mega_rect = self._init_event_data(events)

        self.loop = asyncio.new_event_loop()
        self.main_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.indep_threads = []

    def start(self):
        logger.info("Processor starting...")
        # 1. 메인 루프 시작
        self.main_thread.start()

        # 2. 독립 이벤트 스레드 시작
        for evt in self.independent_events:
            t = threading.Thread(target=self._run_independent_loop, args=(evt,), daemon=True)
            t.start()
            self.indep_threads.append(t)

    def stop(self):
        logger.info("Processor stopping...")
        self.term_event.set()
        if self.main_thread.is_alive():
            self.main_thread.join()
        for t in self.indep_threads:
            if t.is_alive():
                t.join(0.5)

    def _init_event_data(self, raw_events):
        events_data = []      # Main loop events (Group logic applies)
        independent_data = [] # Independent threads (No grouping)
        all_coords = []

        for e in raw_events:
            if not e.use_event:
                continue

            center_x = e.latest_position[0] + e.clicked_position[0]
            center_y = e.latest_position[1] + e.clicked_position[1]
            is_independent = getattr(e, "independent_thread", False)

            evt_data = {
                "name": e.event_name or "Unknown",
                "mode": getattr(e, "match_mode", "pixel"),
                "key": e.key_to_enter.upper() if e.key_to_enter else None,
                "center_x": center_x,
                "center_y": center_y,
                "dur": getattr(e, "press_duration_ms", None),
                "rand": getattr(e, "randomization_ms", None),
                "exec": getattr(e, "execute_action", True),
                "group": getattr(e, "group_id", None),
                "priority": getattr(e, "priority", 0),
                "conds": getattr(e, "conditions", {}),
                "independent": is_independent
            }

            # 독립 이벤트는 그룹 로직에서 제외 (논리적 충돌 방지)
            if is_independent:
                evt_data["group"] = None

            # 매칭 데이터 준비 (Reference Image/Pixel)
            if evt_data["mode"] == "region":
                r_size = getattr(e, "region_size", (20, 20))
                w, h = r_size if r_size else (20, 20)
                evt_data["region_w"], evt_data["region_h"] = w, h

                if e.held_screenshot:
                    full_img = np.array(e.held_screenshot.convert("RGB"))
                    cx, cy = e.clicked_position
                    x1 = max(0, cx - w // 2)
                    y1 = max(0, cy - h // 2)
                    x2 = min(full_img.shape[1], x1 + w)
                    y2 = min(full_img.shape[0], y1 + h)

                    ref_img_rgb = full_img[y1:y2, x1:x2]
                    evt_data["ref_img"] = ref_img_rgb[:, :, ::-1].copy() # BGR

                    # 5-Point Check Optimization
                    rh, rw = evt_data["ref_img"].shape[:2]
                    if rh > 0 and rw > 0:
                        pts = [(0, 0), (rw - 1, 0), (0, rh - 1), (rw - 1, rh - 1), (rw // 2, rh // 2)]
                        evt_data["check_points"] = []
                        for px, py in pts:
                            if 0 <= px < rw and 0 <= py < rh:
                                evt_data["check_points"].append({
                                    "pos": (px, py),
                                    "color": evt_data["ref_img"][py, px]
                                })
            else:
                ref_rgb = e.ref_pixel_value[:3]
                evt_data["ref_bgr"] = np.array(ref_rgb[::-1], dtype=np.uint8)

            if is_independent:
                independent_data.append(evt_data)
            else:
                events_data.append(evt_data)
                # 메인 루프용 MegaRect 좌표 수집
                if evt_data["mode"] == "region":
                    w, h = evt_data["region_w"], evt_data["region_h"]
                    all_coords.append((center_x - w // 2, center_y - h // 2))
                    all_coords.append((center_x + w // 2, center_y + h // 2))
                else:
                    all_coords.append((center_x, center_y))

        # MegaRect Calculation (Only for main events)
        mega_rect = None
        if events_data and all_coords:
            coords = np.array(all_coords)
            x_min, y_min = coords.min(axis=0)
            x_max, y_max = coords.max(axis=0)
            mega_rect = {
                "left": int(x_min), "top": int(y_min),
                "width": int(x_max - x_min + 1), "height": int(y_max - y_min + 1),
            }
            # Calculate relative coordinates
            for evt in events_data:
                evt["rel_x"] = evt["center_x"] - mega_rect["left"]
                evt["rel_y"] = evt["center_y"] - mega_rect["top"]

        logger.info(f"Initialized: {len(events_data)} Main, {len(independent_data)} Independent Events.")
        return events_data, independent_data, mega_rect

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._process_main())
        finally:
            self.loop.close()

    async def _process_main(self):
        if not self.event_data_list:
            return

        logger.debug("Main loop started.")
        with mss.mss() as sct:
            while not self.term_event.is_set():
                if not ProcessUtils.is_process_active(self.pid):
                    await asyncio.sleep(0.33)
                    continue

                if await self.mod_handler.check_and_process():
                    await asyncio.sleep(random.uniform(*self.delays))
                    continue

                if self.mega_rect:
                    img = np.array(sct.grab(self.mega_rect))
                    await self._evaluate_and_execute_main(img)

                await asyncio.sleep(random.uniform(*self.delays))

    def _run_independent_loop(self, evt):
        """독립 이벤트 전용 루프"""
        logger.info(f"Independent thread started for '{evt['name']}'")
        local_delays = (0.02, 0.05) # 독립 루프용 빠른 주기

        # 캡처 영역 계산 (1회)
        cx, cy = evt["center_x"], evt["center_y"]
        if evt["mode"] == "region":
            w, h = evt["region_w"], evt["region_h"]
            capture_rect = {"top": cy - h//2, "left": cx - w//2, "width": w, "height": h}
        else:
            capture_rect = {"top": cy, "left": cx, "width": 1, "height": 1}

        with mss.mss() as sct:
            while not self.term_event.is_set():
                if not ProcessUtils.is_process_active(self.pid):
                    time.sleep(0.5)
                    continue

                try:
                    # 1. Capture
                    img = np.array(sct.grab(capture_rect))

                    # 2. Check Match (독립 루프는 상대 좌표가 0,0 기준이거나 중앙 기준)
                    # Region 모드일 경우 이미지가 딱 맞게 잘림 -> rel_x, rel_y는 이미지 중심 or 0
                    is_active = self._check_match(img, evt, is_independent=True)

                    # 3. Execute
                    # 독립 이벤트는 그룹 로직을 무시하고, 조건(Conditions)만 체크하거나 즉시 실행
                    # 조건 체크가 필요하다면 self.current_states(메인 루프 상태)를 참조해야 함 (Lock 권장)
                    # 여기서는 단순화를 위해 조건 없이 즉시 실행으로 처리하거나, 필요시 Lock 사용하여 구현
                    
                    if is_active and evt["exec"]:
                        self._sync_press_key(evt)

                except Exception as e:
                    logger.error(f"Error in independent thread {evt['name']}: {e}")

                time.sleep(random.uniform(*local_delays))

    def _check_match(self, img, evt, is_independent=False) -> bool:
        """이미지 매칭 로직 (메인/독립 공용)"""
        try:
            if evt["mode"] == "region":
                # ROI 추출 좌표 계산
                if is_independent:
                    # 독립 루프는 이미지가 ROI 크기만큼 캡처됨 -> 전체 비교
                    roi_bgr = img[:, :, :3]
                else:
                    # 메인 루프는 MegaRect 기준 상대 좌표 사용
                    w, h = evt["region_w"], evt["region_h"]
                    half_w, half_h = w // 2, h // 2
                    x = evt["rel_x"] - half_w
                    y = evt["rel_y"] - half_h
                    
                    # 경계 처리
                    img_h, img_w = img.shape[:2]
                    x1, y1 = max(0, x), max(0, y)
                    x2, y2 = min(img_w, x + w), min(img_h, y + h)

                    # 크기가 다르면 매칭 불가
                    ref_h, ref_w = evt["ref_img"].shape[:2]
                    if (x2 - x1) != ref_w or (y2 - y1) != ref_h:
                        return False
                    
                    roi_bgr = img[y1:y2, x1:x2, :3]

                # 1. 5점 선행 검사
                for pt in evt["check_points"]:
                    px, py = pt["pos"]
                    if not np.array_equal(roi_bgr[py, px], pt["color"]):
                        return False
                
                # 2. 정밀 검사 (필요시 추가, 현재는 5점 검사 통과 시 True 간주하거나 전체 비교)
                # 성능을 위해 전체 비교는 생략하거나 옵션화 가능. 여기선 5점 통과 시 True.
                return True

            else:
                # Pixel Match
                if is_independent:
                    pixel = img[0, 0, :3]
                else:
                    pixel = img[evt["rel_y"], evt["rel_x"]][:3]
                
                return np.array_equal(pixel, evt["ref_bgr"])

        except Exception:
            return False

    async def _evaluate_and_execute_main(self, img):
        active_candidates = []

        # --- Step 1: Evaluation ---
        for evt in self.event_data_list:
            is_active = self._check_match(img, evt, is_independent=False)
            
            # 전역 상태 업데이트 (독립 스레드가 참조할 수도 있음 - 필요시 Lock)
            self.current_states[evt["name"]] = is_active
            
            if is_active:
                active_candidates.append(evt)

        # --- Step 2: Logical Filtering (Conditions & Groups) ---
        final_events = []
        
        # Condition Check
        filtered_by_cond = []
        for evt in active_candidates:
            passed = True
            if evt["conds"]:
                for cond_name, expected in evt["conds"].items():
                    actual = self.current_states.get(cond_name, False)
                    if actual != expected:
                        passed = False
                        break
            if passed:
                filtered_by_cond.append(evt)

        # Grouping
        groups = {}
        no_group = []
        for evt in filtered_by_cond:
            if evt["group"]:
                groups.setdefault(evt["group"], []).append(evt)
            else:
                no_group.append(evt)

        for grp_evts in groups.values():
            grp_evts.sort(key=lambda e: e["priority"])
            final_events.append(grp_evts[0]) # Priority 1등만

        final_events.extend(no_group)
        exec_list = [e for e in final_events if e["exec"]]

        # --- Step 3: Execution ---
        if exec_list:
            await asyncio.gather(*(self._press_key_async(e) for e in exec_list))

    async def _press_key_async(self, evt):
        """메인 루프용 비동기 키 입력"""
        key = evt["key"]
        if not key or not (code := self.key_codes.get(key)):
            return

        with self.lock:
            if key in self.pressed_keys:
                return
            self.pressed_keys.add(key)

        try:
            self.sim.press(code)
            
            if evt["dur"] is not None:
                base = evt["dur"] / 1000
                rand = (evt["rand"] or 0) / 1000
                delay = base + random.uniform(-rand, rand)
            else:
                delay = random.uniform(*self.default_press_times)

            await asyncio.sleep(max(0.01, delay))
            self.sim.release(code)
            logger.info(f"Key '{key}' pressed (Main) [{evt['name']}]")
            await asyncio.sleep(random.uniform(0.025, 0.050))
        finally:
            with self.lock:
                self.pressed_keys.discard(key)

    def _sync_press_key(self, evt):
        """독립 루프용 동기 키 입력"""
        key = evt["key"]
        if not key or not (code := self.key_codes.get(key)):
            return

        # Lock을 사용하여 메인 루프와 키 중복 입력 방지
        with self.lock:
            if key in self.pressed_keys:
                return
            self.pressed_keys.add(key)
        
        try:
            self.sim.press(code)
            
            # 동기적 sleep
            if evt["dur"] is not None:
                base = evt["dur"] / 1000
                rand = (evt["rand"] or 0) / 1000
                delay = base + random.uniform(-rand, rand)
            else:
                delay = random.uniform(*self.default_press_times)
            
            time.sleep(max(0.01, delay))
            self.sim.release(code)
            logger.info(f"Key '{key}' pressed (Indep) [{evt['name']}]")
            time.sleep(random.uniform(0.02, 0.04))
        finally:
            with self.lock:
                self.pressed_keys.discard(key)