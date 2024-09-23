import platform
import random
import re
import threading
import time
from threading import Thread
from typing import List, Dict, Optional, Tuple

import mss
from loguru import logger

from keystroke_models import EventModel
from keystroke_utils import KeyUtils

# OS-specific imports
if platform.system() == "Windows":
    import win32gui
    import win32process
    import ctypes
elif platform.system() == "Darwin":
    import AppKit
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        kCGHIDEventTap,
    )


class BaseKeyHandler:
    def __init__(
            self,
            key_codes,
            loop_delay: Tuple[float, float],
            key_pressed_time: Tuple[float, float],
    ):
        self.key_codes = key_codes
        self.loop_delay = loop_delay
        self.key_pressed_time = key_pressed_time

        if platform.system() == "Windows":
            self.press_key = self._press_key_windows
            self.release_key = self._release_key_windows
        elif platform.system() == "Darwin":
            self.press_key = self._press_key_darwin
            self.release_key = self._release_key_darwin

    @staticmethod
    def _press_key_windows(code: int):
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)

    @staticmethod
    def _release_key_windows(code: int):
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)

    @staticmethod
    def _press_key_darwin(code: int):
        event = CGEventCreateKeyboardEvent(None, code, True)
        CGEventPost(kCGHIDEventTap, event)

    @staticmethod
    def _release_key_darwin(code: int):
        event = CGEventCreateKeyboardEvent(None, code, False)
        CGEventPost(kCGHIDEventTap, event)

    def get_sleep_time(self) -> float:
        return random.uniform(self.loop_delay[0], self.loop_delay[1])

    def get_key_press_time(self) -> float:
        return random.uniform(self.key_pressed_time[0], self.key_pressed_time[1])

    def simulate_keystroke(self, key: str):
        key_code = self.key_codes.get(key.upper())
        if key_code is None:
            logger.error(f"A key without a code was pressed: {key}")
            return

        self.press_key(key_code)
        time.sleep(self.get_key_press_time())
        self.release_key(key_code)


class RegularKeyHandler(BaseKeyHandler):
    def simulate_keystroke(self, key: str):
        super().simulate_keystroke(key)


class ModificationKeyHandler(BaseKeyHandler):
    def __init__(
            self,
            key_codes,
            loop_delay: Tuple[float, float],
            key_pressed_time: Tuple[float, float],
            modification_keys,
    ):
        super().__init__(key_codes, loop_delay, key_pressed_time)
        self.modification_keys = {
            key: value for key, value in modification_keys.items() if value.get("enabled")
        }
        self.mod_key_pressed = threading.Event()

    def check_modification_keys(self, is_mod_key_handler: bool = False) -> bool:
        any_mod_key_pressed = False
        for key, value in self.modification_keys.items():
            if KeyUtils.mod_key_pressed(key):
                any_mod_key_pressed = True
                if not value["pass"] and is_mod_key_handler:
                    self.simulate_keystroke(value["value"])
                    logger.debug(
                        f"Key '{value["value"]}' pressed with mod-key '{key.upper()}'"
                    )
                    time.sleep(random.uniform(self.loop_delay[0], self.loop_delay[1]))

        if any_mod_key_pressed:
            self.mod_key_pressed.set()
        else:
            self.mod_key_pressed.clear()

        return any_mod_key_pressed

    def simulate_keystroke(self, key: str):
        super().simulate_keystroke(key)


class KeystrokeEngine(Thread):
    PROCESS_ID_PATTERN = re.compile(r"\((\d+)\)")

    def __init__(
            self,
            main,
            target_process: str,
            event_list: List[EventModel],
            modification_keys: dict,
            terminate_event: threading.Event,
            is_mod_key_handler: bool = False,
    ):
        super().__init__()
        self.main = main
        self.loop_delay = (
            self.main.settings.delay_between_loop_min / 1000,
            self.main.settings.delay_between_loop_max / 1000,
        )
        self.key_pressed_time = (
            self.main.settings.key_pressed_time_min / 1000,
            self.main.settings.key_pressed_time_max / 1000,
        )

        self.target_process = self.parse_process_id(target_process)
        self.event_list = self.prepare_events(event_list)
        self.terminate_event = terminate_event
        self.key_codes = KeyUtils.get_key_list()

        self.regular_key_handler = RegularKeyHandler(
            self.key_codes, self.loop_delay, self.key_pressed_time
        )
        self.mod_key_handler = ModificationKeyHandler(
            self.key_codes, self.loop_delay, self.key_pressed_time, modification_keys
        )
        self.is_mod_key_handler = is_mod_key_handler

        # OS-specific initialization
        if platform.system() == "Windows":
            self.is_process_active = self._is_process_active_windows
        elif platform.system() == "Darwin":
            self.is_process_active = self._is_process_active_darwin

        if len(self.event_list) > 1 and not self.is_mod_key_handler:
            # Precompute the minimal bounding rectangle for all events in the cluster
            self.bounding_rect = self.compute_bounding_rectangle()

            # Map events to their relative positions within the bounding rectangle
            self.relative_events = self.map_events_to_relative_positions()

            logger.info(f"bounding rect: {self.bounding_rect}, relative events: {self.relative_events}")

    def compute_bounding_rectangle(self) -> Dict[str, int]:
        """
        Computes the minimal bounding rectangle that encompasses all event click positions.
        """
        xs = [event["click_position"][0] for event in self.event_list]
        ys = [event["click_position"][1] for event in self.event_list]
        left = min(xs)
        top = min(ys)
        right = max(xs)
        bottom = max(ys)
        width = right - left + 1
        height = bottom - top + 1
        return {"left": left, "top": top, "width": width, "height": height}

    def map_events_to_relative_positions(self) -> List[Dict]:
        """
        Maps each event's click position to its relative position within the bounding rectangle.
        """
        relative_events = []
        for event in self.event_list:
            x, y = event["click_position"]
            relative_x = x - self.bounding_rect["left"]
            relative_y = y - self.bounding_rect["top"]
            relative_events.append({
                "ref_pixel_value": event["ref_pixel_value"],
                "relative_position": (relative_x, relative_y),
                "key": event["key"],
            })
        return relative_events

    @staticmethod
    def parse_process_id(target_process: str) -> Optional[int]:
        match = KeystrokeEngine.PROCESS_ID_PATTERN.search(target_process)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def prepare_events(event_list: List[EventModel]) -> List[Dict]:
        return [
            {
                "ref_pixel_value": tuple(event.ref_pixel_value[:3]),
                "click_position": (
                    event.latest_position[0] + event.clicked_position[0],
                    event.latest_position[1] + event.clicked_position[1],
                ),
                "key": event.key_to_enter,
            }
            for event in event_list
        ]

    def run(self):
        prev_key = None
        key_count = 0
        max_key_count = self.main.settings.max_key_count
        last_pressed_time = 0
        last_grab_result = None
        last_grab_time = 0

        with mss.mss() as sct:
            while not self.terminate_event.is_set():
                if not self.is_process_active(self.target_process):
                    time.sleep(0.33)
                    continue

                # Check modification keys
                if self.mod_key_handler.check_modification_keys(
                        self.is_mod_key_handler
                ):
                    if not self.is_mod_key_handler:
                        self.mod_key_handler.mod_key_pressed.wait()
                    time.sleep(random.uniform(self.loop_delay[0], self.loop_delay[1]))
                    continue

                if self.is_mod_key_handler:
                    time.sleep(random.uniform(self.loop_delay[0], self.loop_delay[1]))
                    continue

                current_time = time.time()

                for event in self.event_list:
                    x, y = event["click_position"]

                    if (
                            last_grab_result
                            and last_grab_result[1] == (x, y)
                            and current_time - last_grab_time < 0.1
                    ):
                        current_pixel = last_grab_result[0]
                    else:
                        current_pixel = sct.grab(
                            {"top": y, "left": x, "width": 1, "height": 1}
                        ).pixel(0, 0)
                        last_grab_result = (current_pixel, (x, y))
                        last_grab_time = current_time

                    if current_pixel[:3] == event["ref_pixel_value"]:
                        key = event["key"]
                        between_pressed = current_time - last_pressed_time
                        if key == prev_key:
                            key_count += 1
                            if key_count <= max_key_count:
                                self.regular_key_handler.simulate_keystroke(key)
                                logger.debug(
                                    f"{self.name:<10} Key '{key}' pressed with a {between_pressed}"
                                )
                        else:
                            prev_key = key
                            key_count = 1
                            self.regular_key_handler.simulate_keystroke(key)
                            logger.debug(
                                f"{self.name:<10} Key '{key}' pressed with a {between_pressed}-seconds."
                            )
                        last_pressed_time = current_time
                        time.sleep(self.regular_key_handler.get_sleep_time())
                        break

        logger.info(f"KeystrokeEngine thread terminated: {self.name}")

    # Windows-specific methods
    @staticmethod
    def _is_process_active_windows(process_id: int) -> bool:
        active_window = win32gui.GetForegroundWindow()
        _, active_pid = win32process.GetWindowThreadProcessId(active_window)
        return process_id == active_pid

    # macOS-specific methods
    @staticmethod
    def _is_process_active_darwin(process_id: int) -> bool:
        active_app = AppKit.NSWorkspace.sharedWorkspace().activeApplication()
        return (
                active_app is not None
                and active_app["NSApplicationProcessIdentifier"] == process_id
        )
