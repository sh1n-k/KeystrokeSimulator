import asyncio
import ctypes
import platform
import random
import re
import threading
import numpy as np
import mss
from typing import List, Dict, Optional
from loguru import logger
from sklearn.cluster import DBSCAN
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
        self.press_times = (
            s.key_pressed_time_min / 1000,
            s.key_pressed_time_max / 1000,
        )

        self.key_codes = KeyUtils.get_key_list()
        self.sim = KeySimulator(self.os_type)
        self.mod_handler = ModificationKeyHandler(
            self.key_codes, self.delays, self.press_times, mod_keys, self.os_type
        )

        self.clusters, self.mega_rect = self._init_event_data(events)
        self.pressed_keys, self.lock = set(), threading.Lock()

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self):
        logger.info("Processor starting...")
        self.thread.start()

    def stop(self):
        logger.info("Processor stopping...")
        self.term_event.set()
        if self.thread.is_alive():
            self.thread.join()

    def _init_event_data(self, raw_events):
        events = []
        seen = set()
        for e in raw_events:
            if not e.use_event:
                continue
            pos = (
                e.latest_position[0] + e.clicked_position[0],
                e.latest_position[1] + e.clicked_position[1],
            )
            ref = tuple(e.ref_pixel_value[:3])
            key = e.key_to_enter.upper()

            if (uid := (pos, ref, key)) not in seen:
                seen.add(uid)
                events.append(
                    {
                        "name": e.event_name,
                        "ref": ref,
                        "pos": pos,
                        "key": key,
                        "dur": e.press_duration_ms,
                        "rand": e.randomization_ms,
                    }
                )

        if not events:
            return {}, None

        # Clustering
        coords = np.array([e["pos"] for e in events])
        labels = (
            DBSCAN(eps=self.main_app.settings.cluster_epsilon_value, min_samples=1)
            .fit(coords)
            .labels_
        )

        clusters = {}
        for label, evt in zip(labels, events):
            clusters.setdefault(label, []).append(evt)

        # Mega Rect Calculation (Min/Max of all points)
        x_min, y_min = coords.min(axis=0)
        x_max, y_max = coords.max(axis=0)
        mega_rect = {
            "left": int(x_min),
            "top": int(y_min),
            "width": int(x_max - x_min + 1),
            "height": int(y_max - y_min + 1),
        }

        logger.info(f"Clusters: {len(clusters)}, MegaRect: {mega_rect}")
        return clusters, mega_rect

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.sct = mss.mss()
        try:
            self.loop.run_until_complete(self._process())
        finally:
            self.sct.close()
            self.loop.close()

    async def _process(self):
        if not self.clusters:
            return
        logger.debug("Loop started.")
        try:
            while not self.term_event.is_set():
                if not ProcessUtils.is_process_active(self.pid):
                    await asyncio.sleep(0.33)
                    continue

                if await self.mod_handler.check_and_process():
                    await asyncio.sleep(random.uniform(*self.delays))
                    continue

                if self.mega_rect:
                    img = np.array(self.sct.grab(self.mega_rect))
                    await asyncio.gather(
                        *(
                            self._check_cluster(img, evts)
                            for evts in self.clusters.values()
                        )
                    )

                await asyncio.sleep(random.uniform(*self.delays))
        except asyncio.CancelledError:
            pass
        logger.info("Loop finished.")

    async def _check_cluster(self, img, events):
        for e in events:
            rx, ry = (
                e["pos"][0] - self.mega_rect["left"],
                e["pos"][1] - self.mega_rect["top"],
            )
            try:
                # mss returns BGRA, convert to RGB by slicing [2::-1]
                if tuple(img[ry, rx][2::-1]) == e["ref"]:
                    await self._press_key(e)
            except IndexError:
                continue

    async def _press_key(self, evt):
        key = evt["key"]
        if not (code := self.key_codes.get(key)):
            return

        with self.lock:
            if key in self.pressed_keys:
                return
            self.pressed_keys.add(key)

        try:
            self.sim.press(code)
            if evt["dur"] is not None:
                delay = (evt["dur"] / 1000) + (
                    random.uniform(-(evt["rand"] or 0), (evt["rand"] or 0)) / 1000
                )
            else:
                delay = random.uniform(*self.press_times)

            await asyncio.sleep(max(0, delay))
            self.sim.release(code)
            logger.info(f"Key '{key}' pressed ({delay:.3f}s)")

            # Pause after key press to prevent spamming
            await asyncio.sleep(random.uniform(0.025, 0.050))
        finally:
            with self.lock:
                self.pressed_keys.discard(key)
