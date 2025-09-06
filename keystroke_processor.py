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

# 가정: keystroke_models와 keystroke_utils는 올바르게 임포트 가능
from keystroke_models import EventModel
from keystroke_utils import KeyUtils, ProcessUtils

# OS-specific imports
if platform.system() == "Windows":
    import win32gui
    import win32process
elif platform.system() == "Darwin":
    import AppKit
    from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap
else:
    # 지원되지 않는 OS에 대한 처리
    pass


class KeySimulator:
    """OS에 맞는 키 입력을 시뮬레이션하는 클래스."""

    def __init__(self, os_type: str):
        os_map = {"Windows": "_win", "Darwin": "_darwin"}
        suffix = os_map.get(os_type, "_unsupported")
        try:
            self.press_key = getattr(self, f"_press_key{suffix}")
            self.release_key = getattr(self, f"_release_key{suffix}")
        except AttributeError:
            # 지원되지 않는 OS인 경우, 에러를 발생시키거나 비활성 함수를 할당
            logger.error(f"Unsupported OS for KeySimulator: {os_type}")
            self.press_key = self.release_key = self._unsupported_op

    def _press_key_win(self, code: int):
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)

    def _release_key_win(self, code: int):
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)

    def _press_key_darwin(self, code: int):
        event = CGEventCreateKeyboardEvent(None, code, True)
        CGEventPost(kCGHIDEventTap, event)

    def _release_key_darwin(self, code: int):
        event = CGEventCreateKeyboardEvent(None, code, False)
        CGEventPost(kCGHIDEventTap, event)

    def _unsupported_op(self, code: int):
        pass


class ModificationKeyHandler:
    """수식 키(Modifier key) 입력을 처리하는 클래스."""

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

    async def check_and_process(self) -> bool:
        """
        수식 키 입력을 확인하고, 눌렸을 경우 관련 동작을 수행합니다.
        :return: 수식 키가 하나라도 눌렸으면 True, 아니면 False.
        """
        any_mod_key_pressed = False
        tasks = []
        for key, value in self.modification_keys.items():
            if KeyUtils.mod_key_pressed(key):
                any_mod_key_pressed = True
                logger.debug(
                    f"Modification key '{key}' pressed. Pass: {value.get('pass')}"
                )
                if not value.get("pass"):
                    # 키 입력을 비동기 태스크로 만들어 동시에 처리할 수 있도록 함
                    tasks.append(self.simulate_keystroke(value["value"]))

        if tasks:
            await asyncio.gather(*tasks)

        if any_mod_key_pressed:
            self.mod_key_pressed.set()
        else:
            self.mod_key_pressed.clear()

        return any_mod_key_pressed

    async def simulate_keystroke(self, key: str):
        """
        단일 키 입력을 비동기적으로 시뮬레이션합니다.
        :param key: 시뮬레이션할 키.
        """
        key_code = self.key_codes.get(key.upper())
        if key_code is None:
            logger.error(f"A modification key without a code was pressed: {key}")
            return

        logger.debug(f"Simulating keystroke for '{key}' with modification.")
        self.key_simulator.press_key(key_code)
        await asyncio.sleep(random.uniform(*self.key_pressed_time))
        self.key_simulator.release_key(key_code)


class KeystrokeProcessor:
    """
    화면 픽셀 감지를 통해 키 입력을 자동화하는 메인 프로세서 클래스.
    """

    PROCESS_ID_PATTERN = re.compile(r"\((\d+)\)")
    INACTIVE_PROCESS_CHECK_INTERVAL = 0.33
    SHORT_DELAY_INTERVAL = 0.1
    KEY_SIMULATION_PAUSE_MIN = 0.025
    KEY_SIMULATION_PAUSE_MAX = 0.050

    def __init__(
        self,
        main_app,
        target_process: str,
        event_list: List[EventModel],
        modification_keys: Dict[str, Dict],
        terminate_event: threading.Event,
    ):
        self.main_app = main_app
        self.target_process_pid = self._parse_process_id(target_process)
        self.terminate_event = terminate_event
        self.os_type = platform.system()

        # 설정값 초기화
        settings = self.main_app.settings
        self.loop_delay = (
            settings.delay_between_loop_min / 1000,
            settings.delay_between_loop_max / 1000,
        )
        self.key_pressed_time = (
            settings.key_pressed_time_min / 1000,
            settings.key_pressed_time_max / 1000,
        )

        # 의존성 객체 초기화
        self.key_codes = KeyUtils.get_key_list()
        self.key_simulator = KeySimulator(self.os_type)
        self.mod_key_handler = ModificationKeyHandler(
            self.key_codes,
            self.loop_delay,
            self.key_pressed_time,
            modification_keys,
            self.os_type,
        )
        self.sct = None

        # 데이터 처리 및 클러스터링
        prepared_events = self._prepare_events(event_list)
        self.clusters, self.mega_bounding_rect = self._compute_clusters_and_mega_rect(
            prepared_events
        )

        # 동시성 관련 초기화
        self.pressed_keys = set()
        self.pressed_keys_lock = threading.Lock()

        # 비동기 루프를 위한 스레드 시작
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._start_async_loop, daemon=True)

    def start(self):
        """프로세서를 시작합니다."""
        logger.info("KeystrokeProcessor starting...")
        self.thread.start()

    def stop(self):
        """프로세서를 안전하게 중지합니다."""
        logger.info("KeystrokeProcessor stopping...")
        self.terminate_event.set()

        # 스레드가 완전히 종료될 때까지 대기 (sct는 워커 스레드에서 정리)
        if self.thread.is_alive():
            self.thread.join()
        logger.info("KeystrokeProcessor stopped.")

    # --- Private Helper Methods (Initialization & Setup) ---

    @staticmethod
    def _parse_process_id(target_process: str) -> Optional[int]:
        match = KeystrokeProcessor.PROCESS_ID_PATTERN.search(target_process)
        return int(match.group(1)) if match else None

    def _prepare_events(self, event_list: List[EventModel]) -> List[EventModel]:
        prepared = []
        seen_events = set()
        for event in event_list:
            if not event.use_event:
                continue

            x = event.latest_position[0] + event.clicked_position[0]
            y = event.latest_position[1] + event.clicked_position[1]

            # 기준 픽셀 값은 (R, G, B) 순서로 저장
            ref_pixel = tuple(event.ref_pixel_value[:3])
            key_to_enter = event.key_to_enter.upper()

            event_key = ((x, y), ref_pixel, key_to_enter)
            if event_key not in seen_events:
                seen_events.add(event_key)
                # Create a new dictionary to avoid modifying the original event
                event_data = {
                    "event_name": event.event_name,
                    "ref_pixel_value": ref_pixel,
                    "click_position": (x, y),
                    "key": key_to_enter,
                    "press_duration_ms": event.press_duration_ms,
                    "randomization_ms": event.randomization_ms,
                }
                prepared.append(event_data)
        return prepared

    def _compute_clusters_and_mega_rect(
        self, events: List[Dict]
    ) -> Tuple[Dict, Optional[Dict]]:
        if not events:
            logger.warning("No events to process for clustering.")
            return {}, None

        coordinates = np.array([event["click_position"] for event in events])
        epsilon = self.main_app.settings.cluster_epsilon_value
        clustering = DBSCAN(eps=epsilon, min_samples=1).fit(coordinates)

        clusters = {}
        for label, event in zip(clustering.labels_, events):
            clusters.setdefault(label, []).append(event)

        logger.info(f"Total {len(clusters)} clusters formed.")

        bounding_rects = {
            label: self._get_bounding_rect_for_events(cluster_events)
            for label, cluster_events in clusters.items()
        }

        mega_rect = self._calculate_mega_bounding_rect(list(bounding_rects.values()))
        logger.info(f"Mega bounding rect calculated: {mega_rect}")

        return clusters, mega_rect

    @staticmethod
    def _get_bounding_rect_for_events(events: List[Dict]) -> Dict[str, int]:
        coords = np.array([e["click_position"] for e in events])
        x_min, y_min = coords.min(axis=0)
        x_max, y_max = coords.max(axis=0)
        return {
            "left": int(x_min),
            "top": int(y_min),
            "width": int(x_max - x_min + 1),
            "height": int(y_max - y_min + 1),
        }

    @staticmethod
    def _calculate_mega_bounding_rect(rects: List[Dict]) -> Optional[Dict[str, int]]:
        if not rects:
            return None

        min_left = min(r["left"] for r in rects)
        min_top = min(r["top"] for r in rects)
        max_right = max(r["left"] + r["width"] for r in rects)
        max_bottom = max(r["top"] + r["height"] for r in rects)

        return {
            "left": int(min_left),
            "top": int(min_top),
            "width": int(max_right - min_left),
            "height": int(max_bottom - min_top),
        }

    # --- Main Asynchronous Loop Logic ---

    def _start_async_loop(self):
        asyncio.set_event_loop(self.loop)
        # 스레드 안전성을 위해 mss 객체를 스레드 내부에서 생성
        logger.debug("Creating mss object...")
        self.sct = mss.mss()
        logger.debug("mss object created, starting processor...")
        try:
            self.loop.run_until_complete(self._run_processor())
        finally:
            # sct 정리를 워커 스레드에서 처리
            if self.sct is not None:
                try:
                    self.sct.close()
                except Exception as e:
                    logger.debug(f"sct.close() failed: {e}")
            self.loop.close()

    async def _run_processor(self):
        if not self.clusters:
            logger.warning("No clusters to process. Processor will not run.")
            return

        logger.debug("Processor loop starting...")
        try:
            while not self.terminate_event.is_set():
                if not self._is_target_process_active():
                    await asyncio.sleep(self.INACTIVE_PROCESS_CHECK_INTERVAL)
                    continue

                if await self.mod_key_handler.check_and_process():
                    await asyncio.sleep(random.uniform(*self.loop_delay))
                    continue

                if not self.mega_bounding_rect:
                    await asyncio.sleep(self.SHORT_DELAY_INTERVAL)
                    continue

                # 캡처 및 처리를 비동기적으로 실행
                await self._capture_and_process_clusters()

                await asyncio.sleep(random.uniform(*self.loop_delay))

        except asyncio.CancelledError:
            logger.info("Processor task was cancelled.")
        finally:
            logger.info("Processor loop finished.")

    async def _capture_and_process_clusters(self):
        # 화면을 한 번 캡처하고 NumPy 배열로 변환
        grabbed_image = self.sct.grab(self.mega_bounding_rect)
        image_np = np.array(grabbed_image)

        # 각 클러스터를 병렬로 처리
        tasks = [
            self._process_cluster(image_np, events) for events in self.clusters.values()
        ]
        if tasks:
            await asyncio.gather(*tasks)

    async def _process_cluster(self, image_np: np.ndarray, events: List[Dict]):
        for event in events:
            rel_x = event["click_position"][0] - self.mega_bounding_rect["left"]
            rel_y = event["click_position"][1] - self.mega_bounding_rect["top"]

            try:
                # NumPy 배열에서 BGRA 픽셀 값을 가져옴
                pixel_bgra = image_np[rel_y, rel_x]
            except IndexError:
                continue

            # BGRA를 RGB 튜플로 변환하여 기준 값과 비교
            current_pixel_rgb = (pixel_bgra[2], pixel_bgra[1], pixel_bgra[0])
            if current_pixel_rgb == event["ref_pixel_value"]:
                await self._schedule_keystroke(event)

    async def _schedule_keystroke(self, event: Dict):
        # 키 입력을 시뮬레이션
        await self._simulate_keystroke_async(event)
        # 키 입력 후 짧은 지연을 주어 동시 다발적인 입력을 방지
        await asyncio.sleep(
            random.uniform(self.KEY_SIMULATION_PAUSE_MIN, self.KEY_SIMULATION_PAUSE_MAX)
        )

    async def _simulate_keystroke_async(self, event: Dict):
        key = event["key"]
        event_name = event.get("event_name", "Unnamed Event")
        key_code = self.key_codes.get(key.upper())
        if key_code is None:
            logger.error(f"Event '{event_name}': Key '{key}' has no valid key code.")
            return

        with self.pressed_keys_lock:
            if key in self.pressed_keys:
                return  # 이미 눌린 키는 무시
            self.pressed_keys.add(key)

        try:
            self.key_simulator.press_key(key_code)

            # 개별 이벤트에 설정된 press_duration_ms를 확인
            press_duration_ms = event.get("press_duration_ms")
            if press_duration_ms is not None:
                randomization_ms = event.get("randomization_ms", 0) or 0
                delay = (press_duration_ms / 1000) + (
                    random.uniform(-randomization_ms, randomization_ms) / 1000
                )
            else:
                # 기존 전역 설정 사용
                delay = random.uniform(*self.key_pressed_time)

            await asyncio.sleep(max(0, delay))  # 음수 딜레이 방지

            self.key_simulator.release_key(key_code)
            logger.info(
                f"Event '{event_name}': Key '{key}' simulated with delay {delay:.4f}s."
            )
        finally:
            with self.pressed_keys_lock:
                self.pressed_keys.discard(key)

    # --- OS-specific Methods ---

    def _is_target_process_active(self) -> bool:
        return ProcessUtils.is_process_active(self.target_process_pid)
