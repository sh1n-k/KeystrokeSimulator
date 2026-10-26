"""실행 창의 상태와 동작. UI 툴킷과 무관하다.

고른 대상·실행·수정키 세트로 준비 상태를 판정하고, 시작/중지와 단축키 묶음
켜고 끄기, 전역 입력 리스너 구성을 맡는다. 화면 갱신·HUD 닫기·창 위치는
`RunHost`가 맡는다.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NotRequired, Protocol, TypedDict, cast

import pynput.keyboard
import pynput.mouse
from loguru import logger

from app.domain.models import EventModel, ProfileModel, UserSettings
from app.domain.run_composition import ComposedRunSession, compose_run_session
from app.domain.runtime_toggle import (
    MOUSE_BUTTON_3_TRIGGER,
    MOUSE_BUTTON_4_TRIGGER,
    RUNTIME_TOGGLE_DEBOUNCE_SECONDS,
    RUNTIME_TOGGLE_SCROLL_GESTURE_SECONDS,
    WHEEL_DOWN_TRIGGER,
    WHEEL_UP_TRIGGER,
    display_runtime_toggle_trigger,
    is_keyboard_runtime_toggle_trigger,
    is_mouse_button_runtime_toggle_trigger,
    is_wheel_runtime_toggle_trigger,
    normalize_runtime_toggle_listener_key,
    normalize_runtime_toggle_trigger,
    runtime_toggle_member_count,
)
from app.engine.processor import KeystrokeProcessor
from app.platform.input_router import InputListener, InputRouter
from app.platform.mac_hotkey_tap import MacHotkeyTapListener
from app.platform.mac_key_poll import MacKeyPollListener
from app.platform.system import PermissionUtils, ProcessUtils
from app.storage.app_state import StateUtils
from app.storage.modkey_sets_storage import (
    DEFAULT_MODKEY_SET_NAME,
    default_modification_keys,
    get_modkey_set,
)
from app.storage.profile_storage import list_profile_names, load_profile
from app.storage.run_sets_storage import (
    CURRENT_RUN_SET_ID,
    get_run_set,
    is_current_run_set,
    upsert_run_set,
)
from app.storage.settings_storage import load_user_settings, save_user_settings
from app.utils.i18n import normalize_language, set_language, txt
from app.utils.sounds import SoundPlayer

# macOS Option+Shift: prefer CGEventTap (consume + CFRunLoop); poll is fallback.
MAC_POLL_INTERVAL_MS = 10
MAC_ALT_SHIFT_DEBOUNCE_SECONDS = 0.2
# Poll-only hold filter (tap fires on chord rising edge, no hold delay).
MAC_ALT_SHIFT_HOLD_SECONDS = 0.015
SETTINGS_FILE = Path("user_settings.json")

StatusTone = Literal["ready", "warn", "error"]
StatusAction = Literal["permissions", "process", "workspace"]


class Readiness(TypedDict):
    can_start: bool
    badge_text: str
    title: str
    detail: str
    tone: StatusTone
    missing_permissions: NotRequired[list[str]]
    # One-line status text and the single fix action shown when blocked.
    summary: NotRequired[str]
    action: NotRequired[StatusAction]


@dataclass(frozen=True)
class RunSelection:
    process: str = ""
    profile: str = ""
    run_set: str = CURRENT_RUN_SET_ID
    modkey_set: str = DEFAULT_MODKEY_SET_NAME


class RunHost(Protocol):
    """컨트롤러가 UI에 요청하는 일."""

    def selection(self) -> RunSelection: ...
    def on_run_state_changed(self) -> None: ...
    def on_status_changed(self) -> None: ...
    def before_start(self) -> None: ...
    def defer(self, action: Callable[[], None]) -> None: ...
    def window_position(self) -> str | None: ...
    def is_alive(self) -> bool: ...


def safe_call[**P, R](
    func: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R | None:
    """예외를 무시하고 함수 호출"""
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


def selected_process_pid(process: str) -> int | None:
    pid_match = re.search(r"\((\d+)\)", process)
    return int(pid_match.group(1)) if pid_match else None


def runnable_events(events: list[EventModel]) -> list[EventModel]:
    return [
        evt
        for evt in events
        if getattr(evt, "use_event", True)
        and (getattr(evt, "key_to_enter", None) or not getattr(evt, "execute_action", True))
    ]


def events_with_processor_inputs(events: list[EventModel]) -> list[EventModel]:
    ready: list[EventModel] = []
    for evt in events:
        if evt.is_screenless_input():
            ready.append(evt)
            continue
        if evt.latest_position is None or evt.clicked_position is None:
            continue
        mode = evt.match_mode or "pixel"
        if mode == "pixel" and (
            evt.ref_pixel_value is None or len(evt.ref_pixel_value) < 3
        ):
            continue
        if mode == "region" and evt.held_screenshot is None:
            continue
        ready.append(evt)
    return ready


def legacy_run_profiles(state: dict[str, object]) -> list[str]:
    """Earlier multi-select UI stored a run_profiles list instead of a set."""
    raw = state.get("run_profiles")
    if isinstance(raw, list):
        return [
            str(item)
            for item in cast(list[object], raw)
            if isinstance(item, str) and item
        ]
    if isinstance(raw, str) and raw:
        return [raw]
    return []


def migrate_legacy_run_profiles(
    state: dict[str, object], existing_set_names: list[str], run_sets_path: Path
) -> str | None:
    """Save a legacy 2+ profile run list as a named set. Returns the set name."""
    run_profiles = legacy_run_profiles(state)
    if len(run_profiles) < 2:
        return None
    migrated = "Migrated"
    try:
        # Avoid clobbering an existing user set name if present.
        existing = set(existing_set_names)
        name = migrated
        n = 2
        while name in existing:
            name = f"{migrated} {n}"
            n += 1
        upsert_run_set(name, run_profiles, run_sets_path)
        return name
    except Exception as exc:
        logger.warning(f"Legacy run profile migration failed: {exc}")
        return None


class RunController:
    def __init__(
        self,
        host: RunHost,
        *,
        router: InputRouter,
        sound_player: SoundPlayer,
        profiles_dir: Path,
        modkey_sets_path: Path,
        run_sets_path: Path,
        settings_path: Path = SETTINGS_FILE,
    ) -> None:
        self.host = host
        self.router = router
        self.sound_player = sound_player
        self.profiles_dir = profiles_dir
        self.modkey_sets_path = modkey_sets_path
        self.run_sets_path = run_sets_path
        self.settings_path = settings_path
        self.settings: UserSettings = UserSettings()
        self.is_running = False
        self.keystroke_processor: KeystrokeProcessor | None = None
        self.terminate_event = threading.Event()

        self.start_stop_mouse_listener: InputListener | None = None
        self.runtime_toggle_mouse_listener: InputListener | None = None
        self.keyboard_listener: InputListener | None = None
        self.alt_pressed = False
        self.shift_pressed = False
        self.last_alt_shift_toggle_time = 0.0
        self.ctrl_check_active = False
        self._mac_hotkey_tap_listener: MacHotkeyTapListener | None = None
        self._mac_key_poll_listener: MacKeyPollListener | None = None
        self.latest_scroll_time: float | None = None
        self.runtime_toggle_enabled = False
        self.runtime_toggle_key: str | None = None
        self.runtime_toggle_active = False
        self.runtime_toggle_member_count = 0
        self.last_runtime_toggle_time = 0.0
        self.latest_runtime_scroll_time: float | None = None
        self.toggle_transition_in_progress = False
        self._pending_start_stop_toggle = False

    # ── settings and selection ─────────────────────────────────────────

    def load_settings(self) -> None:
        self.settings, can_save_settings = load_user_settings(self.settings_path)
        self.settings.language = normalize_language(self.settings.language)
        set_language(self.settings.language)
        if can_save_settings:
            save_user_settings(self.settings, self.settings_path)
        safe_call(
            self.sound_player.set_notification_pack,
            self.settings.notification_sound_pack,
        )
        safe_call(
            self.sound_player.set_runtime_toggle_pack,
            self.settings.runtime_toggle_sound_pack,
        )

    def run_profile_names(self) -> list[str]:
        """Members of the chosen run set, else the chosen profile."""
        sel = self.host.selection()
        set_id = (sel.run_set or "").strip()
        if set_id and not is_current_run_set(set_id):
            available = set(list_profile_names(self.profiles_dir))
            names = [n for n in get_run_set(set_id, self.run_sets_path) if n in available]
            if names:
                return names
        return [sel.profile] if sel.profile else []

    def _target_process_is_active(self) -> bool:
        return ProcessUtils.is_process_active(
            selected_process_pid(self.host.selection().process)
        )

    def run_set_status_label(self) -> str:
        """Short label for status lines: the profile, or the named set."""
        sel = self.host.selection()
        set_id = (sel.run_set or "").strip()
        if set_id and not is_current_run_set(set_id):
            return txt("Set {name}", "세트 {name}", name=set_id)
        return (sel.profile or "—").strip() or "—"

    def run_target_label(self, profile_names: list[str] | None = None) -> str:
        """"BM_야수" 또는 "세트 레이드 (프로필 2개)"."""
        target = self.run_set_status_label()
        members = self.run_set_members_status_label(profile_names)
        return target if members in ("—", target) else f"{target} ({members})"

    def run_set_members_status_label(
        self, profile_names: list[str] | None = None
    ) -> str:
        """Compact member summary: profile name, count, or em dash."""
        names = profile_names
        if names is None:
            names = self.run_profile_names()
        cleaned = [n for n in names if n]
        if not cleaned:
            return "—"
        if len(cleaned) == 1:
            return cleaned[0]
        return txt("{count} profiles", "프로필 {count}개", count=len(cleaned))

    def status_detail_with_selection(self, detail: str) -> str:
        """Append the run target + modkey set when not already present."""
        sel = self.host.selection()
        profile_name = (sel.profile or "").strip()
        modkey_set_name = (sel.modkey_set or "").strip()
        if not profile_name and not modkey_set_name:
            return detail
        if "Modifier keys " in detail or "수정키 " in detail:
            return detail
        line = txt(
            "Run {target} · Modifier keys {modkey_set}",
            "실행 {target} · 수정키 {modkey_set}",
            target=self.run_target_label(),
            modkey_set=modkey_set_name or "—",
        )
        return f"{detail}\n{line}" if detail else line

    # ── composing a run ────────────────────────────────────────────────

    def load_profiles_for_run(
        self, names: list[str], *, migrate: bool
    ) -> tuple[list[tuple[str, ProfileModel]], list[str]]:
        loaded: list[tuple[str, ProfileModel]] = []
        load_errors: list[str] = []
        profiles_dir = Path(self.profiles_dir)
        for name in names:
            jpath = profiles_dir / f"{name}.json"
            # When the file is on disk, fail closed on corrupt/non-object JSON so a
            # broken run-set member is not silently treated as an empty profile.
            # (Unit tests that mock load_profile without files skip this gate.)
            if jpath.is_file():
                try:
                    raw: object = json.loads(jpath.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict):
                        raise ValueError(
                            f"Profile root must be an object, got {type(raw).__name__}"
                        )
                except Exception as exc:
                    load_errors.append(
                        txt(
                            "Profile '{profile}' could not be loaded: {error}",
                            "프로필 '{profile}'을(를) 불러오지 못했습니다: {error}",
                            profile=name,
                            error=exc,
                        )
                    )
                    continue
            try:
                profile = load_profile(profiles_dir, name, migrate=migrate)
            except Exception as exc:
                load_errors.append(
                    txt(
                        "Profile '{profile}' could not be loaded: {error}",
                        "프로필 '{profile}'을(를) 불러오지 못했습니다: {error}",
                        profile=name,
                        error=exc,
                    )
                )
                continue
            loaded.append((name, profile))
        return loaded, load_errors

    def compose_selected_run(
        self, *, migrate: bool
    ) -> tuple[ComposedRunSession | None, list[str]]:
        names = self.run_profile_names()
        if not names:
            return None, [
                txt(
                    "Select at least one profile to run.",
                    "실행할 프로필을 하나 이상 선택하세요.",
                )
            ]
        loaded, load_errors = self.load_profiles_for_run(names, migrate=migrate)
        if load_errors and not loaded:
            return None, load_errors
        if not loaded:
            return None, load_errors or [
                txt(
                    "Select at least one profile to run.",
                    "실행할 프로필을 하나 이상 선택하세요.",
                )
            ]
        session = compose_run_session(
            loaded, settings=self.settings, os_name=platform.system()
        )
        errors = list(load_errors) + list(session.errors)
        if errors:
            return session, errors
        return session, []

    # ── readiness / status text ────────────────────────────────────────

    def readiness(self) -> Readiness:
        if self.is_running:
            detail = txt(
                "Stop to change the target, run or modifier keys. Workspace edits apply from the next start.",
                "대상·실행·수정키를 바꾸려면 중지하세요. 작업 공간 편집은 다음 시작부터 반영됩니다.",
            )
            summary = self.run_target_label()
            if self.runtime_toggle_enabled and self.runtime_toggle_key:
                summary = txt(
                    "{target} · hotkey set {trigger} ({state})",
                    "{target} · 단축키 묶음 {trigger} ({state})",
                    target=summary,
                    trigger=display_runtime_toggle_trigger(self.runtime_toggle_key),
                    state=txt("ON", "켜짐")
                    if self.runtime_toggle_active
                    else txt("OFF", "꺼짐"),
                )
            return {
                "can_start": True,
                "badge_text": txt("Running", "실행 중"),
                "title": txt(
                    "Simulation is active for the selected target.",
                    "선택한 대상에 대해 시뮬레이션이 실행 중입니다.",
                ),
                "summary": summary,
                "detail": detail,
                "tone": "ready",
            }

        process = self.host.selection().process
        if not process or "(" not in process:
            return {
                "can_start": False,
                "badge_text": txt("Select Process", "프로세스 선택"),
                "title": txt(
                    "Choose the target app before starting.",
                    "시작하기 전에 대상 앱을 선택하세요.",
                ),
                "detail": txt(
                    "Pick the process you want to watch in the Target list.",
                    "감시할 대상을 대상 목록에서 고르세요.",
                ),
                "tone": "warn",
                "action": "process",
            }

        run_names = self.run_profile_names()
        if not run_names:
            return {
                "can_start": False,
                "badge_text": txt("Select Profile", "프로필 선택"),
                "title": txt(
                    "Select one or more profiles to run.",
                    "실행할 프로필을 하나 이상 선택하세요.",
                ),
                "detail": txt(
                    "Choose a profile or a run set in the Run list.",
                    "실행 목록에서 프로필이나 실행 세트를 고르세요.",
                ),
                "tone": "warn",
                "action": "workspace",
            }

        session, compose_errors = self.compose_selected_run(migrate=False)
        if compose_errors:
            first = compose_errors[0]
            badge = txt("Profile Error", "프로필 오류")
            title = txt(
                "The run set could not be prepared.",
                "실행 세트를 준비하지 못했습니다.",
            )
            lower = first.lower()
            if "duplicate" in lower or "중복" in first:
                badge = txt("Duplicate Events", "중복 이벤트")
                title = txt(
                    "Duplicate event names were found in a run profile.",
                    "실행 프로필에서 중복 이벤트 이름이 발견되었습니다.",
                )
            elif (
                "on/off hotkey" in lower
                or "hotkey set" in lower
                or "켜고 끄는 단축키" in first
                or "단축키 묶음" in first
            ):
                badge = txt("Hotkey Conflict", "단축키 충돌")
                title = txt(
                    "On/off hotkey settings need attention.",
                    "켜고 끄는 단축키 설정을 확인해야 합니다.",
                )
            return {
                "can_start": False,
                "badge_text": badge,
                "title": title,
                "detail": first,
                "tone": "error",
                "action": "workspace",
            }

        assert session is not None
        events = list(session.events)
        runnable = runnable_events(events)
        enabled_count = sum(1 for evt in events if getattr(evt, "use_event", True))
        runnable_count = len(runnable)

        if not events:
            return {
                "can_start": False,
                "badge_text": txt("Add Events", "이벤트 추가"),
                "title": txt("Nothing to run yet.", "실행할 이벤트가 아직 없습니다."),
                "detail": txt(
                    "Add at least one event in the workspace or with Quick events.",
                    "작업 공간이나 빠른 이벤트에서 이벤트를 하나 이상 추가하세요.",
                ),
                "tone": "warn",
                "action": "workspace",
            }

        if enabled_count == 0:
            return {
                "can_start": False,
                "badge_text": txt("Enable Event", "이벤트 활성화"),
                "title": txt("Every event is turned off.", "모든 이벤트가 꺼져 있습니다."),
                "detail": txt(
                    "Turn on at least one event in the workspace before starting.",
                    "시작하기 전에 작업 공간에서 이벤트를 하나 이상 켜세요.",
                ),
                "tone": "warn",
                "action": "workspace",
            }

        if runnable_count == 0:
            return {
                "can_start": False,
                "badge_text": txt("Check Events", "이벤트 확인"),
                "title": txt(
                    "Rules in use have no input key.",
                    "사용 중인 규칙에 키가 없습니다.",
                ),
                "detail": txt(
                    "Open the workspace and set a key for rules marked 'no key'.",
                    "작업 공간에서 '키 없음' 규칙에 키를 지정하세요.",
                ),
                "tone": "warn",
                "action": "workspace",
            }

        missing_permissions = PermissionUtils.missing_macos_permissions()
        if missing_permissions:
            missing_labels: list[str] = []
            if "screen" in missing_permissions:
                missing_labels.append(txt("Screen Recording", "화면 기록"))
            if "accessibility" in missing_permissions:
                missing_labels.append(txt("Accessibility", "손쉬운 사용"))
            return {
                "can_start": False,
                "badge_text": txt("Permissions", "권한 필요"),
                "summary": ", ".join(missing_labels),
                "title": txt(
                    "macOS permissions are blocking capture or key control.",
                    "macOS 권한 부족으로 캡처 또는 키 제어가 차단되고 있습니다.",
                ),
                "detail": txt(
                    "Grant {missing} to this executable, then restart the app.\nExecutable: {path}",
                    "이 실행 파일에 {missing} 권한을 부여한 뒤 앱을 다시 실행하세요.\n실행 파일: {path}",
                    missing=", ".join(missing_labels),
                    path=sys.executable,
                ),
                "tone": "error",
                "missing_permissions": missing_permissions,
                "action": "permissions",
            }

        if not events_with_processor_inputs(runnable):
            return {
                "can_start": False,
                "badge_text": txt("Check Events", "이벤트 확인"),
                "title": txt(
                    "Enabled events need captured coordinates and reference data.",
                    "활성 이벤트에는 캡처 좌표와 기준 데이터가 필요합니다.",
                ),
                "detail": txt(
                    "Open the workspace and capture a screen for events missing one.",
                    "작업 공간에서 화면이 빠진 이벤트를 다시 캡처하세요.",
                ),
                "tone": "warn",
                "action": "workspace",
            }

        target_label = self.run_target_label(list(session.profile_names))
        modkey_set_name = self.host.selection().modkey_set or DEFAULT_MODKEY_SET_NAME
        rules = sum(1 for evt in runnable if evt.execute_action)
        signals = len(runnable) - rules
        return {
            "can_start": True,
            "badge_text": txt("Ready", "준비됨"),
            "title": txt(
                "Everything is ready to start monitoring.",
                "모니터링을 시작할 준비가 끝났습니다.",
            ),
            "summary": txt(
                "rules {rules} · signals {signals}",
                "규칙 {rules} · 신호 {signals}",
                rules=rules,
                signals=signals,
            ),
            "detail": txt(
                "Run {target} · Modifier keys {modkey_set} · {count} event(s).",
                "실행 {target} · 수정키 {modkey_set} · 이벤트 {count}개.",
                target=target_label,
                modkey_set=modkey_set_name,
                count=runnable_count,
            ),
            "tone": "ready",
        }

    def hotkey_hint_text(self) -> str:
        if platform.system() == "Darwin" and self.settings.toggle_start_stop_mac:
            trigger = txt("Alt + Shift", "Alt + Shift")
        elif platform.system() == "Windows" and self.settings.use_alt_shift_hotkey:
            trigger = txt("Alt + Shift", "Alt + Shift")
        elif self.settings.start_stop_key == "DISABLED":
            return txt(
                "Start/stop hotkey is disabled. Use the Start button.",
                "시작/중지 단축키가 꺼져 있습니다. 시작 버튼을 사용하세요.",
            )
        elif self.settings.start_stop_key == "W_UP":
            trigger = txt("Mouse wheel up", "마우스 휠 위")
        elif self.settings.start_stop_key == "W_DN":
            trigger = txt("Mouse wheel down", "마우스 휠 아래")
        else:
            trigger = self.settings.start_stop_key

        hint = txt(
            "Start or stop with {trigger}.",
            "{trigger}(으)로 시작 또는 중지할 수 있습니다.",
            trigger=trigger,
        )
        if self.runtime_toggle_enabled and self.runtime_toggle_key:
            toggle_state = (
                txt("ON", "켜짐") if self.runtime_toggle_active else txt("OFF", "꺼짐")
            )
            hint = txt(
                "{base}\nHotkey set: {trigger} ({state})",
                "{base}\n단축키 묶음: {trigger} ({state})",
                base=hint,
                trigger=display_runtime_toggle_trigger(self.runtime_toggle_key),
                state=toggle_state,
            )
        return hint

    def hotkey_short(self) -> str:
        """시작 버튼에 붙이는 짧은 단축키 표시. 꺼져 있으면 빈 문자열."""
        settings = self.settings
        if platform.system() == "Darwin" and settings.toggle_start_stop_mac:
            return "⌥⇧"
        if platform.system() == "Windows" and settings.use_alt_shift_hotkey:
            return "Alt+Shift"
        key = str(settings.start_stop_key or "")
        if key == "DISABLED":
            return ""
        wheel = {"W_UP": txt("wheel ↑", "휠 ↑"), "W_DN": txt("wheel ↓", "휠 ↓")}
        return wheel.get(key, key)

    @staticmethod
    def run_dock_text(running: bool) -> str:
        """상태 줄과 겹치지 않게, 실행 중 멈추는 방법만 알린다."""
        if running:
            return txt(
                "Press the hotkey or Stop to halt.",
                "단축키나 중지로 멈춥니다.",
            )
        return ""

    # ── runtime toggle session ─────────────────────────────────────────

    def reset_runtime_toggle_session(self) -> None:
        self.runtime_toggle_enabled = False
        self.runtime_toggle_key = None
        self.runtime_toggle_active = False
        self.runtime_toggle_member_count = 0
        self.latest_runtime_scroll_time = None

    def configure_runtime_toggle_session(
        self,
        *,
        enabled: bool,
        toggle_key: str | None,
        events: list[EventModel],
    ) -> None:
        self.reset_runtime_toggle_session()
        key = normalize_runtime_toggle_trigger(toggle_key)
        member_count = runtime_toggle_member_count(events)
        self.runtime_toggle_enabled = bool(enabled and key and member_count > 0)
        self.runtime_toggle_key = key if self.runtime_toggle_enabled else None
        self.runtime_toggle_member_count = (
            member_count if self.runtime_toggle_enabled else 0
        )

    # ── global input listeners ─────────────────────────────────────────

    def setup_event_handlers(self) -> None:
        self.unbind_events()
        self.router.start()

        runtime_toggle_trigger = normalize_runtime_toggle_trigger(
            self.runtime_toggle_key
        )
        use_mac_hotkeys = platform.system() == "Darwin" and (
            self.settings.toggle_start_stop_mac
            or (
                self.runtime_toggle_enabled
                and is_keyboard_runtime_toggle_trigger(runtime_toggle_trigger)
            )
        )
        if use_mac_hotkeys:
            self._start_mac_hotkeys()

        key = self.settings.start_stop_key
        if key.startswith("W_"):
            self.start_stop_mouse_listener = cast(
                InputListener,
                pynput.mouse.Listener(
                    on_scroll=lambda x, y, dx, dy: self.router.post(
                        lambda: self.on_mouse_scroll(x, y, dx, dy)
                    )
                ),
            )
            self.router.add(self.start_stop_mouse_listener)

        if self.runtime_toggle_enabled and (
            is_wheel_runtime_toggle_trigger(runtime_toggle_trigger)
            or is_mouse_button_runtime_toggle_trigger(runtime_toggle_trigger)
        ):
            self.runtime_toggle_mouse_listener = cast(
                InputListener,
                pynput.mouse.Listener(
                    on_scroll=lambda x, y, dx, dy: self.router.post(
                        lambda: self.on_runtime_toggle_mouse_scroll(x, y, dx, dy)
                    ),
                    on_click=lambda x, y, button, pressed: self.router.post(
                        lambda: self.on_runtime_toggle_mouse_click(
                            x, y, button, pressed
                        )
                    ),
                ),
            )
            self.router.add(self.runtime_toggle_mouse_listener)

        should_listen_keyboard = (
            (
                self.runtime_toggle_enabled
                and is_keyboard_runtime_toggle_trigger(runtime_toggle_trigger)
            )
            or (platform.system() == "Windows" and self.settings.use_alt_shift_hotkey)
            or (key != "DISABLED" and not key.startswith("W_"))
        )
        if should_listen_keyboard and not use_mac_hotkeys:
            self.keyboard_listener = cast(
                InputListener,
                pynput.keyboard.Listener(
                    on_press=lambda key: self.router.post(
                        lambda: self.on_key_press(key)
                    ),
                    on_release=lambda key: self.router.post(
                        lambda: self.on_key_release(key)
                    ),
                ),
            )
            self.router.add(self.keyboard_listener)

    def unbind_events(self) -> None:
        self.router.stop()
        self.keyboard_listener = None
        self.start_stop_mouse_listener = None
        self.runtime_toggle_mouse_listener = None

        self.ctrl_check_active = False
        self._mac_hotkey_tap_listener = None
        self._mac_key_poll_listener = None

    def on_key_press(self, key: object) -> None:
        now = time.time()
        if key in (pynput.keyboard.Key.alt_l, pynput.keyboard.Key.alt_r):
            self.alt_pressed = True
        if key in (pynput.keyboard.Key.shift_l, pynput.keyboard.Key.shift_r):
            self.shift_pressed = True
        if (
            platform.system() == "Windows"
            and self.settings.use_alt_shift_hotkey
            and now - self.last_alt_shift_toggle_time >= 0.2
            and self.alt_pressed
            and self.shift_pressed
        ):
            self.last_alt_shift_toggle_time = now
            self.toggle_start_stop()
            return

        key_str = normalize_runtime_toggle_listener_key(key)
        if self.should_toggle_runtime_group(key_str, now):
            self.last_runtime_toggle_time = now
            self.toggle_runtime_event_group()
            return

        if self.should_toggle_start_stop(key_str):
            self.toggle_start_stop()

    def on_key_release(self, key: object) -> None:
        if key in (pynput.keyboard.Key.alt_l, pynput.keyboard.Key.alt_r):
            self.alt_pressed = False
        if key in (pynput.keyboard.Key.shift_l, pynput.keyboard.Key.shift_r):
            self.shift_pressed = False

    def should_toggle_start_stop(self, key_str: str) -> bool:
        return (
            bool(key_str)
            and not (
                platform.system() == "Windows" and self.settings.use_alt_shift_hotkey
            )
            and self.settings.start_stop_key not in {"DISABLED", "W_UP", "W_DN"}
            and key_str == self.settings.start_stop_key.upper()
        )

    def should_toggle_runtime_group(self, key_str: str, current_time: float) -> bool:
        runtime_trigger = normalize_runtime_toggle_trigger(self.runtime_toggle_key)
        return (
            self.runtime_toggle_enabled
            and self.is_running
            and bool(runtime_trigger)
            and is_keyboard_runtime_toggle_trigger(runtime_trigger)
            and key_str == runtime_trigger.upper()
            and current_time - self.last_runtime_toggle_time
            >= RUNTIME_TOGGLE_DEBOUNCE_SECONDS
            and self._target_process_is_active()
        )

    def _start_mac_hotkeys(self) -> None:
        """Arm macOS Option+Shift / runtime key via CGEventTap; poll fallback."""
        self.ctrl_check_active = True
        self.router.begin_responsiveness()
        tap = MacHotkeyTapListener(
            self.router,
            debounce_seconds=MAC_ALT_SHIFT_DEBOUNCE_SECONDS,
            runtime_debounce_seconds=RUNTIME_TOGGLE_DEBOUNCE_SECONDS,
            start_stop_enabled=self._mac_start_stop_enabled_for_poll,
            runtime_toggle_enabled=self._mac_runtime_toggle_enabled_for_poll,
            runtime_key_provider=self._mac_runtime_key_for_poll,
            on_start_stop=self.on_mac_start_stop_chord,
            on_runtime_toggle=self.on_mac_runtime_toggle_chord,
        )
        tap.start()
        if tap.is_active:
            self._mac_hotkey_tap_listener = tap
            self.router.add(tap, started=True)
            logger.info("macOS hotkeys: CGEventTap active (events consumed)")
            return
        # No Accessibility / tap install failure: observe-only poll (no consume).
        try:
            tap.stop()
        except Exception:
            pass
        logger.warning(
            "macOS hotkeys: CGEventTap unavailable; falling back to key-state poll "
            "(Option+Shift will still reach the focused app)"
        )
        self._start_mac_key_polling()

    def _start_mac_key_polling(self) -> None:
        """Fallback: detect Option+Shift on a bg thread without consuming events."""
        self.ctrl_check_active = True
        listener = MacKeyPollListener(
            self.router,
            interval_ms=MAC_POLL_INTERVAL_MS,
            hold_seconds=MAC_ALT_SHIFT_HOLD_SECONDS,
            debounce_seconds=MAC_ALT_SHIFT_DEBOUNCE_SECONDS,
            runtime_debounce_seconds=RUNTIME_TOGGLE_DEBOUNCE_SECONDS,
            start_stop_enabled=self._mac_start_stop_enabled_for_poll,
            runtime_toggle_enabled=self._mac_runtime_toggle_enabled_for_poll,
            runtime_key_provider=self._mac_runtime_key_for_poll,
            on_start_stop=self.on_mac_start_stop_chord,
            on_runtime_toggle=self.on_mac_runtime_toggle_chord,
        )
        self._mac_key_poll_listener = listener
        self.router.add(listener)

    def _mac_start_stop_enabled_for_poll(self) -> bool:
        return bool(getattr(self.settings, "toggle_start_stop_mac", False))

    def _mac_runtime_toggle_enabled_for_poll(self) -> bool:
        if not self.runtime_toggle_enabled or not self.is_running:
            return False
        if not self._target_process_is_active():
            return False
        return is_keyboard_runtime_toggle_trigger(self.runtime_toggle_key)

    def _mac_runtime_key_for_poll(self) -> str | None:
        if not self.runtime_toggle_enabled:
            return None
        trigger = normalize_runtime_toggle_trigger(self.runtime_toggle_key)
        if not is_keyboard_runtime_toggle_trigger(trigger):
            return None
        return trigger

    def on_mac_start_stop_chord(self) -> None:
        """Main-thread: Option+Shift chord accepted by bg poller."""
        if not self.ctrl_check_active:
            return
        self.last_alt_shift_toggle_time = time.time()
        self.toggle_start_stop()

    def on_mac_runtime_toggle_chord(self) -> None:
        """Main-thread: runtime toggle key accepted by bg poller."""
        if not self.ctrl_check_active:
            return
        self.last_runtime_toggle_time = time.time()
        self.toggle_runtime_event_group()

    def on_mouse_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        pid = selected_process_pid(self.host.selection().process)
        if pid is None or not ProcessUtils.is_process_active(pid):
            return

        curr_time = time.time()
        if self.latest_scroll_time and curr_time - self.latest_scroll_time <= 0.75:
            return

        key = self.settings.start_stop_key
        if (key == "W_UP" and dy > 0) or (key == "W_DN" and dy < 0):
            self.toggle_start_stop()
        self.latest_scroll_time = curr_time

    def _runtime_toggle_trigger_ready(self, current_time: float) -> bool:
        return (
            self.runtime_toggle_enabled
            and self.is_running
            and bool(normalize_runtime_toggle_trigger(self.runtime_toggle_key))
            and current_time - self.last_runtime_toggle_time
            >= RUNTIME_TOGGLE_DEBOUNCE_SECONDS
            and self._target_process_is_active()
        )

    def on_runtime_toggle_mouse_scroll(
        self, x: int, y: int, dx: int, dy: int
    ) -> None:
        trigger = normalize_runtime_toggle_trigger(self.runtime_toggle_key)
        curr_time = time.time()
        if not self._runtime_toggle_trigger_ready(curr_time):
            return
        if (
            self.latest_runtime_scroll_time
            and curr_time - self.latest_runtime_scroll_time
            <= RUNTIME_TOGGLE_SCROLL_GESTURE_SECONDS
        ):
            return
        if (trigger == WHEEL_UP_TRIGGER and dy > 0) or (
            trigger == WHEEL_DOWN_TRIGGER and dy < 0
        ):
            self.latest_runtime_scroll_time = curr_time
            self.last_runtime_toggle_time = curr_time
            self.toggle_runtime_event_group()

    def on_runtime_toggle_mouse_click(
        self, x: int, y: int, button: object, pressed: bool
    ) -> None:
        if not pressed:
            return

        trigger = normalize_runtime_toggle_trigger(self.runtime_toggle_key)
        curr_time = time.time()
        if not self._runtime_toggle_trigger_ready(curr_time):
            return

        button_name = str(getattr(button, "name", button) or "").lower()
        if button_name in {"button.x1", "x1"}:
            button_trigger = MOUSE_BUTTON_3_TRIGGER
        elif button_name in {"button.x2", "x2"}:
            button_trigger = MOUSE_BUTTON_4_TRIGGER
        else:
            button_trigger = None

        if button_trigger == trigger:
            self.last_runtime_toggle_time = curr_time
            self.toggle_runtime_event_group()

    # ── start / stop ───────────────────────────────────────────────────

    def toggle_start_stop(self) -> None:
        # Start/stop can take hundreds of ms (processor + UI + sound). A second
        # Option+Shift during that window must not be dropped silently.
        if self.toggle_transition_in_progress:
            self._pending_start_stop_toggle = True
            return
        self.toggle_transition_in_progress = True
        try:
            if not self.is_running:
                if self.start_simulation():
                    self.is_running = True
                self.host.on_run_state_changed()
            else:
                self.is_running = False
                self.stop_simulation()
        finally:
            self.toggle_transition_in_progress = False
            if self._pending_start_stop_toggle:
                self._pending_start_stop_toggle = False
                # Defer so we do not recurse inside the input drain stack.
                try:
                    self.host.defer(self.toggle_start_stop)
                except Exception:
                    self.toggle_start_stop()

    def start_simulation(self) -> bool:
        # 빠른 캡처 HUD는 모달이 아니다. 실행 중 전역 CTRL을 캡처·저장으로
        # 받지 않도록 실행 전에 닫는다.
        self.host.before_start()
        process = self.host.selection().process
        if not (process and "(" in process and self.run_profile_names()):
            return False

        session, compose_errors = self.compose_selected_run(migrate=True)
        if compose_errors or session is None:
            return False

        events = runnable_events(list(session.events))
        if not events:
            return False
        self.configure_runtime_toggle_session(
            enabled=bool(session.runtime_toggle_enabled),
            toggle_key=session.runtime_toggle_key,
            events=events,
        )

        set_name = self.host.selection().modkey_set or DEFAULT_MODKEY_SET_NAME
        try:
            mod_keys = get_modkey_set(set_name, self.modkey_sets_path)
        except Exception as exc:
            logger.warning(f"Modifier key set load failed for '{set_name}': {exc}")
            mod_keys = default_modification_keys()

        self.terminate_event.clear()
        self.keystroke_processor = KeystrokeProcessor(
            self,
            process,
            events,
            mod_keys,
            self.terminate_event,
        )
        if not self.keystroke_processor.event_data_list:
            self.keystroke_processor = None
            self.reset_runtime_toggle_session()
            return False

        # Keep the macOS bg key poller alive while Option+Shift may still be held.
        if platform.system() != "Darwin" or not self.ctrl_check_active:
            self.setup_event_handlers()

        self.keystroke_processor.start()
        self.save_state()
        self.sound_player.play_start_sound()
        return True

    def stop_simulation(self) -> None:
        if self.keystroke_processor:
            safe_call(self.keystroke_processor.stop)
            self.keystroke_processor = None
        self.terminate_event.set()
        self.reset_runtime_toggle_session()
        if platform.system() != "Darwin" or not self.settings.toggle_start_stop_mac:
            self.setup_event_handlers()

        if safe_call(self.host.is_alive):
            self.sound_player.play_stop_sound()
            self.host.on_run_state_changed()

    def toggle_runtime_event_group(self) -> bool:
        if not (
            self.is_running
            and self.keystroke_processor
            and self.runtime_toggle_enabled
            and self.runtime_toggle_key
        ):
            return False

        next_state = not self.runtime_toggle_active
        safe_call(self.keystroke_processor.set_runtime_toggle_active, next_state)
        self.runtime_toggle_active = next_state
        if self.settings.runtime_toggle_sound_enabled:
            if next_state:
                self.sound_player.play_runtime_toggle_on_sound()
            else:
                self.sound_player.play_runtime_toggle_off_sound()
        self.host.on_status_changed()
        return True

    # ── persistence / shutdown ─────────────────────────────────────────

    def save_state(self) -> None:
        sel = self.host.selection()
        StateUtils.save_main_app_state(
            process=sel.process.split(" (")[0],
            profile=sel.profile,
            run_set=sel.run_set or CURRENT_RUN_SET_ID,
            modkey_set=sel.modkey_set,
            main_pos=self.host.window_position(),
        )

    def shutdown(self) -> None:
        self.terminate_event.set()
        safe_call(self.stop_simulation)
        safe_call(self.save_state)
        safe_call(self.unbind_events)
