import asyncio
import ctypes
import platform
import random
import re
import threading
import time
import uuid
from typing import List, Dict, Tuple, Optional

import mss
import numpy as np
from loguru import logger
from sklearn.cluster import DBSCAN

from keystroke_models import EventModel
from keystroke_utils import KeyUtils

# OS-specific imports
if platform.system() == "Windows":
    import win32gui
    import win32process
elif platform.system() == "Darwin":
    import AppKit
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        kCGHIDEventTap,
    )


class KeySimulator:
    def __init__(self, os_type: str):
        os_map = {
            "Windows": "_win",
            "Darwin": "_darwin",
        }
        suffix = os_map.get(os_type, "_unsupported")  # 기본값 처리
        self.press_key = getattr(self, f"press_key{suffix}")
        self.release_key = getattr(self, f"release_key{suffix}")

    def press_key_win(self, code: int):
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)

    def release_key_win(self, code: int):
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)

    def press_key_darwin(self, code: int):
        event = CGEventCreateKeyboardEvent(None, code, True)
        CGEventPost(kCGHIDEventTap, event)

    def release_key_darwin(self, code: int):
        event = CGEventCreateKeyboardEvent(None, code, False)
        CGEventPost(kCGHIDEventTap, event)


class ModificationKeyHandler:
    def __init__(
        self,
        key_codes: Dict[str, int],
        loop_delay: Tuple[float, float],
        key_pressed_time: Tuple[float, float],
        modification_keys: Dict[str, Dict],
        os_type: str,
    ):
        self.key_codes = key_codes
        self.loop_delay = loop_delay
        self.key_pressed_time = key_pressed_time
        self.modification_keys = {
            key: value
            for key, value in modification_keys.items()
            if value.get("enabled")
        }
        self.key_simulator = KeySimulator(os_type)
        self.mod_key_pressed = threading.Event()

    async def check_modification_keys(self) -> bool:
        """
        Checks if any modification key is pressed.

        :return: True if any modification key is pressed, else False.
        """
        any_mod_key_pressed = False
        for key, value in self.modification_keys.items():
            if KeyUtils.mod_key_pressed(key):
                any_mod_key_pressed = True
                logger.debug(f"mod_key_pressed: {value.get('pass')} / {value}")
                if not value.get("pass"):
                    self.simulate_keystroke(value["value"])
                    logger.debug(
                        f"Key '{value['value']}' pressed with mod-key '{key.upper()}'"
                    )
                    await asyncio.sleep(random.uniform(*self.loop_delay))

        if any_mod_key_pressed:
            self.mod_key_pressed.set()
        else:
            self.mod_key_pressed.clear()

        return any_mod_key_pressed

    def simulate_keystroke(self, key: str):
        """
        Simulates a single keystroke.

        :param key: The key to simulate.
        """
        key_code = self.key_codes.get(key.upper())
        if key_code is None:
            logger.error(
                f"A modification key without a code was pressed: {key} / {key_code}"
            )
            return

        self.key_simulator.press_key(key_code)
        time.sleep(random.uniform(*self.key_pressed_time))
        self.key_simulator.release_key(key_code)


class KeystrokeProcessor:
    PROCESS_ID_PATTERN = re.compile(r"\((\d+)\)")

    def __init__(
        self,
        main_app,
        target_process: str,
        event_list: List[EventModel],
        modification_keys: Dict[str, Dict],
        terminate_event: threading.Event,
    ):
        """
        Initializes the KeystrokeProcessor.

        :param main_app: Reference to the main application.
        :param target_process: The target process string (e.g., "Notepad (1234)").
        :param event_list: List of EventModel instances.
        :param modification_keys: Dictionary of modification keys.
        :param terminate_event: threading.Event to signal termination.
        """
        self.main_app = main_app
        self.target_process = self.parse_process_id(target_process)
        self.event_list = self.prepare_events(event_list)
        self.modification_keys = modification_keys
        self.terminate_event = terminate_event
        self.os_type = platform.system()
        self.key_simulator = KeySimulator(self.os_type)

        self.key_codes = KeyUtils.get_key_list()

        self.loop_delay = (
            self.main_app.settings.delay_between_loop_min / 1000,
            self.main_app.settings.delay_between_loop_max / 1000,
        )
        self.key_pressed_time = (
            self.main_app.settings.key_pressed_time_min / 1000,
            self.main_app.settings.key_pressed_time_max / 1000,
        )

        self.mod_key_handler = ModificationKeyHandler(
            self.key_codes,
            self.loop_delay,
            self.key_pressed_time,
            modification_keys,
            self.os_type,
        )

        # OS-specific initialization
        if self.os_type == "Windows":
            self.is_process_active = self._is_process_active_windows
        elif self.os_type == "Darwin":
            self.is_process_active = self._is_process_active_darwin

        # Perform clustering and compute bounding rectangles
        self.clusters, self.bounding_rects = self._compute_clusters_and_bounding_rects()

        # Initialize asyncio loop in a separate thread
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._start_loop, daemon=True)
        self.thread.start()

        # Initialize set to track pressed keys and a lock for thread safety
        self.pressed_keys = set()
        self.pressed_keys_lock = threading.Lock()

        self.sct = mss.mss()

    @staticmethod
    def parse_process_id(target_process: str) -> Optional[int]:
        """
        Extracts the process ID from the target process string.

        :param target_process: The target process string.
        :return: Process ID as integer or None.
        """
        match = KeystrokeProcessor.PROCESS_ID_PATTERN.search(target_process)
        if match:
            return int(match.group(1))
        return None

    def prepare_events(self, event_list: List[EventModel]) -> List[Dict]:
        """
        Prepares events by computing absolute click positions and reference pixel values.

        :param event_list: List of EventModel instances.
        :return: List of event dictionaries.
        """
        prepared = []
        seen_events = set()
        for event in event_list:
            x = event.latest_position[0] + event.clicked_position[0]
            y = event.latest_position[1] + event.clicked_position[1]
            event_key = (
                (x, y),
                tuple(event.ref_pixel_value[:3]),
                event.key_to_enter.upper(),
            )
            if event_key not in seen_events:
                seen_events.add(event_key)
                prepared.append(
                    {
                        "ref_pixel_value": tuple(event.ref_pixel_value[:3]),
                        "click_position": (x, y),
                        "key": event.key_to_enter.upper(),
                    }
                )
            else:
                logger.debug(f"Duplicate event detected and skipped: {event_key}")
        return prepared

    def _compute_clusters_and_bounding_rects(
        self,
    ) -> Tuple[Dict[int, List[Dict]], Dict[int, Dict]]:
        """
        Performs clustering on the event list and computes bounding rectangles for each cluster.

        :return: A tuple containing:
                 - clusters: Dictionary mapping cluster labels to lists of event dictionaries.
                 - bounding_rects: Dictionary mapping cluster labels to their bounding rectangle dictionaries.
        """
        # Perform clustering using DBSCAN
        coordinates = np.array([event["click_position"] for event in self.event_list])
        if len(coordinates) == 0:
            logger.warning("No events to process.")
            return {}, {}

        # Define DBSCAN parameters
        epsilon = (
            self.main_app.settings.cluster_epsilon_value
        )  # Maximum distance between two samples for a cluster
        min_samples = 1  # Minimum number of samples in a neighborhood for a point to be a core point

        clustering = DBSCAN(eps=epsilon, min_samples=min_samples).fit(coordinates)
        labels = clustering.labels_

        # Group events by cluster label and compute bounding_rects once
        clusters = {}
        bounding_rects = {}
        for label, event in zip(labels, self.event_list):
            if label not in clusters:
                clusters[label] = []
                # Initialize bounding_rect for the new cluster
                x, y = event["click_position"]
                bounding_rects[label] = {
                    "left": x,
                    "top": y,
                    "right": x,
                    "bottom": y,
                }
            clusters[label].append(event)
            # Update bounding_rect
            rect = bounding_rects[label]
            rect["left"] = min(rect["left"], event["click_position"][0])
            rect["top"] = min(rect["top"], event["click_position"][1])
            rect["right"] = max(rect["right"], event["click_position"][0])
            rect["bottom"] = max(rect["bottom"], event["click_position"][1])

        # Finalize bounding_rects
        for label, rect in bounding_rects.items():
            bounding_rects[label] = {
                "left": rect["left"],
                "top": rect["top"],
                "width": rect["right"] - rect["left"] + 1,
                "height": rect["bottom"] - rect["top"] + 1,
            }

        logger.info(
            f"Total clusters formed: {len(clusters)} / bounding rects: {bounding_rects}"
        )

        # 전체 클러스터를 감싸는 하나의 큰 바운딩 박스 계산
        self.mega_bounding_rect = None
        if bounding_rects:
            all_lefts = [r["left"] for r in bounding_rects.values()]
            all_tops = [r["top"] for r in bounding_rects.values()]
            all_rights = [r["left"] + r["width"] for r in bounding_rects.values()]
            all_bottoms = [r["top"] + r["height"] for r in bounding_rects.values()]

            mega_left = min(all_lefts)
            mega_top = min(all_tops)
            self.mega_bounding_rect = {
                "left": mega_left,
                "top": mega_top,
                "width": max(all_rights) - mega_left,
                "height": max(all_bottoms) - mega_top,
            }

        logger.info(f"Mega bounding rect calculated: {self.mega_bounding_rect}")
        return clusters, bounding_rects

    def _start_loop(self):
        """
        Starts the asyncio event loop.
        """
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run_processor())

    async def run_processor(self):
        """
        The main asynchronous processor that handles clustering and keystroke simulation.
        """
        if not self.clusters:
            logger.warning("No clusters to process.")
            return

        try:
            while not self.terminate_event.is_set():
                if not self.is_process_active(self.target_process):
                    await asyncio.sleep(0.33)
                    continue

                # Check modification keys
                if await self.mod_key_handler.check_modification_keys():
                    await asyncio.sleep(random.uniform(*self.loop_delay))
                    continue

                # Process each cluster
                if not self.mega_bounding_rect:
                    await asyncio.sleep(0.1)
                    continue

                # 큰 영역을 한 번만 캡처
                grabbed_mega_image = self.sct.grab(self.mega_bounding_rect)

                tasks = []
                for cluster_id, events in self.clusters.items():
                    task = asyncio.create_task(
                        # 캡처된 이미지와 메가 박스 정보를 전달
                        self.process_cluster(grabbed_mega_image, events)
                    )
                    tasks.append(task)

                if tasks:
                    await asyncio.gather(*tasks)

                await asyncio.sleep(random.uniform(*self.loop_delay))

        except asyncio.CancelledError:
            logger.info("run_processor received cancellation request.")

        finally:
            logger.info("ThreadPoolExecutor has been shut down.")

    async def process_cluster(self, grabbed_mega_image, events: List[Dict]):
        """
        Processes a single cluster of events by grabbing the minimal bounding rectangle and simulating keystrokes.

        :param bounding_rect: The bounding rectangle dictionary for the cluster.
        :param events: List of event dictionaries in the cluster.
        """
        # Process each event in the cluster
        for event in events:
            # 메가 캡처 이미지 내에서의 상대 좌표 계산
            rel_x = event["click_position"][0] - self.mega_bounding_rect["left"]
            rel_y = event["click_position"][1] - self.mega_bounding_rect["top"]

            try:
                pixel = grabbed_mega_image.pixel(rel_x, rel_y)
            except IndexError:
                logger.error(
                    f"Pixel ({rel_x}, {rel_y}) out of bounds in grabbed region."
                )
                continue

            if pixel[:3] == event["ref_pixel_value"]:
                asyncio.create_task(
                    asyncio.to_thread(
                        self._simulate_keystroke_sync, event["key"], uuid.uuid4()
                    )
                )
                await asyncio.sleep(random.uniform(0.025, 0.05))

    def _simulate_keystroke_sync(self, key: str, task_id: uuid.UUID):
        """
        Synchronously simulates a keystroke.

        :param key: The key to simulate.
        :param task_id: Unique identifier for the task.
        """
        key_code = self.key_codes.get(key.upper())
        if key_code is None:
            logger.error(f"Task {task_id}: A key without a code was pressed: {key}")
            return

        # Acquire lock to check and update pressed_keys
        with self.pressed_keys_lock:
            if key in self.pressed_keys:
                logger.debug(
                    f"Task {task_id}: Key '{key}' is already pressed. Skipping."
                )
                return
            self.pressed_keys.add(key)
            logger.debug(f"Task {task_id}: Key '{key}' added to pressed_keys.")

        try:
            self.key_simulator.press_key(key_code)
            logger.debug(f"Task {task_id}: Key '{key}' pressed.")
            time.sleep(random.uniform(*self.key_pressed_time))
            self.key_simulator.release_key(key_code)
            logger.debug(f"Task {task_id}: Key '{key}' released.")
            logger.info(f"Task {task_id}: Key '{key}' simulated.")
        finally:
            # Ensure the key is removed from pressed_keys even if an error occurs
            with self.pressed_keys_lock:
                self.pressed_keys.discard(key)
                logger.debug(f"Task {task_id}: Key '{key}' removed from pressed_keys.")

    def _is_process_active_windows(self, process_id: int) -> bool:
        """
        Checks if the specified process is active on Windows.

        :param process_id: The process ID to check.
        :return: True if active, else False.
        """
        try:
            active_window = win32gui.GetForegroundWindow()
            if not active_window:
                return False
            _, active_pid = win32process.GetWindowThreadProcessId(active_window)
            return process_id == active_pid
        except Exception as e:
            logger.error(f"Error checking active process on Windows: {e}")
            return False

    def _is_process_active_darwin(self, process_id: int) -> bool:
        """
        Checks if the specified process is active on macOS.

        :param process_id: The process ID to check.
        :return: True if active, else False.
        """
        try:
            active_app = AppKit.NSWorkspace.sharedWorkspace().activeApplication()
            return (
                active_app is not None
                and active_app.get("NSApplicationProcessIdentifier") == process_id
            )
        except Exception as e:
            logger.error(f"Error checking active process on macOS: {e}")
            return False

    def start(self):
        """
        Starts the KeystrokeProcessor.
        """
        logger.info("KeystrokeProcessor started.")

    def stop(self):
        """
        Stops the KeystrokeProcessor.
        """
        self.sct.close()
        self.terminate_event.set()
        self.thread.join()
        logger.info("KeystrokeProcessor stopped.")
