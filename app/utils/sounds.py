from __future__ import annotations

import atexit
import array
import base64
import importlib
import threading
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any, TypeAlias, cast

from loguru import logger

from app.utils.notification_sound_packs import (
    DEFAULT_NOTIFICATION_SOUND_PACK,
    get_notification_sound_pack,
    normalize_notification_sound_pack,
)

miniaudio: Any = importlib.import_module("miniaudio")
SampleArray: TypeAlias = array.array[int]

_CHANNELS = 2
_SAMPLE_RATE = 44100
_SAMPLE_FORMAT = miniaudio.SampleFormat.SIGNED16
_SAMPLE_WIDTH = int(miniaudio.width_from_format(_SAMPLE_FORMAT))
_BUFFER_MSEC = 20
_SAMPLE_MIN = -32768
_SAMPLE_MAX = 32767


@dataclass
class _ActiveSound:
    samples: SampleArray
    position: int


class _SoundHandle:
    def __init__(self, player: "SoundPlayer", samples: SampleArray) -> None:
        self._player = player
        self._samples = samples

    def play(self) -> None:
        self._player.queue_samples(self._samples)


class SoundPlayer:
    def __init__(self, pack_id: str | None = None) -> None:
        self.start_sound: _SoundHandle | None = None
        self.stop_sound: _SoundHandle | None = None
        self.runtime_toggle_on_sound: _SoundHandle | None = None
        self.runtime_toggle_off_sound: _SoundHandle | None = None
        self._active_sounds: list[_ActiveSound] = []
        self._lock = threading.Lock()
        self._device: Any | None = None
        self._stream: Generator[bytes | SampleArray, int, None] | None = None
        self._pack_cache: dict[str, tuple[_SoundHandle | None, _SoundHandle | None]] = {}
        self._toggle_pack_cache: dict[
            str, tuple[_SoundHandle | None, _SoundHandle | None]
        ] = {}
        self.notification_sound_pack: str = DEFAULT_NOTIFICATION_SOUND_PACK
        self.runtime_toggle_sound_pack: str = DEFAULT_NOTIFICATION_SOUND_PACK
        # Idle stop must never run inside the miniaudio data callback. A generation
        # token cancels stale stop workers when new audio is queued.
        self._idle_generation: int = 0
        self._idle_stop_pending: bool = False
        self._idle_stop_thread: threading.Thread | None = None
        self._starting: bool = False
        # Serialize native device start/stop/close across threads (never hold
        # self._lock while calling into miniaudio stop/close).
        self._device_io = threading.Lock()
        try:
            self.set_notification_pack(pack_id)
            self.set_runtime_toggle_pack(None)
            # Playback device starts on first play and stops when idle (no always-on audio thread).
            atexit.register(self.close)
        except Exception as e:
            self._disable()
            print(f"Sound init error: {e}")

    def set_notification_pack(self, pack_id: str | None) -> str:
        """Bind start/stop handles to a known pack; returns the applied pack id."""
        applied = normalize_notification_sound_pack(pack_id)
        if applied in self._pack_cache:
            start_h, stop_h = self._pack_cache[applied]
        else:
            pack = get_notification_sound_pack(applied)
            start_h = self._load_sound(pack.start_b64)
            stop_h = self._load_sound(pack.stop_b64)
            self._pack_cache[applied] = (start_h, stop_h)
        self.start_sound = start_h
        self.stop_sound = stop_h
        self.notification_sound_pack = applied
        return applied

    def set_runtime_toggle_pack(self, pack_id: str | None) -> str:
        """Bind toggle ON/OFF handles to a known pack; returns the applied id."""
        applied = normalize_notification_sound_pack(pack_id)
        if applied in self._toggle_pack_cache:
            on_h, off_h = self._toggle_pack_cache[applied]
        else:
            pack = get_notification_sound_pack(applied)
            on_h = self._load_sound(pack.on_b64)
            off_h = self._load_sound(pack.off_b64)
            self._toggle_pack_cache[applied] = (on_h, off_h)
        self.runtime_toggle_on_sound = on_h
        self.runtime_toggle_off_sound = off_h
        self.runtime_toggle_sound_pack = applied
        return applied

    def _load_sound(self, b64_data: str) -> _SoundHandle | None:
        """Decode base64 audio once so trigger-time playback stays lightweight."""
        if not b64_data:
            return None
        try:
            decoded = miniaudio.decode(
                base64.b64decode(b64_data),
                output_format=_SAMPLE_FORMAT,
                nchannels=_CHANNELS,
                sample_rate=_SAMPLE_RATE,
            )
            return _SoundHandle(self, cast(SampleArray, decoded.samples))
        except Exception as e:
            print(f"Sound load error: {e}")
            return None

    def _release_device(self, device: Any | None) -> None:
        """Stop then close a PlaybackDevice. Must not run inside the data callback."""
        if device is None:
            return
        with self._device_io:
            try:
                stop = getattr(device, "stop", None)
                if callable(stop):
                    stop()
            except Exception as exc:
                logger.debug(f"Sound device stop failed: {exc}")
            try:
                device.close()
            except Exception as exc:
                logger.debug(f"Sound device close failed: {exc}")

    def _start_device(self) -> None:
        """Start the playback device if it is not already running. Caller holds no lock."""
        with self._lock:
            if self._device is not None or self._starting:
                return
            self._starting = True
        device: Any | None = None
        stream: Generator[bytes | SampleArray, int, None] | None = None
        try:
            with self._device_io:
                stream = self._mix_stream()
                next(stream)
                created = miniaudio.PlaybackDevice(
                    output_format=_SAMPLE_FORMAT,
                    nchannels=_CHANNELS,
                    sample_rate=_SAMPLE_RATE,
                    buffersize_msec=_BUFFER_MSEC,
                )
                device = created
                with self._lock:
                    self._stream = stream
                    self._device = created
                    self._starting = False
                created.start(stream)
        except Exception:
            with self._lock:
                self._stream = None
                self._device = None
                self._starting = False
            self._release_device(device)
            raise

    def close(self) -> None:
        with self._lock:
            device = self._device
            self._device = None
            self._stream = None
            self._active_sounds.clear()
            self._idle_generation += 1
            self._idle_stop_pending = False
            self._starting = False
        self._release_device(device)

    def _disable(self) -> None:
        self.start_sound = None
        self.stop_sound = None
        self.runtime_toggle_on_sound = None
        self.runtime_toggle_off_sound = None
        self._pack_cache.clear()
        self._toggle_pack_cache.clear()
        self.notification_sound_pack = DEFAULT_NOTIFICATION_SOUND_PACK
        self.runtime_toggle_sound_pack = DEFAULT_NOTIFICATION_SOUND_PACK
        self.close()

    def __del__(self) -> None:
        self.close()

    def queue_samples(self, samples: SampleArray) -> None:
        with self._lock:
            self._active_sounds.append(_ActiveSound(samples, 0))
            # Cancel any in-flight idle stop so a restart is not racing a close.
            self._idle_generation += 1
            self._idle_stop_pending = False
            needs_start = self._device is None and not self._starting
        if needs_start:
            try:
                self._start_device()
            except Exception as exc:
                with self._lock:
                    device = self._device
                    self._active_sounds.clear()
                    self._device = None
                    self._stream = None
                    self._starting = False
                self._release_device(device)
                print(f"Sound device start error: {exc}")

    def _arm_idle_stop(self, generation: int) -> None:
        """Stop the device from a non-callback thread after the mix queue goes idle."""
        thread = threading.Thread(
            target=self._run_idle_stop,
            args=(generation,),
            name="sound-idle-stop",
            daemon=True,
        )
        with self._lock:
            self._idle_stop_thread = thread
        thread.start()

    def _run_idle_stop(self, generation: int) -> None:
        with self._lock:
            if generation != self._idle_generation:
                return
            if self._active_sounds:
                self._idle_stop_pending = False
                return
            device = self._device
            self._device = None
            self._stream = None
            self._idle_stop_pending = False
        # stop/close outside the lock and never from the audio callback thread.
        self._release_device(device)

    def _await_idle_stop(self, timeout: float = 1.0) -> None:
        """Join the latest idle-stop worker (tests / deterministic drain)."""
        with self._lock:
            thread = self._idle_stop_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _mix_stream(self) -> Generator[bytes | SampleArray, int, None]:
        required_frames = yield b""
        while True:
            sample_count = int(required_frames) * _CHANNELS
            with self._lock:
                active_sounds = self._active_sounds
                self._active_sounds = []
            if not active_sounds:
                mixed = None
            else:
                mixed = array.array("h", [0]) * sample_count
                remaining: list[_ActiveSound] = []
                for sound in active_sounds:
                    samples = sound.samples
                    position = sound.position
                    end = min(position + sample_count, len(samples))
                    for index, sample in enumerate(samples[position:end]):
                        value = mixed[index] + sample
                        if value > _SAMPLE_MAX:
                            value = _SAMPLE_MAX
                        elif value < _SAMPLE_MIN:
                            value = _SAMPLE_MIN
                        mixed[index] = value
                    if end < len(samples):
                        sound.position = end
                        remaining.append(sound)
                if remaining:
                    with self._lock:
                        if self._device is not None:
                            self._active_sounds = remaining + self._active_sounds
            if mixed is None:
                # Empty snapshot: re-check under the lock so a concurrent
                # queue_samples cannot leave work stranded while we arm idle stop.
                schedule_generation: int | None = None
                with self._lock:
                    if self._active_sounds:
                        # New samples arrived while we observed an empty queue.
                        continue
                    # Keep yielding silence from this generator until a non-callback
                    # thread stops the device. Never close/stop here: miniaudio
                    # invokes this generator on the CoreAudio IO thread.
                    if self._device is not None and not self._idle_stop_pending:
                        self._idle_generation += 1
                        self._idle_stop_pending = True
                        schedule_generation = self._idle_generation
                if schedule_generation is not None:
                    self._arm_idle_stop(schedule_generation)
                required_frames = yield b"\x00" * (sample_count * _SAMPLE_WIDTH)
                continue
            required_frames = yield mixed

    def play_start_sound(self) -> None:
        if self.start_sound:
            self.start_sound.play()

    def play_stop_sound(self) -> None:
        if self.stop_sound:
            self.stop_sound.play()

    def play_runtime_toggle_on_sound(self) -> None:
        if self.runtime_toggle_on_sound:
            self.runtime_toggle_on_sound.play()

    def play_runtime_toggle_off_sound(self) -> None:
        if self.runtime_toggle_off_sound:
            self.runtime_toggle_off_sound.play()
