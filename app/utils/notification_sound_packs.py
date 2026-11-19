"""Notification sound pack catalog (start/stop pairs).

Packs:
  - classic: original app start/stop tones (MP3 base64)
  - soft_a / soft_b / soft_c: soft preview sets (WAV base64)

WAV sources live under samples/notification-preview/ (peak-normalized so
loudness is closer to classic at the same system volume).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.utils._classic_notification_sounds import CLASSIC_START_SOUND, CLASSIC_STOP_SOUND
from app.utils._soft_notification_sounds import (
    SOFT_A_START,
    SOFT_A_STOP,
    SOFT_B_START,
    SOFT_B_STOP,
    SOFT_C_START,
    SOFT_C_STOP,
)
from app.utils._toggle_notification_sounds import (
    SOFT_A_TOGGLE_OFF,
    SOFT_A_TOGGLE_ON,
    SOFT_B_TOGGLE_OFF,
    SOFT_B_TOGGLE_ON,
    SOFT_C_TOGGLE_OFF,
    SOFT_C_TOGGLE_ON,
)
from app.utils.sound_assets import (
    RUNTIME_TOGGLE_OFF_SOUND,
    RUNTIME_TOGGLE_ON_SOUND,
)

DEFAULT_NOTIFICATION_SOUND_PACK = "classic"


@dataclass(frozen=True)
class NotificationSoundPack:
    pack_id: str
    start_b64: str
    stop_b64: str
    on_b64: str
    off_b64: str
    label_en: str
    label_ko: str


NOTIFICATION_SOUND_PACKS: dict[str, NotificationSoundPack] = {
    "classic": NotificationSoundPack(
        pack_id="classic",
        start_b64=CLASSIC_START_SOUND,
        stop_b64=CLASSIC_STOP_SOUND,
        on_b64=RUNTIME_TOGGLE_ON_SOUND,
        off_b64=RUNTIME_TOGGLE_OFF_SOUND,
        label_en="Classic",
        label_ko="클래식",
    ),
    "soft_a": NotificationSoundPack(
        pack_id="soft_a",
        start_b64=SOFT_A_START,
        stop_b64=SOFT_A_STOP,
        on_b64=SOFT_A_TOGGLE_ON,
        off_b64=SOFT_A_TOGGLE_OFF,
        label_en="Soft A (Chime)",
        label_ko="소프트 A (차임)",
    ),
    "soft_b": NotificationSoundPack(
        pack_id="soft_b",
        start_b64=SOFT_B_START,
        stop_b64=SOFT_B_STOP,
        on_b64=SOFT_B_TOGGLE_ON,
        off_b64=SOFT_B_TOGGLE_OFF,
        label_en="Soft B (Minimal)",
        label_ko="소프트 B (미니멀)",
    ),
    "soft_c": NotificationSoundPack(
        pack_id="soft_c",
        start_b64=SOFT_C_START,
        stop_b64=SOFT_C_STOP,
        on_b64=SOFT_C_TOGGLE_ON,
        off_b64=SOFT_C_TOGGLE_OFF,
        label_en="Soft C (Chord)",
        label_ko="소프트 C (코드)",
    ),
}


def normalize_notification_sound_pack(value: object) -> str:
    """Return a known pack id; unknown/empty values fall back to classic."""
    if not isinstance(value, str):
        return DEFAULT_NOTIFICATION_SOUND_PACK
    pack_id = value.strip().lower()
    if pack_id in NOTIFICATION_SOUND_PACKS:
        return pack_id
    return DEFAULT_NOTIFICATION_SOUND_PACK


def get_notification_sound_pack(pack_id: str | None) -> NotificationSoundPack:
    return NOTIFICATION_SOUND_PACKS[normalize_notification_sound_pack(pack_id)]


def notification_sound_pack_choices() -> list[NotificationSoundPack]:
    # Stable order: classic first, then soft_a/b/c
    order = ("classic", "soft_a", "soft_b", "soft_c")
    return [NOTIFICATION_SOUND_PACKS[k] for k in order]
