"""설정 창의 상태·검증·저장. UI 툴킷과 무관하다.

저장 순서: 키 검증 → 숫자 검증 → 알림음 값 반영 → 저장. 초기화는 화면 값만 기본값으로 바꾸고 저장하지 않는다.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from loguru import logger

from app.domain.models import UserSettings
from app.domain.validation import settings_number_entry_valid, start_stop_key_valid
from app.storage.settings_storage import (
    USER_SETTINGS_PATH,
    load_user_settings,
    save_user_settings,
)
from app.utils.i18n import normalize_language, set_language, txt
from app.utils.notification_sound_packs import normalize_notification_sound_pack

SettingsSection = Literal["keys", "language", "timing", "sound"]

TIMING_PREFIXES = ("key_pressed_time", "delay_between_loop")
TIMING_FIELDS = tuple(f"{p}_{s}" for p in TIMING_PREFIXES for s in ("min", "max"))
TIMING_MIN_MS = 50
TIMING_MAX_MS = 500
_UNSET_START_STOP_KEYS = ("", "DISABLED")


@dataclass(frozen=True)
class FormError:
    section: SettingsSection
    message: str


@dataclass(frozen=True)
class SaveResult:
    settings: UserSettings
    language_changed: bool


class SettingsForm:
    """편집 중인 설정 사본. `submit()` 전에는 파일을 건드리지 않는다."""

    def __init__(
        self,
        settings: UserSettings,
        *,
        is_windows: bool | None = None,
        path: Path = USER_SETTINGS_PATH,
    ) -> None:
        self.path = path
        self.is_windows = (
            platform.system() == "Windows" if is_windows is None else is_windows
        )
        self.saved_language = normalize_language(settings.language)
        self.settings = replace(settings, language=self.saved_language)
        self.timing: dict[str, str] = {}
        self._sync_timing_text()

    @classmethod
    def load(
        cls, path: Path = USER_SETTINGS_PATH, *, is_windows: bool | None = None
    ) -> SettingsForm:
        """창을 열 때마다 파일을 다시 읽는다(Tk `_load_settings`)."""
        settings, _can_save = load_user_settings(path)
        set_language(settings.language)
        return cls(settings, is_windows=is_windows, path=path)

    # ── start/stop key ────────────────────────────────────────────────

    @property
    def key_capture_enabled(self) -> bool:
        """키 칸이 입력을 받는지. Windows는 Alt+Shift가 꺼졌을 때, 그 외는
        Option+Shift 단축키가 켜졌을 때."""
        if self.is_windows:
            return not self.settings.use_alt_shift_hotkey
        return self.settings.toggle_start_stop_mac

    def set_use_alt_shift(self, enabled: bool) -> None:
        self.settings.use_alt_shift_hotkey = enabled

    def set_mac_hotkey_enabled(self, enabled: bool) -> None:
        """Tk `_toggle_combo_state`: 켜면 DISABLED를 기본 키로, 끄면 DISABLED로."""
        self.settings.toggle_start_stop_mac = enabled
        if not enabled:
            self.settings.start_stop_key = "DISABLED"
        elif self.settings.start_stop_key == "DISABLED":
            self.settings.start_stop_key = UserSettings().start_stop_key

    def capture_key(self, key: str) -> bool:
        """눌린 키 이름을 시작/중지 키로 받는다. 받으면 True."""
        if not self.key_capture_enabled:
            return False
        key = key.upper()
        if not start_stop_key_valid(key):
            return False
        self.settings.start_stop_key = key
        return True

    @property
    def start_stop_key_display(self) -> str:
        """키 칸에 보일 값. 지정되지 않았으면 빈 문자열."""
        key = self.settings.start_stop_key
        return "" if key in _UNSET_START_STOP_KEYS else key

    # ── timing ────────────────────────────────────────────────────────

    @staticmethod
    def timing_text_valid(text: str) -> bool:
        """입력 중 숫자 칸 검증(빈 값 또는 앞자리 0 없는 0~999)."""
        return settings_number_entry_valid(text)

    def set_timing(self, name: str, text: str) -> bool:
        if name not in TIMING_FIELDS or not self.timing_text_valid(text):
            return False
        self.timing[name] = text
        return True

    def _sync_timing_text(self) -> None:
        self.timing = {name: str(getattr(self.settings, name)) for name in TIMING_FIELDS}

    # ── reset / submit ────────────────────────────────────────────────

    def reset(self) -> None:
        """화면 값만 기본값으로 바꾼다. 저장은 `submit()`에서만 한다."""
        self.settings = UserSettings()
        self._sync_timing_text()

    def validate(self) -> tuple[FormError | None, UserSettings]:
        """검증하고, 통과하면 저장할 설정을 돌려준다."""
        candidate = replace(self.settings)
        candidate.language = normalize_language(candidate.language)
        missing_key = candidate.start_stop_key in _UNSET_START_STOP_KEYS
        if self.is_windows:
            needs_key = not candidate.use_alt_shift_hotkey
        else:
            needs_key = candidate.toggle_start_stop_mac
        if needs_key and missing_key:
            return (
                FormError(
                    "keys",
                    txt("Please select a Start/Stop key.", "시작/중지 키를 선택하세요."),
                ),
                candidate,
            )
        try:
            for prefix in TIMING_PREFIXES:
                mn = int(self.timing[f"{prefix}_min"] or 0)
                mx = int(self.timing[f"{prefix}_max"] or 0)
                if mn >= mx:
                    return (
                        FormError(
                            "timing",
                            txt(
                                "Min must be less than Max.",
                                "최소값은 최대값보다 작아야 합니다.",
                            ),
                        ),
                        candidate,
                    )
                if not (TIMING_MIN_MS <= mn and mx <= TIMING_MAX_MS):
                    return (
                        FormError(
                            "timing",
                            txt(
                                "Values must be between 50 and 500.",
                                "값은 50~500 범위여야 합니다.",
                            ),
                        ),
                        candidate,
                    )
                setattr(candidate, f"{prefix}_min", mn)
                setattr(candidate, f"{prefix}_max", mx)
        except ValueError:
            return (
                FormError(
                    "timing",
                    txt("Invalid numeric input.", "숫자 입력이 올바르지 않습니다."),
                ),
                candidate,
            )
        candidate.notification_sound_pack = normalize_notification_sound_pack(
            candidate.notification_sound_pack
        )
        candidate.runtime_toggle_sound_pack = normalize_notification_sound_pack(
            candidate.runtime_toggle_sound_pack
        )
        candidate.runtime_toggle_sound_enabled = bool(
            candidate.runtime_toggle_sound_enabled
        )
        return None, candidate

    def submit(self) -> FormError | SaveResult:
        """검증을 통과하면 언어를 적용하고 저장한다. 저장 실패는 Tk와 같이
        기록만 하고 창은 닫히게 둔다."""
        error, candidate = self.validate()
        if error is not None:
            return error
        language_changed = candidate.language != self.saved_language
        set_language(candidate.language)
        self.settings = candidate
        self._sync_timing_text()
        try:
            save_user_settings(candidate, self.path)
            logger.debug(f"Saved: {candidate}")
        except Exception as e:
            logger.error(f"Save failed: {e}")
        return SaveResult(candidate, language_changed)
