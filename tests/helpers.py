import threading

from app.core.processor import ImageFrame, KeystrokeProcessor, Pixel


def make_processor_stub(event_data_list=None) -> KeystrokeProcessor:
    """테스트용 프로세서 stub 생성 (가장 풍부한 버전)"""
    proc = KeystrokeProcessor.__new__(KeystrokeProcessor)
    proc.state_lock = threading.Lock()
    proc.current_states = {}
    proc.term_event = threading.Event()
    proc.default_press_times = (0.1, 0.1)
    proc.event_data_list = event_data_list or []
    proc.runtime_toggle_active = False
    return proc


async def evaluate_processor_events(proc: KeystrokeProcessor, img=None) -> None:
    await proc._apply_local_match_states(
        proc._evaluate_capture_group(img, proc.event_data_list)
    )


def make_image_frame(
    width: int,
    height: int,
    fill: Pixel = (0, 0, 0),
    *,
    channels: int = 3,
) -> ImageFrame:
    data = bytearray(width * height * channels)
    frame = ImageFrame(
        width=width,
        height=height,
        data=data,
        row_stride=width * channels,
        pixel_stride=channels,
    )
    fill_frame_rect(frame, 0, 0, width, height, fill)
    return frame


def set_frame_pixel(frame: ImageFrame, x: int, y: int, color: Pixel) -> None:
    if not isinstance(frame.data, bytearray):
        raise TypeError("test frame data must be mutable")
    idx = frame.offset + y * frame.row_stride + x * frame.pixel_stride
    frame.data[idx] = color[0]
    frame.data[idx + 1] = color[1]
    frame.data[idx + 2] = color[2]
    if frame.pixel_stride > 3:
        frame.data[idx + 3] = 255


def fill_frame_rect(
    frame: ImageFrame,
    left: int,
    top: int,
    width: int,
    height: int,
    color: Pixel,
) -> None:
    for y in range(top, top + height):
        for x in range(left, left + width):
            set_frame_pixel(frame, x, y, color)
