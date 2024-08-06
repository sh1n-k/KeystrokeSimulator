import platform
import random
import threading
import time
from threading import Thread
from typing import List, Dict, Optional

import mss
from loguru import logger

from keystroke_models import EventModel
from keystroke_utils import KeyUtils

# OS-specific initialization
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


class KeystrokeEngine(Thread):
    def __init__(
        self,
        main,
        target_process: str,
        event_list: List[EventModel],
        terminate_event: threading.Event,
    ):
        super().__init__()
        self.main = main
        self.loop_delay = (
            self.main.settings.delay_between_loop_min / 1000,
            self.main.settings.delay_between_loop_max / 1000,
        )
        self.key_pressed = (
            self.main.settings.key_pressed_time_min / 1000,
            self.main.settings.key_pressed_time_max / 1000,
        )

        self.target_process = self.parse_process_id(target_process)
        self.event_list = self.prepare_events(event_list)
        self.terminate_event = terminate_event
        self.key_codes = KeyUtils.get_key_list()

        # OS-specific initialization
        if platform.system() == "Windows":
            self.is_process_active = self._is_process_active_windows
            self.press_key = self._press_key_windows
            self.release_key = self._release_key_windows
        elif platform.system() == "Darwin":
            self.is_process_active = self._is_process_active_darwin
            self.press_key = self._press_key_darwin
            self.release_key = self._release_key_darwin

    @staticmethod
    def parse_process_id(target_process: str) -> Optional[int]:
        try:
            return int(
                target_process[
                    target_process.index("(") + 1 : target_process.index(")")
                ]
            )
        except (ValueError, IndexError):
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
        max_key_count = 10
        sleep_duration = 0.1
        last_pressed_time = 0
        last_grab_result = None
        last_grab_time = 0

        with mss.mss() as sct:
            while not self.terminate_event.is_set():
                if not self.is_process_active(self.target_process):
                    time.sleep(sleep_duration)
                    continue

                for event in self.event_list:
                    x, y = event["click_position"]
                    current_time = time.time()

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
                                self.simulate_keystroke(key)
                        else:
                            prev_key = key
                            key_count = 1
                            self.simulate_keystroke(key)
                        last_pressed_time = current_time
                        logger.debug(f"pressed gap: {between_pressed}")
                        time.sleep(
                            random.uniform(self.loop_delay[0], self.loop_delay[1])
                        )
                        break

        logger.info("KeystrokeEngine thread terminated.")

    def simulate_keystroke(self, key: str):
        key_code = self.key_codes[key.upper()]
        self.press_key(key_code)
        time.sleep(random.uniform(self.key_pressed[0], self.key_pressed[1]))
        self.release_key(key_code)

    # Windows-specific methods
    @staticmethod
    def _is_process_active_windows(process_id: int) -> bool:
        logger.debug(f"processId: {process_id}")
        active_window = win32gui.GetForegroundWindow()
        _, active_pid = win32process.GetWindowThreadProcessId(active_window)
        return process_id == active_pid

    @staticmethod
    def _press_key_windows(code: int):
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)

    @staticmethod
    def _release_key_windows(code: int):
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)

    # macOS-specific methods
    @staticmethod
    def _is_process_active_darwin(process_id: int) -> bool:
        logger.debug(f"processId: {process_id}")
        active_app = AppKit.NSWorkspace.sharedWorkspace().activeApplication()
        return (
            active_app is not None
            and active_app["NSApplicationProcessIdentifier"] == process_id
        )

    @staticmethod
    def _press_key_darwin(code: int):
        event = CGEventCreateKeyboardEvent(None, code, True)
        CGEventPost(kCGHIDEventTap, event)

    @staticmethod
    def _release_key_darwin(code: int):
        event = CGEventCreateKeyboardEvent(None, code, False)
        CGEventPost(kCGHIDEventTap, event)
