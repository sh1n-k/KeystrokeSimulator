"""soft_a/b/c 두 음 알림음(시작·종료·토글 ON) 생성.

첫 음을 자르지 않고 다음 음 아래에서 계속 잦아들게 해 음 사이에 무음 구간이
생기지 않게 한다. 단음인 토글 OFF는 대상이 아니다.

출력:
  samples/notification-preview/set{A,B,C}_{start,stop}.wav
  app/utils/notification_sound_packs.py   (_SOFT_*_START / _SOFT_*_STOP)
  app/utils/_toggle_notification_sounds.py (SOFT_*_TOGGLE_ON)

실행:
  uv run -m scripts.generate_soft_notification_sounds
"""

from __future__ import annotations

import array
import base64
import io
import math
import re
import wave
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "samples" / "notification-preview"
PACKS_FILE = PROJECT_ROOT / "app" / "utils" / "notification_sound_packs.py"
TOGGLE_FILE = PROJECT_ROOT / "app" / "utils" / "_toggle_notification_sounds.py"

SAMPLE_RATE = 44100
PEAK = 24575  # 약 75% FS: 기존 soft 음원과 같은 크기
ATTACK_MS = 5.0
END_FADE_MS = 40.0

C4, E4, G4, A4, B4 = 261.63, 329.63, 392.00, 440.00, 493.88
C5, E5, G5, B5 = 523.25, 659.25, 783.99, 987.77

Partials = tuple[tuple[float, float], ...]  # (주파수, 상대 크기)


def chime(freq: float) -> Partials:
    return ((freq, 1.0), (freq * 2, 0.09))


def pair(low: float, high: float, gain: float = 0.72) -> Partials:
    return ((low, 1.0), (high, gain))


@dataclass(frozen=True)
class Note:
    onset_ms: float
    partials: Partials
    decay_ms: float  # 지수 감쇠 시정수


@dataclass(frozen=True)
class Sound:
    notes: tuple[Note, ...]
    total_ms: float


def two_note(
    first: Partials, second: Partials, onset_ms: float, total_ms: float, decay_ms: float
) -> Sound:
    return Sound(
        (Note(0.0, first, decay_ms), Note(onset_ms, second, decay_ms)), total_ms
    )


# 음 구성·시작 시점·길이는 기존 음원을 따른다.
CHIME_DECAY_MS = 110.0
TOGGLE_DECAY_MS = 60.0
WAV_SOUNDS: dict[str, Sound] = {
    "setA_start": two_note(chime(A4), chime(C5), 175, 355, CHIME_DECAY_MS),
    "setA_stop": two_note(chime(C5), chime(A4), 175, 375, CHIME_DECAY_MS),
    "setB_start": two_note(chime(E4), chime(C5), 165, 325, CHIME_DECAY_MS),
    "setB_stop": two_note(chime(C5), chime(E4), 165, 365, CHIME_DECAY_MS),
    "setC_start": two_note(pair(C4, E4), pair(G4, B4), 175, 355, CHIME_DECAY_MS),
    "setC_stop": two_note(pair(G4, B4), pair(C4, E4), 175, 375, CHIME_DECAY_MS),
}
TOGGLE_SOUNDS: dict[str, Sound] = {
    "SOFT_A_TOGGLE_ON": two_note(((E5, 1.0),), ((G5, 1.0),), 100, 190, TOGGLE_DECAY_MS),
    "SOFT_B_TOGGLE_ON": two_note(((B4, 1.0),), ((E5, 1.0),), 75, 145, TOGGLE_DECAY_MS),
    "SOFT_C_TOGGLE_ON": two_note(
        pair(C5, E5, 1.0), pair(G5, B5, 1.0), 100, 180, TOGGLE_DECAY_MS
    ),
}
PACK_CONSTANTS = {
    "_SOFT_A_START": "setA_start",
    "_SOFT_A_STOP": "setA_stop",
    "_SOFT_B_START": "setB_start",
    "_SOFT_B_STOP": "setB_stop",
    "_SOFT_C_START": "setC_start",
    "_SOFT_C_STOP": "setC_stop",
}


def render(sound: Sound) -> list[float]:
    frames = round(sound.total_ms * SAMPLE_RATE / 1000)
    out = [0.0] * frames
    attack = ATTACK_MS * SAMPLE_RATE / 1000
    for note in sound.notes:
        start = round(note.onset_ms * SAMPLE_RATE / 1000)
        decay = note.decay_ms * SAMPLE_RATE / 1000
        for n in range(frames - start):
            env = math.exp(-n / decay)
            if n < attack:
                env *= 0.5 - 0.5 * math.cos(math.pi * n / attack)
            t = n / SAMPLE_RATE
            out[start + n] += env * sum(
                gain * math.sin(2 * math.pi * freq * t) for freq, gain in note.partials
            )
    fade = round(END_FADE_MS * SAMPLE_RATE / 1000)
    for i in range(fade):
        out[frames - fade + i] *= 0.5 + 0.5 * math.cos(math.pi * (i + 1) / fade)
    return out


def to_wav(samples: list[float]) -> bytes:
    scale = PEAK / max(abs(v) for v in samples)
    pcm = array.array("h")
    for v in samples:
        value = round(v * scale)
        pcm.extend((value, value))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def replace_constants(path: Path, values: dict[str, str]) -> None:
    # 줄바꿈(CRLF/LF)을 그대로 두기 위해 bytes로 읽고 쓴다.
    text = path.read_bytes().decode("utf-8")
    for name, value in values.items():
        text, count = re.subn(
            rf'^{name} = "[^"]*"', f'{name} = "{value}"', text, flags=re.MULTILINE
        )
        if count != 1:
            raise SystemExit(f"{path.name}: {name} 상수를 찾지 못함")
    path.write_bytes(text.encode("utf-8"))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def main() -> None:
    wavs = {name: to_wav(render(sound)) for name, sound in WAV_SOUNDS.items()}
    for name, data in wavs.items():
        (SAMPLES_DIR / f"{name}.wav").write_bytes(data)
    replace_constants(
        PACKS_FILE, {const: b64(wavs[name]) for const, name in PACK_CONSTANTS.items()}
    )
    replace_constants(
        TOGGLE_FILE,
        {name: b64(to_wav(render(sound))) for name, sound in TOGGLE_SOUNDS.items()},
    )
    print(f"generated {len(wavs)} WAV + {len(TOGGLE_SOUNDS)} toggle sounds")


if __name__ == "__main__":
    main()
