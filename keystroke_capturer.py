import time
import tkinter as tk
from threading import Event, Thread
from typing import Callable, Optional, Tuple

import mss
import screeninfo
from PIL import Image


class ScreenshotCapturer:
    def __init__(self):
        current_monitor = screeninfo.get_monitors()[0]
        self.screen_width, self.screen_height = (
            current_monitor.width,
            current_monitor.height,
        )
        self.box_size = 100
        self.current_position = (0, 0)

        self.capturing: Event = Event()
        self.capture_thread: Optional[Thread] = None
        self.screenshot_callback: Callable[[Tuple, Image.Image], None] = None

    def get_current_mouse_position(self) -> Optional[Tuple[int, int]]:
        return self.current_position

    def set_current_mouse_position(self, position):
        mouse_x, mouse_y = position
        if (
            mouse_x + self.box_size >= self.screen_width
            or mouse_y + self.box_size >= self.screen_height
        ):
            return

        self.current_position = (mouse_x, mouse_y)

    def set_mouse_position(self, position):
        self.current_position = position

    def start_capture(self):
        self.capturing.set()
        self.capture_thread = Thread(target=self.capture_screenshot)
        self.capture_thread.start()

    def stop_capture(self):
        self.capturing.clear()

    def capture_screenshot(self):
        with mss.mss() as sct:
            while self.capturing.is_set():
                try:
                    position = self.get_current_mouse_position()
                    if position and self.screenshot_callback:
                        image = sct.grab(
                            {
                                "top": position[1],
                                "left": position[0],
                                "width": self.box_size,
                                "height": self.box_size,
                            }
                        )
                        pil_image = Image.frombytes(
                            "RGB", image.size, image.bgra, "raw", "BGRX"
                        )
                        self.screenshot_callback(position, pil_image)
                except tk.TclError as e:
                    print(f"Event windows has been destroyed: {e}")
                    self.capturing.clear()
                    break

                time.sleep(0.2)
