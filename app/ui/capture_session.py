from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from PIL import Image

from app.core.capturer import ScreenshotCapturer
from app.core.models import ColorTuple, Position

MIN_CAPTURE_SIZE = 50
MAX_CAPTURE_SIZE = 1000


@dataclass(frozen=True)
class CaptureSnapshot:
    generation: int
    latest_position: Position | None
    latest_image: Image.Image | None
    held_image: Image.Image | None
    held_position: Position | None
    selected_position: Position | None
    reference_color: ColorTuple | None


class CaptureBackend(Protocol):
    screenshot_callback: Callable[[Position, Image.Image], None] | None
    capture_thread: threading.Thread | None

    def start_capture(self) -> None: ...
    def stop_capture(self) -> None: ...
    def set_capture_size(self, width: int, height: int) -> None: ...
    def set_mouse_position(self, position: Position) -> None: ...
    def set_current_mouse_position(self, position: Position) -> None: ...
    def get_current_mouse_position(self) -> Position: ...


class CaptureSession:
    """Thread-safe capture state with no Tk calls from the capture thread."""

    def __init__(self, capturer: CaptureBackend | None = None) -> None:
        self.capturer = capturer or ScreenshotCapturer()
        self._lock = threading.Lock()
        self._generation = 0
        self._latest_position: Position | None = None
        self._latest_image: Image.Image | None = None
        self._held_image: Image.Image | None = None
        self._held_position: Position | None = None
        self._selected_position: Position | None = None
        self._reference_color: ColorTuple | None = None
        self._stopped = True

    def start(self) -> None:
        with self._lock:
            self._stopped = False
        self.capturer.screenshot_callback = self._on_frame
        self.capturer.start_capture()

    def stop(self, join_timeout: float = 0.1) -> None:
        with self._lock:
            self._stopped = True
        self.capturer.screenshot_callback = None
        self.capturer.stop_capture()
        thread = self.capturer.capture_thread
        if thread is not None and thread.is_alive():
            thread.join(join_timeout)

    def _on_frame(self, position: Position, image: Image.Image) -> None:
        with self._lock:
            if self._stopped:
                return
            self._latest_position = position
            self._latest_image = image
            self._generation += 1

    def snapshot(self) -> CaptureSnapshot:
        with self._lock:
            return CaptureSnapshot(
                generation=self._generation,
                latest_position=self._latest_position,
                latest_image=self._latest_image,
                held_image=self._held_image,
                held_position=self._held_position,
                selected_position=self._selected_position,
                reference_color=self._reference_color,
            )

    def set_capture_size(self, width: int, height: int) -> Position:
        size = (
            max(MIN_CAPTURE_SIZE, min(MAX_CAPTURE_SIZE, int(width))),
            max(MIN_CAPTURE_SIZE, min(MAX_CAPTURE_SIZE, int(height))),
        )
        self.capturer.set_capture_size(*size)
        return size

    def set_position(self, position: Position, *, force: bool = False) -> None:
        if force:
            self.capturer.set_mouse_position(position)
        else:
            self.capturer.set_current_mouse_position(position)

    def current_position(self) -> Position:
        return self.capturer.get_current_mouse_position()

    def hold(self) -> bool:
        with self._lock:
            if self._latest_image is None:
                return False
            self._held_image = self._latest_image.copy()
            self._held_position = self._latest_position
            return True

    def select(self, position: Position, display_size: Position) -> bool:
        display_width, display_height = display_size
        with self._lock:
            image = self._held_image
            if image is None or display_width <= 1 or display_height <= 1:
                return False
            x = int(position[0] * image.width / display_width)
            y = int(position[1] * image.height / display_height)
            if not (0 <= x < image.width and 0 <= y < image.height):
                return False
            self._selected_position = (x, y)
            self._reference_color = _normalize_color(image.getpixel((x, y)))
            return True

    def restore(
        self,
        *,
        latest_position: Position | None,
        held_image: Image.Image | None,
        selected_position: Position | None,
        reference_color: ColorTuple | None,
    ) -> None:
        with self._lock:
            self._latest_position = latest_position
            self._latest_image = held_image
            self._held_image = held_image
            self._held_position = latest_position
            self._selected_position = selected_position
            self._reference_color = reference_color
            self._generation += 1

    @property
    def latest_position(self) -> Position | None:
        return self.snapshot().latest_position

    @latest_position.setter
    def latest_position(self, value: Position | None) -> None:
        with self._lock:
            self._latest_position = value

    @property
    def latest_image(self) -> Image.Image | None:
        return self.snapshot().latest_image

    @latest_image.setter
    def latest_image(self, value: Image.Image | None) -> None:
        with self._lock:
            self._latest_image = value
            self._generation += 1

    @property
    def held_image(self) -> Image.Image | None:
        return self.snapshot().held_image

    @held_image.setter
    def held_image(self, value: Image.Image | None) -> None:
        with self._lock:
            self._held_image = value
            self._held_position = self._latest_position if value is not None else None

    @property
    def held_position(self) -> Position | None:
        return self.snapshot().held_position

    @property
    def selected_position(self) -> Position | None:
        return self.snapshot().selected_position

    @selected_position.setter
    def selected_position(self, value: Position | None) -> None:
        with self._lock:
            self._selected_position = value

    @property
    def reference_color(self) -> ColorTuple | None:
        return self.snapshot().reference_color

    @reference_color.setter
    def reference_color(self, value: ColorTuple | None) -> None:
        with self._lock:
            self._reference_color = value


def _normalize_color(value: object) -> ColorTuple:
    if isinstance(value, tuple):
        channels = cast(tuple[object, ...], value)
        return tuple(
            int(channel) if isinstance(channel, int | float) else 0
            for channel in channels
        )
    if isinstance(value, int | float):
        channel = int(value)
        return (channel, channel, channel)
    return (0, 0, 0)
