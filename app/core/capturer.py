import time
import tkinter as tk
from threading import Event, Thread
from collections.abc import Callable

from PIL import Image
from loguru import logger

from app.core.screen_backend import (
    BACKEND_RETRY_INTERVAL_S,
    ScreenBackend,
    open_screen_backend,
)
from app.utils.system import MonitorUtils


class ScreenshotCapturer:
    def __init__(self) -> None:
        self.screen_width, self.screen_height = MonitorUtils.get_primary_size()
        self.box_w = 100
        self.box_h = 100
        self.current_position: tuple[int, int] = (0, 0)

        self.capturing: Event = Event()
        self.capture_thread: Thread | None = None
        self.screenshot_callback: Callable[[tuple[int, int], Image.Image], None] | None = None
        self._last_capture_signature: tuple[tuple[int, int], int, int] | None = None
        self._idle_cycles = 0

    def get_current_mouse_position(self) -> tuple[int, int]:
        return self.current_position

    def set_capture_size(self, w: int, h: int) -> None:
        self.box_w, self.box_h = max(1, w), max(1, h)

    def set_current_mouse_position(self, position: tuple[int, int]) -> None:
        mouse_x, mouse_y = position
        if (
            mouse_x + self.box_w >= self.screen_width
            or mouse_y + self.box_h >= self.screen_height
        ):
            return

        self.current_position = (mouse_x, mouse_y)

    def set_mouse_position(self, position: tuple[int, int]) -> None:
        self.current_position = position

    def start_capture(self) -> None:
        self.capturing.set()
        self._last_capture_signature = None
        self._idle_cycles = 0
        self.capture_thread = Thread(target=self.capture_screenshot, daemon=True)
        self.capture_thread.start()

    def stop_capture(self) -> None:
        self.capturing.clear()

    def _screen_group(self) -> dict[str, object]:
        return {
            "rect": {
                "left": 0,
                "top": 0,
                "width": self.screen_width,
                "height": self.screen_height,
            },
            "events": [],
        }

    def _capture_group(self, position: tuple[int, int]) -> dict[str, object]:
        """미리보기 영역. 좌표를 손대지 않는다 — 여기서 보정하면 저장되는
        기준 좌표와 어긋나 엉뚱한 픽셀이 기준색으로 남는다."""
        return {
            "rect": {
                "left": position[0],
                "top": position[1],
                "width": self.box_w,
                "height": self.box_h,
            },
            "events": [],
        }

    def capture_screenshot(self) -> None:
        # 실행 루프와 같은 백엔드로 찍는다. 경로가 다르면 여기서 고른 기준색이
        # 실행 중에는 픽셀값이 달라 맞지 않는다.
        backend: ScreenBackend = open_screen_backend([self._screen_group()])
        last_retry = 0.0  # 죽은 채로 시작하면 곧바로 다시 열어본다
        try:
            while self.capturing.is_set():
                try:
                    position = self.get_current_mouse_position()
                    callback = self.screenshot_callback
                    group = self._capture_group(position) if position else None
                    if group is not None and callback:
                        capture_signature = (position, self.box_w, self.box_h)
                        if capture_signature == self._last_capture_signature:
                            self._idle_cycles = min(self._idle_cycles + 1, 5)
                        else:
                            self._last_capture_signature = capture_signature
                            self._idle_cycles = 0

                        if backend.is_dead():
                            backend, last_retry = self._reopen(backend, last_retry)
                        frame = backend.grab([group])[0]
                        if frame is not None:
                            callback(position, frame.to_rgb_image())
                except tk.TclError as e:
                    logger.error(f"Event windows has been destroyed: {e}")
                    self.capturing.clear()
                    break
                except Exception as e:
                    logger.error(f"Preview capture failed: {e}")
                time.sleep(0.2 if self._idle_cycles == 0 else 0.3)
        finally:
            backend.close()

    def _reopen(
        self, backend: ScreenBackend, last_retry: float
    ) -> tuple[ScreenBackend, float]:
        if time.monotonic() - last_retry < BACKEND_RETRY_INTERVAL_S:
            return backend, last_retry
        backend.close()
        try:
            fresh: ScreenBackend = open_screen_backend([self._screen_group()])
        except Exception as exc:
            logger.error(f"Preview backend restart failed: {exc}")
            fresh = backend
        # 실패 경로가 수 초 걸릴 수 있다. 간격은 시도가 '끝난' 뒤부터 센다.
        return fresh, time.monotonic()
