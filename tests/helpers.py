import threading

from app.core.processor import KeystrokeProcessor


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
