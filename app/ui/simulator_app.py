from __future__ import annotations

import json
import platform
import re
import sys
import threading
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Any, NotRequired, ParamSpec, TypedDict, TypeVar, cast

from loguru import logger
import pynput.keyboard
import pynput.mouse
from app.utils.i18n import normalize_language, set_language, txt

from app.core.models import EventModel, ProfileModel, UserSettings
from app.core.run_composition import (
    ComposedRunSession,
    compose_run_session,
)
from app.ui.dialogs import ask_confirm
from app.ui.modkeys import ModificationKeysWindow
from app.ui.main_frames import (
    ButtonFrame,
    ModKeySetFrame,
    ProcessFrame,
    ProfileFrame,
    RunSetFrame,
)
from app.ui.input_listener_session import InputListener, InputListenerSession
from app.ui.mac_hotkey_tap import MacHotkeyTapListener
from app.ui.mac_key_poll import MacKeyPollListener
from app.storage.modkey_sets_storage import (
    DEFAULT_MODKEY_SET_NAME,
    DEFAULT_MODKEY_SETS_PATH,
    default_modification_keys,
    get_modkey_set,
)
from app.storage.run_sets_storage import (
    CURRENT_RUN_SET_ID,
    DEFAULT_RUN_SETS_PATH,
    is_current_run_set,
    upsert_run_set,
)
from app.storage.profile_storage import (
    load_profile,
)
from app.storage.settings_storage import load_user_settings, save_user_settings
from app.core.processor import KeystrokeProcessor
from app.ui.profiles import KeystrokeProfiles
from app.ui.quick_event_editor import KeystrokeQuickEventEditor
from app.ui.settings import KeystrokeSettings
from app.ui.sort_events import KeystrokeSortEvents
from app.utils.sounds import SoundPlayer
from app.utils.runtime_toggle import (
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
from app.utils.system import (
    ProcessUtils,
    PermissionUtils,
)
from app.utils.exception_hooks import install_exception_hooks
from app.utils.window_state import StateUtils, WindowUtils
from app.ui import theme

STATUS_BG_INFO = theme.STATUS_INFO_BG
STATUS_FG_INFO = theme.STATUS_INFO_FG
STATUS_BG_OK = theme.STATUS_READY_BG
STATUS_FG_OK = theme.STATUS_READY_FG
STATUS_BG_WARN = theme.STATUS_WARN_BG
STATUS_FG_WARN = theme.STATUS_WARN_FG
STATUS_BG_ERR = theme.STATUS_ERROR_BG
STATUS_FG_ERR = theme.STATUS_ERROR_FG
STATUS_BG_RUN = theme.STATUS_RUNNING_BG
STATUS_FG_RUN = theme.STATUS_RUNNING_FG

# macOS Option+Shift: prefer CGEventTap (consume + CFRunLoop); poll is fallback.
MAC_POLL_INTERVAL_MS = 10
MAC_ALT_SHIFT_DEBOUNCE_SECONDS = 0.2
# Poll-only hold filter (tap fires on chord rising edge, no hold delay).
MAC_ALT_SHIFT_HOLD_SECONDS = 0.015

P = ParamSpec("P")
R = TypeVar("R")
VoidCallback = Callable[[], None]


class ReadinessSnapshot(TypedDict):
    can_start: bool
    badge_text: str
    title: str
    detail: str
    bg: str
    fg: str
    missing_permissions: NotRequired[list[str]]


def safe_call(func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R | None:
    """예외를 무시하고 함수 호출"""
    try:
        return func(*args, **kwargs)
    except Exception:
        return None



class KeystrokeSimulatorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        install_exception_hooks(self)
        self.title("Keystroke Simulator")
        self.profiles_dir = Path("profiles")
        self.profiles_dir.mkdir(exist_ok=True)
        self.modkey_sets_path = Path(DEFAULT_MODKEY_SETS_PATH)
        self.is_running: tk.BooleanVar = tk.BooleanVar(value=False)
        self.selected_process: tk.StringVar = tk.StringVar()
        self.selected_profile: tk.StringVar = tk.StringVar()
        self.selected_modkey_set: tk.StringVar = tk.StringVar(
            value=DEFAULT_MODKEY_SET_NAME
        )
        self.selected_run_set: tk.StringVar = tk.StringVar(value=CURRENT_RUN_SET_ID)
        self.run_sets_path = Path(DEFAULT_RUN_SETS_PATH)
        self.keystroke_processor: KeystrokeProcessor | None = None
        self.terminate_event: threading.Event = threading.Event()
        self.settings: UserSettings = UserSettings()
        self.settings_window: KeystrokeSettings | None = None
        self.latest_scroll_time: float | None = None
        self.sound_player: SoundPlayer = SoundPlayer()

        # Input Listeners
        self.start_stop_mouse_listener: InputListener | None = None
        self.runtime_toggle_mouse_listener: InputListener | None = None
        self.keyboard_listener: InputListener | None = None
        self.input_listener_session = InputListenerSession(self)
        self.alt_pressed: bool = False
        self.shift_pressed: bool = False
        self.last_alt_shift_toggle_time: float = 0
        self.ctrl_check_active: bool = False
        self._mac_hotkey_tap_listener: MacHotkeyTapListener | None = None
        self._mac_key_poll_listener: MacKeyPollListener | None = None
        self._selection_trace_handles: list[str] = []
        self.runtime_toggle_enabled: bool = False
        self.runtime_toggle_key: str | None = None
        self.runtime_toggle_active: bool = False
        self.runtime_toggle_member_count: int = 0
        self.last_runtime_toggle_time: float = 0
        self.latest_runtime_scroll_time: float | None = None
        self.toggle_transition_in_progress: bool = False
        self._pending_start_stop_toggle: bool = False

        self._create_ui()
        self._bind_selection_traces()
        self.load_settings()
        self.setup_event_handlers()
        self.update_ui()

    def _create_ui(self) -> None:
        # Workstation theme: paper-tone root + ttk styles.
        self.configure(bg=theme.SURFACE_PAPER)
        try:
            ttk.Style(self).theme_use("default")
        except tk.TclError:
            pass
        theme.install_styles(self)
        f = theme.fonts()

        # --- Context Bar (top header) -----------------------------------
        self.context_bar: tk.Frame = tk.Frame(
            self,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_3,
            pady=theme.SPACE_2,
        )
        self.context_bar.pack(fill="x", side="top")
        self.lbl_app_title: tk.Label = tk.Label(
            self.context_bar,
            text="KEYSTROKE SIMULATOR",
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_SECONDARY,
            font=f["heading"],
        )
        self.lbl_app_title.pack(side=tk.LEFT)
        self.lbl_app_subtitle: tk.Label = tk.Label(
            self.context_bar,
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
        )
        self.lbl_app_subtitle.pack(side=tk.RIGHT)
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x", side="top")

        # --- Run Dock (bottom, packed before body so it stays anchored) --
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x", side="bottom")
        self.run_dock: tk.Frame = tk.Frame(
            self,
            bg=theme.SURFACE_PAPER,
            padx=theme.SPACE_3,
            pady=theme.SPACE_3,
        )
        self.run_dock.pack(fill="x", side="bottom")

        # --- Body (cards live here) --------------------------------------
        self.body: tk.Frame = tk.Frame(
            self,
            bg=theme.SURFACE_PAPER,
            padx=theme.SPACE_3,
            pady=theme.SPACE_3,
        )
        self.body.pack(fill="both", expand=True, side="top")
        self.workspace: tk.Frame = tk.Frame(self.body, bg=theme.SURFACE_PAPER)
        self.workspace.pack(side=tk.TOP, fill="both", expand=True)

        # TARGET card -----------------------------------------------------
        self.target_card: tk.Frame
        self.status_frame: tk.Frame
        self.tools_card: tk.Frame
        self.target_card, target_body = self._make_card(
            self.workspace, txt("Target", "대상")
        )
        self.target_card.pack(fill="x", pady=(0, theme.SPACE_3))
        self.process_frame: ProcessFrame = ProcessFrame(target_body, self.selected_process)
        self.process_frame.configure(bg=theme.SURFACE_CANVAS)
        self.process_frame.pack(fill="x", pady=(0, theme.SPACE_1))
        self.profile_frame: ProfileFrame = ProfileFrame(
            target_body,
            self.selected_profile,
            self.profiles_dir,
            edit_cb=self.open_profile,
            sort_cb=self.sort_profile_events,
            list_changed_cb=self._sync_run_set_available,
        )
        self.profile_frame.configure(bg=theme.SURFACE_CANVAS)
        self.profile_frame.pack(fill="x", pady=(0, theme.SPACE_1))
        self.modkey_set_frame: ModKeySetFrame = ModKeySetFrame(
            target_body,
            self.selected_modkey_set,
            sets_path=self.modkey_sets_path,
            edit_cb=self.open_modkeys,
        )
        self.modkey_set_frame.configure(bg=theme.SURFACE_CANVAS)
        self.modkey_set_frame.pack(fill="x", pady=(0, theme.SPACE_1))
        self.run_set_frame: RunSetFrame = RunSetFrame(
            target_body,
            self.selected_run_set,
            sets_path=self.run_sets_path,
            profiles_dir=self.profiles_dir,
            current_profile_getter=lambda: self.selected_profile.get(),
            on_change=self._on_run_profiles_changed,
        )
        self.run_set_frame.configure(bg=theme.SURFACE_CANVAS)
        self.run_set_frame.pack(fill="x")
        self._sync_run_set_available()

        # STATE card ------------------------------------------------------
        self.status_frame, status_body = self._make_card(
            self.workspace, txt("State", "상태")
        )
        self.status_frame.pack(fill="x", pady=(0, theme.SPACE_3))
        # Color-bar on the left + content stack on the right.
        self.status_color_bar: tk.Frame = tk.Frame(
            status_body, bg=theme.STATUS_READY_FG, width=4
        )
        self.status_color_bar.pack(side=tk.LEFT, fill="y", padx=(0, theme.SPACE_2))
        status_stack = tk.Frame(status_body, bg=theme.SURFACE_CANVAS)
        status_stack.pack(side=tk.LEFT, fill="both", expand=True)
        # Pill: icon + badge text in one rounded background.
        self.lbl_status_badge: tk.Label = tk.Label(
            status_stack,
            bg=theme.STATUS_READY_BG,
            fg=theme.STATUS_READY_FG,
            font=f["body_bold"],
            padx=theme.SPACE_2,
            pady=theme.SPACE_1,
            anchor="w",
        )
        self.lbl_status_badge.pack(anchor="w")
        self.lbl_status_title: tk.Label = tk.Label(
            status_stack,
            font=f["heading"],
            bg=theme.SURFACE_CANVAS,
            fg=theme.INK_PRIMARY,
            anchor="w",
            justify="left",
        )
        self.lbl_status_title.pack(anchor="w", pady=(theme.SPACE_2, 0))
        self.lbl_status_detail: tk.Label = tk.Label(
            status_stack,
            anchor="w",
            justify="left",
            bg=theme.SURFACE_CANVAS,
            fg=theme.INK_SECONDARY,
            wraplength=560,
            font=f["body"],
        )
        self.lbl_status_detail.pack(anchor="w", pady=(theme.SPACE_1, 0))
        self.lbl_hotkey_hint: tk.Label = tk.Label(
            status_stack,
            anchor="w",
            justify="left",
            bg=theme.SURFACE_CANVAS,
            fg=theme.INK_MUTED,
            wraplength=560,
            font=f["caption"],
        )
        self.lbl_hotkey_hint.pack(anchor="w", pady=(theme.SPACE_2, 0))
        self.permission_actions_frame: tk.Frame = tk.Frame(
            status_stack, bg=theme.SURFACE_CANVAS
        )
        self.btn_open_screen_permission: tk.Button = tk.Button(
            self.permission_actions_frame,
            command=lambda: self._open_macos_permission_setting("screen"),
        )
        self.btn_open_accessibility_permission: tk.Button = tk.Button(
            self.permission_actions_frame,
            command=lambda: self._open_macos_permission_setting("accessibility"),
        )
        for btn in (
            self.btn_open_screen_permission,
            self.btn_open_accessibility_permission,
        ):
            self._apply_outline_button(btn)

        # TOOLS card ------------------------------------------------------
        self.tools_card, tools_body = self._make_card(
            self.workspace, txt("Tools", "도구")
        )
        self.tools_card.pack(fill="x")
        self.button_frame: ButtonFrame = ButtonFrame(
            tools_body,
            self.open_quick_events,
            self.open_settings,
            self.clear_local_logs,
        )
        self.button_frame.configure(bg=theme.SURFACE_CANVAS)
        self.button_frame.pack(fill="x")

        for sec in (
            self.button_frame.quick_events_button,
            self.button_frame.settings_button,
            self.button_frame.clear_logs_button,
            self.process_frame.refresh_button,
            self.profile_frame.edit_button,
            self.profile_frame.copy_button,
            self.profile_frame.del_button,
            self.profile_frame.sort_button,
            self.run_set_frame.edit_button,
            self.run_set_frame.copy_button,
            self.run_set_frame.del_button,
            self.modkey_set_frame.edit_button,
            self.modkey_set_frame.copy_button,
            self.modkey_set_frame.del_button,
        ):
            self._apply_outline_button(sec)

        # Calm labels inside Process/Profile/ModKeys rows to the canvas tone.
        for w in (
            self.process_frame.lbl_process,
            self.profile_frame.lbl_profiles,
            self.run_set_frame.lbl_run_set,
            self.modkey_set_frame.lbl_sets,
        ):
            w.configure(
                bg=theme.SURFACE_CANVAS,
                fg=theme.INK_SECONDARY,
                font=f["body"],
            )

        # --- Run Dock contents ------------------------------------------
        self.lbl_run_status: tk.Label = tk.Label(
            self.run_dock,
            bg=theme.SURFACE_PAPER,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        )
        self.lbl_run_status.pack(side=tk.LEFT)
        # Label (not tk.Button): Aqua ignores Button bg/fg, so solid fill never shows.
        self.run_start_button: tk.Label = tk.Label(
            self.run_dock,
            text=txt("Start", "시작"),
            cursor="hand2",
        )
        self._run_start_enabled = True
        self._apply_accent_button(self.run_start_button)
        self.run_start_button.bind("<Button-1>", self._on_run_start_clicked)
        self.run_start_button.pack(side=tk.RIGHT)

        style = ttk.Style(self)
        style.configure("TEntry", fieldbackground=theme.SURFACE_CANVAS)
        self._refresh_ui_texts()
        self._restore_window_position()

    # ---------------------------------------------------------------
    # Helpers used by _create_ui
    # ---------------------------------------------------------------
    def _make_card(self, parent: tk.Misc, title: str) -> tuple[tk.Frame, tk.Frame]:
        """Create a workstation-style card with a thin divider title."""
        f = theme.fonts()
        outer = tk.Frame(
            parent,
            bg=theme.SURFACE_CANVAS,
            highlightthickness=1,
            highlightbackground=theme.SURFACE_DIVIDER,
        )
        header = tk.Frame(outer, bg=theme.SURFACE_CANVAS)
        header.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, 0))
        title_label = tk.Label(
            header,
            text=title,
            bg=theme.SURFACE_CANVAS,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        )
        title_label.pack(side=tk.LEFT, anchor="w")
        # Track the label so refresh_texts can update it later if needed.
        cast(Any, outer)._title_label = title_label
        body = tk.Frame(outer, bg=theme.SURFACE_CANVAS)
        body.pack(
            fill="x",
            padx=theme.SPACE_3,
            pady=(theme.SPACE_1, theme.SPACE_3),
        )
        return outer, body

    def _on_run_start_clicked(self, _event: object | None = None) -> None:
        if not getattr(self, "_run_start_enabled", False):
            return
        self.toggle_start_stop()

    @staticmethod
    def _style_run_control(
        btn: tk.Misc,
        *,
        bg: str,
        fg: str,
        cursor: str = "hand2",
    ) -> None:
        """Color the Start/Stop control (Label on Aqua; Button elsewhere)."""
        widget = cast(Any, btn)
        try:
            widget.configure(
                bg=bg,
                fg=fg,
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                padx=theme.SPACE_3,
                pady=theme.SPACE_2,
                cursor=cursor,
            )
        except tk.TclError:
            try:
                widget.configure(bg=bg, fg=fg)
            except tk.TclError:
                pass
        try:
            widget.configure(font=theme.fonts()["body_bold"])
        except Exception:
            pass

    @classmethod
    def _apply_accent_button(cls, btn: tk.Misc) -> None:
        """Solid green + white text (Label preferred: Aqua ignores Button bg/fg)."""
        cls._style_run_control(btn, bg=theme.SIGNAL_BASE, fg="#FFFFFF")

    @classmethod
    def _apply_run_stop_button(cls, btn: tk.Misc) -> None:
        """Running-state Start→Stop control (amber fill, white text)."""
        cls._style_run_control(btn, bg=theme.STATUS_RUNNING_FG, fg="#FFFFFF")

    @classmethod
    def _apply_run_disabled_button(cls, btn: tk.Misc) -> None:
        """Muted control when start is not available."""
        cls._style_run_control(
            btn, bg=theme.SURFACE_SUNKEN, fg=theme.INK_MUTED, cursor="arrow"
        )

    @staticmethod
    def _apply_outline_button(btn: tk.Button) -> None:
        f = theme.fonts()
        btn.configure(
            bg=theme.SURFACE_CANVAS,
            fg=theme.INK_PRIMARY,
            activebackground=theme.SURFACE_SUNKEN,
            activeforeground=theme.INK_PRIMARY,
            disabledforeground=theme.INK_MUTED,
            relief="flat",
            borderwidth=1,
            highlightbackground=theme.SURFACE_DIVIDER,
            highlightcolor=theme.SURFACE_DIVIDER,
            highlightthickness=1,
            font=f["body"],
        )

    def _bind_selection_traces(self) -> None:
        def schedule_update(*_args: object) -> None:
            self.after_idle(self.update_ui)

        for var in (
            self.selected_process,
            self.selected_profile,
            self.selected_modkey_set,
            self.selected_run_set,
        ):
            self._selection_trace_handles.append(var.trace_add("write", schedule_update))

    def load_settings(self) -> None:
        # Load settings
        s_file = Path("user_settings.json")
        self.settings, can_save_settings = load_user_settings(s_file)
        self.settings.language = normalize_language(self.settings.language)
        set_language(self.settings.language)
        if can_save_settings:
            save_user_settings(self.settings, s_file)
        sound_player = getattr(self, "sound_player", None)
        if sound_player is not None:
            safe_call(
                sound_player.set_notification_pack,
                self.settings.notification_sound_pack,
            )
            safe_call(
                sound_player.set_runtime_toggle_pack,
                self.settings.runtime_toggle_sound_pack,
            )
        self._refresh_ui_texts()

        # Load state
        state = StateUtils.load_main_app_state() or {}
        proc = state.get("process")
        if isinstance(proc, str) and proc:
            match = next(
                (
                    p
                    for p in cast(tuple[str, ...], self.process_frame.process_combobox.cget("values"))
                    if p.startswith(proc)
                ),
                None,
            )
            if match:
                self.selected_process.set(match)
        prof = state.get("profile")
        if isinstance(prof, str) and prof:
            self.profile_frame.set_selected_profile(prof)
        self._sync_run_set_available()
        self._restore_run_set_selection(state, prof if isinstance(prof, str) else None)
        modkey_set = state.get("modkey_set")
        if isinstance(modkey_set, str) and modkey_set:
            self.modkey_set_frame.set_selected_set(modkey_set)
        self.update_ui()

    def _refresh_ui_texts(self) -> None:
        self._set_card_title(
            getattr(self, "target_card", None), txt("Target", "대상")
        )
        self._set_card_title(
            getattr(self, "status_frame", None), txt("State", "상태")
        )
        self._set_card_title(
            getattr(self, "tools_card", None), txt("Tools", "도구")
        )
        if hasattr(self, "process_frame"):
            self.process_frame.refresh_texts()
        if hasattr(self, "profile_frame"):
            self.profile_frame.refresh_texts()
        if hasattr(self, "run_set_frame"):
            self.run_set_frame.refresh_texts()
        if hasattr(self, "modkey_set_frame"):
            self.modkey_set_frame.refresh_texts()
        if hasattr(self, "button_frame"):
            self.button_frame.refresh_texts()
        run_start_button = self.__dict__.get("run_start_button")
        if run_start_button is not None:
            self._apply_accent_button(run_start_button)
        if hasattr(self, "lbl_hotkey_hint"):
            self.lbl_hotkey_hint.config(text=self._get_hotkey_hint_text())
        if hasattr(self, "btn_open_screen_permission"):
            self.btn_open_screen_permission.config(
                text=txt("Open Screen Recording Settings", "화면 기록 설정 열기")
            )
        if hasattr(self, "btn_open_accessibility_permission"):
            self.btn_open_accessibility_permission.config(
                text=txt("Open Accessibility Settings", "손쉬운 사용 설정 열기")
            )
        if hasattr(self, "lbl_status_badge"):
            self._update_main_status()
        if hasattr(self, "lbl_app_subtitle"):
            self.lbl_app_subtitle.config(
                text=txt("Workstation", "워크스테이션")
            )

    @staticmethod
    def _set_card_title(card: tk.Misc | None, title: str) -> None:
        if card is None:
            return
        label = getattr(card, "_title_label", None)
        if label is not None:
            label.config(text=title)

    def _get_hotkey_hint_text(self) -> str:
        if not hasattr(self, "settings"):
            return ""
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
                "{base}\nToggle set: {trigger} ({state})",
                "{base}\n토글 세트: {trigger} ({state})",
                base=hint,
                trigger=display_runtime_toggle_trigger(self.runtime_toggle_key),
                state=toggle_state,
            )
        return hint

    @staticmethod
    def _listener_key_name(key: object) -> str:
        return normalize_runtime_toggle_listener_key(key)

    def _selected_process_pid(self) -> int | None:
        pid_match = re.search(r"\((\d+)\)", self.selected_process.get())
        return int(pid_match.group(1)) if pid_match else None

    def _target_process_is_active(self) -> bool:
        return ProcessUtils.is_process_active(self._selected_process_pid())

    def _reset_runtime_toggle_session(self) -> None:
        self.runtime_toggle_enabled = False
        self.runtime_toggle_key = None
        self.runtime_toggle_active = False
        self.runtime_toggle_member_count = 0
        self.latest_runtime_scroll_time = None

    def _configure_runtime_toggle_session(
        self,
        *,
        enabled: bool,
        toggle_key: str | None,
        events: list[EventModel],
    ) -> None:
        self._reset_runtime_toggle_session()
        key = normalize_runtime_toggle_trigger(toggle_key)
        member_count = runtime_toggle_member_count(events)
        self.runtime_toggle_enabled = bool(enabled and key and member_count > 0)
        self.runtime_toggle_key = key if self.runtime_toggle_enabled else None
        self.runtime_toggle_member_count = (
            member_count if self.runtime_toggle_enabled else 0
        )

    def _sync_run_set_available(self) -> None:
        frame = self.__dict__.get("run_set_frame")
        profile_frame = self.__dict__.get("profile_frame")
        if frame is None or profile_frame is None:
            return
        names = list(getattr(profile_frame, "profile_names", []) or [])
        frame.set_available_profiles(names)

    def _on_run_profiles_changed(self, _names: list[str]) -> None:
        if not self.is_running.get():
            self.update_ui()

    def _restore_run_set_selection(
        self, state: dict[str, object], profile_name: str | None
    ) -> None:
        """Restore named run set or migrate legacy run_profiles list."""
        frame = self.__dict__.get("run_set_frame")
        if frame is None:
            return
        run_set = state.get("run_set")
        if isinstance(run_set, str) and run_set.strip():
            frame.set_selected_set(run_set.strip())
            return
        # Legacy: run_profiles list from earlier multi-select UI.
        run_profiles_raw = state.get("run_profiles")
        run_profiles: list[str] = []
        if isinstance(run_profiles_raw, list):
            run_profiles = [
                str(item)
                for item in cast(list[object], run_profiles_raw)
                if isinstance(item, str) and item
            ]
        elif isinstance(run_profiles_raw, str) and run_profiles_raw:
            run_profiles = [run_profiles_raw]
        if len(run_profiles) >= 2:
            migrated = "Migrated"
            try:
                # Avoid clobbering an existing user set name if present.
                existing = set(frame.set_ids)
                name = migrated
                n = 2
                while name in existing and name != CURRENT_RUN_SET_ID:
                    name = f"{migrated} {n}"
                    n += 1
                upsert_run_set(name, run_profiles, self.run_sets_path)
                frame.load_sets(select_id=name)
            except Exception:
                frame.set_selected_set(CURRENT_RUN_SET_ID)
            return
        if len(run_profiles) == 1 and profile_name and run_profiles[0] != profile_name:
            # Single different profile → named one-member set is overkill; use current.
            frame.set_selected_set(CURRENT_RUN_SET_ID)
            return
        frame.set_selected_set(CURRENT_RUN_SET_ID)

    def _get_run_profile_names(self) -> list[str]:
        frame = self.__dict__.get("run_set_frame")
        if frame is not None:
            names = frame.get_run_profiles()
            if names:
                return names
        selected = self.selected_profile.get()
        return [selected] if selected else []

    def _run_set_status_label(self) -> str:
        """Short label for status lines (avoids resizing the main window)."""
        frame = self.__dict__.get("run_set_frame")
        set_id = (
            frame.get_selected_set_id()
            if frame is not None
            else self.selected_run_set.get()
        )
        if is_current_run_set(set_id):
            return txt("Current profile", "현재 프로필")
        return (set_id or "—").strip() or "—"

    def _run_set_members_status_label(self, profile_names: list[str] | None = None) -> str:
        """Compact member summary: profile name, count, or em dash."""
        names = profile_names
        if names is None:
            names = self._get_run_profile_names()
        cleaned = [n for n in names if n]
        if not cleaned:
            return "—"
        if len(cleaned) == 1:
            return cleaned[0]
        return txt(
            "{count} profiles",
            "프로필 {count}개",
            count=len(cleaned),
        )

    def _load_profiles_for_run(
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

    def _compose_selected_run(
        self, *, migrate: bool
    ) -> tuple[ComposedRunSession | None, list[str]]:
        names = self._get_run_profile_names()
        if not names:
            return None, [
                txt(
                    "Select at least one profile to run.",
                    "실행할 프로필을 하나 이상 선택하세요.",
                )
            ]
        loaded, load_errors = self._load_profiles_for_run(names, migrate=migrate)
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
            loaded,
            settings=self.__dict__.get("settings"),
            os_name=platform.system(),
        )
        errors = list(load_errors) + list(session.errors)
        if errors:
            return session, errors
        return session, []

    @staticmethod
    def _runnable_events(events: list[EventModel]) -> list[EventModel]:
        return [
            evt
            for evt in events
            if getattr(evt, "use_event", True)
            and (
                getattr(evt, "key_to_enter", None)
                or not getattr(evt, "execute_action", True)
            )
        ]

    @staticmethod
    def _events_with_processor_inputs(events: list[EventModel]) -> list[EventModel]:
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

    def _get_readiness_snapshot(self) -> ReadinessSnapshot:
        if self.is_running.get():
            detail = txt(
                "Stop first if you want to change process, profile, ModKey set, or event settings.",
                "프로세스, 프로필, 수정키 세트, 이벤트 설정을 바꾸려면 먼저 중지하세요.",
            )
            if self.runtime_toggle_enabled and self.runtime_toggle_key:
                detail = txt(
                    "{detail}\nToggle set: {trigger} ({state})",
                    "{detail}\n토글 세트: {trigger} ({state})",
                    detail=detail,
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
                "detail": detail,
                "bg": STATUS_BG_OK,
                "fg": STATUS_FG_OK,
            }

        if not self.selected_process.get() or "(" not in self.selected_process.get():
            return {
                "can_start": False,
                "badge_text": txt("Select Process", "프로세스 선택"),
                "title": txt(
                    "Choose the target app before starting.",
                    "시작하기 전에 대상 앱을 선택하세요.",
                ),
                "detail": txt(
                    "Pick the process you want to watch in the Process list.",
                    "감시할 대상을 프로세스 목록에서 고르세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
            }

        run_names = self._get_run_profile_names()
        if not run_names:
            return {
                "can_start": False,
                "badge_text": txt("Select Profile", "프로필 선택"),
                "title": txt(
                    "Select one or more profiles to run.",
                    "실행할 프로필을 하나 이상 선택하세요.",
                ),
                "detail": txt(
                    "Use Run set to choose profiles. Edit profiles separately from the Profiles row.",
                    "실행 세트에서 프로필을 고르세요. 프로필 행에서는 편집 대상을 고릅니다.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
            }

        session, compose_errors = self._compose_selected_run(migrate=False)
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
                "toggle" in lower
                or "토글" in first
                or "runtime event group" in lower
                or "toggle set" in lower
                or "추가 이벤트 묶음" in first
                or "토글 세트" in first
            ):
                badge = txt("Toggle Conflict", "토글 충돌")
                title = txt(
                    "Toggle set trigger settings need attention.",
                    "토글 세트 트리거 설정을 확인해야 합니다.",
                )
            return {
                "can_start": False,
                "badge_text": badge,
                "title": title,
                "detail": first,
                "bg": STATUS_BG_ERR,
                "fg": STATUS_FG_ERR,
            }

        assert session is not None
        events = list(session.events)
        runnable_events = self._runnable_events(events)
        enabled_count = sum(1 for evt in events if getattr(evt, "use_event", True))
        runnable_count = len(runnable_events)

        if not events:
            return {
                "can_start": False,
                "badge_text": txt("Add Events", "이벤트 추가"),
                "title": txt(
                    "The run set has no events yet.",
                    "실행 세트에 아직 이벤트가 없습니다.",
                ),
                "detail": txt(
                    "Open Profile Manager or Quick Events and save at least one event first.",
                    "프로필 편집 또는 빠른 이벤트에서 이벤트를 먼저 하나 이상 저장하세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
            }

        if enabled_count == 0:
            return {
                "can_start": False,
                "badge_text": txt("Enable Event", "이벤트 활성화"),
                "title": txt(
                    "All events in the run set are disabled.",
                    "실행 세트의 모든 이벤트가 비활성화되어 있습니다.",
                ),
                "detail": txt(
                    "Turn on at least one event in Profile Manager before starting.",
                    "시작하기 전에 프로필 편집에서 이벤트를 하나 이상 활성화하세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
            }

        if runnable_count == 0:
            return {
                "can_start": False,
                "badge_text": txt("Check Events", "이벤트 확인"),
                "title": txt(
                    "Enabled events need a key or condition-only mode.",
                    "활성 이벤트에는 입력 키 또는 조건 전용 설정이 필요합니다.",
                ),
                "detail": txt(
                    "Open Profile Manager and review events with missing input keys.",
                    "프로필 편집에서 입력 키가 비어 있는 이벤트를 확인하세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
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
                "bg": STATUS_BG_ERR,
                "fg": STATUS_FG_ERR,
                "missing_permissions": missing_permissions,
            }

        processor_ready_count = len(self._events_with_processor_inputs(runnable_events))
        if processor_ready_count == 0:
            return {
                "can_start": False,
                "badge_text": txt("Check Events", "이벤트 확인"),
                "title": txt(
                    "Enabled events need captured coordinates and reference data.",
                    "활성 이벤트에는 캡처 좌표와 기준 데이터가 필요합니다.",
                ),
                "detail": txt(
                    "Open Profile Manager and recapture events with missing target positions or reference pixels.",
                    "프로필 편집에서 대상 좌표나 기준 픽셀이 빠진 이벤트를 다시 캡처하세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
            }

        set_label = self._run_set_status_label()
        members_label = self._run_set_members_status_label(list(session.profile_names))
        modkey_set_name = self.selected_modkey_set.get() or DEFAULT_MODKEY_SET_NAME
        return {
            "can_start": True,
            "badge_text": txt("Ready", "준비 완료"),
            "title": txt(
                "Everything is ready to start monitoring.",
                "모니터링을 시작할 준비가 끝났습니다.",
            ),
            "detail": txt(
                "Run set {run_set} · {members} · ModKey {modkey_set} · {count} event(s).",
                "실행 세트 {run_set} · {members} · 수정키 {modkey_set} · 이벤트 {count}개.",
                run_set=set_label,
                members=members_label,
                modkey_set=modkey_set_name,
                count=runnable_count,
            ),
            "bg": STATUS_BG_INFO,
            "fg": STATUS_FG_INFO,
        }

    def _status_detail_with_selection(self, detail: str) -> str:
        """Append run-set + modkey-set selection when not already present."""
        profile_name = (self.selected_profile.get() or "").strip()
        modkey_set_name = (self.selected_modkey_set.get() or "").strip()
        if not profile_name and not modkey_set_name:
            return detail
        if (
            "ModKey set" in detail
            or "ModKey " in detail
            or "수정키 세트" in detail
            or "수정키 " in detail
        ):
            return detail
        set_label = self._run_set_status_label()
        members_label = self._run_set_members_status_label()
        line = txt(
            "Run set {run_set} · {members} · ModKey {modkey_set}",
            "실행 세트 {run_set} · {members} · 수정키 {modkey_set}",
            run_set=set_label or "—",
            members=members_label,
            modkey_set=modkey_set_name or "—",
        )
        return f"{detail}\n{line}" if detail else line


    def _update_main_status(self) -> None:
        if not hasattr(self, "lbl_status_badge"):
            return
        snapshot = self._get_readiness_snapshot()
        bg: str = snapshot["bg"]
        fg: str = snapshot["fg"]
        running = self.is_running.get()
        if running:
            bg, fg = STATUS_BG_RUN, STATUS_FG_RUN
        icon = self._icon_for_status(bg, running)
        badge_text = (
            f"{icon}  {snapshot['badge_text']}" if icon else snapshot["badge_text"]
        )
        self.lbl_status_badge.config(
            text=badge_text,
            bg=bg,
            fg=fg,
        )
        if hasattr(self, "status_color_bar"):
            self.status_color_bar.config(bg=fg)
        self.lbl_status_title.config(text=snapshot["title"])
        self.lbl_status_detail.config(
            text=self._status_detail_with_selection(snapshot["detail"])
        )
        self.lbl_hotkey_hint.config(text=self._get_hotkey_hint_text())
        self._update_permission_actions(
            [] if running else snapshot.get("missing_permissions", [])
        )
        if hasattr(self, "lbl_run_status"):
            self.lbl_run_status.config(text=self._run_dock_text(snapshot, running))

    def _update_permission_actions(self, missing_permissions: list[str]) -> None:
        if not hasattr(self, "permission_actions_frame"):
            return

        buttons = {
            "screen": self.btn_open_screen_permission,
            "accessibility": self.btn_open_accessibility_permission,
        }
        visible = [
            permission for permission in buttons if permission in missing_permissions
        ]
        if not visible:
            self.permission_actions_frame.pack_forget()
            return

        self.permission_actions_frame.pack(anchor="w", pady=(theme.SPACE_2, 0))
        for btn in buttons.values():
            btn.grid_forget()
        for col, permission in enumerate(visible):
            buttons[permission].grid(row=0, column=col, padx=(0, theme.SPACE_2))

    def _open_macos_permission_setting(self, permission: str) -> None:
        if PermissionUtils.open_macos_permission_settings(permission):
            return
        messagebox.showinfo(
            txt("Open Settings", "설정 열기"),
            txt(
                "Open macOS System Settings and grant this executable the required permission.",
                "macOS 시스템 설정을 열어 이 실행 파일에 필요한 권한을 허용하세요.",
            ),
        )

    @staticmethod
    def _icon_for_status(bg: str, running: bool) -> str:
        if running:
            return theme.STATUS_RUNNING_ICON
        return {
            theme.STATUS_INFO_BG: theme.STATUS_INFO_ICON,
            theme.STATUS_READY_BG: theme.STATUS_READY_ICON,
            theme.STATUS_WARN_BG: theme.STATUS_WARN_ICON,
            theme.STATUS_ERROR_BG: theme.STATUS_ERROR_ICON,
            theme.STATUS_RUNNING_BG: theme.STATUS_RUNNING_ICON,
        }.get(bg, theme.STATUS_INFO_ICON)

    def _run_dock_text(self, snapshot: ReadinessSnapshot, running: bool) -> str:
        if running:
            return txt(
                "Running. Press the hotkey or Stop to halt.",
                "실행 중. 단축키 또는 중지로 멈출 수 있습니다.",
            )
        if snapshot.get("can_start"):
            return txt("Ready to start.", "시작할 준비가 되었습니다.")
        return snapshot["badge_text"]

    def setup_event_handlers(self) -> None:
        self.unbind_events()
        self.input_listener_session.start()
        self.bind("<Escape>", self.on_closing)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

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
                    on_scroll=lambda x, y, dx, dy: self.input_listener_session.post(
                        lambda: self._on_mouse_scroll(x, y, dx, dy)
                    )
                ),
            )
            self.input_listener_session.add(self.start_stop_mouse_listener)

        if self.runtime_toggle_enabled and (
            is_wheel_runtime_toggle_trigger(runtime_toggle_trigger)
            or is_mouse_button_runtime_toggle_trigger(runtime_toggle_trigger)
        ):
            self.runtime_toggle_mouse_listener = cast(
                InputListener,
                pynput.mouse.Listener(
                    on_scroll=lambda x, y, dx, dy: self.input_listener_session.post(
                        lambda: self._on_runtime_toggle_mouse_scroll(x, y, dx, dy)
                    ),
                    on_click=lambda x, y, button, pressed: self.input_listener_session.post(
                        lambda: self._on_runtime_toggle_mouse_click(
                            x, y, button, pressed
                        )
                    ),
                ),
            )
            self.input_listener_session.add(self.runtime_toggle_mouse_listener)

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
                    on_press=lambda key: self.input_listener_session.post(
                        lambda: self._on_key_press(key)
                    ),
                    on_release=lambda key: self.input_listener_session.post(
                        lambda: self._on_key_release(key)
                    ),
                ),
            )
            self.input_listener_session.add(self.keyboard_listener)

    def _on_key_press(self, key: object) -> None:
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

        key_str = self._listener_key_name(key)
        if self._should_toggle_runtime_group(key_str, now):
            self.last_runtime_toggle_time = now
            self.toggle_runtime_event_group()
            return

        if self._should_toggle_start_stop(key_str):
            self.toggle_start_stop()

    def _on_key_release(self, key: object) -> None:
        if key in (pynput.keyboard.Key.alt_l, pynput.keyboard.Key.alt_r):
            self.alt_pressed = False
        if key in (pynput.keyboard.Key.shift_l, pynput.keyboard.Key.shift_r):
            self.shift_pressed = False

    def _should_toggle_start_stop(self, key_str: str) -> bool:
        return (
            bool(key_str)
            and not (
                platform.system() == "Windows" and self.settings.use_alt_shift_hotkey
            )
            and self.settings.start_stop_key not in {"DISABLED", "W_UP", "W_DN"}
            and key_str == self.settings.start_stop_key.upper()
        )

    def _should_toggle_runtime_group(self, key_str: str, current_time: float) -> bool:
        runtime_trigger = normalize_runtime_toggle_trigger(self.runtime_toggle_key)
        return (
            self.runtime_toggle_enabled
            and self.is_running.get()
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
        self.input_listener_session.begin_responsiveness()
        tap = MacHotkeyTapListener(
            self.input_listener_session,
            debounce_seconds=MAC_ALT_SHIFT_DEBOUNCE_SECONDS,
            runtime_debounce_seconds=RUNTIME_TOGGLE_DEBOUNCE_SECONDS,
            start_stop_enabled=self._mac_start_stop_enabled_for_poll,
            runtime_toggle_enabled=self._mac_runtime_toggle_enabled_for_poll,
            runtime_key_provider=self._mac_runtime_key_for_poll,
            on_start_stop=self._on_mac_start_stop_chord,
            on_runtime_toggle=self._on_mac_runtime_toggle_chord,
        )
        tap.start()
        if tap.is_active:
            self._mac_hotkey_tap_listener = tap
            self.input_listener_session.add(tap, started=True)
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
            self.input_listener_session,
            interval_ms=MAC_POLL_INTERVAL_MS,
            hold_seconds=MAC_ALT_SHIFT_HOLD_SECONDS,
            debounce_seconds=MAC_ALT_SHIFT_DEBOUNCE_SECONDS,
            runtime_debounce_seconds=RUNTIME_TOGGLE_DEBOUNCE_SECONDS,
            start_stop_enabled=self._mac_start_stop_enabled_for_poll,
            runtime_toggle_enabled=self._mac_runtime_toggle_enabled_for_poll,
            runtime_key_provider=self._mac_runtime_key_for_poll,
            on_start_stop=self._on_mac_start_stop_chord,
            on_runtime_toggle=self._on_mac_runtime_toggle_chord,
        )
        self._mac_key_poll_listener = listener
        self.input_listener_session.add(listener)

    def _mac_start_stop_enabled_for_poll(self) -> bool:
        return bool(getattr(self.settings, "toggle_start_stop_mac", False))

    def _mac_runtime_toggle_enabled_for_poll(self) -> bool:
        if not self.runtime_toggle_enabled or not self.is_running.get():
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

    def _on_mac_start_stop_chord(self) -> None:
        """Main-thread: Option+Shift chord accepted by bg poller."""
        if not self.ctrl_check_active:
            return
        self.last_alt_shift_toggle_time = time.time()
        self.toggle_start_stop()

    def _on_mac_runtime_toggle_chord(self) -> None:
        """Main-thread: runtime toggle key accepted by bg poller."""
        if not self.ctrl_check_active:
            return
        self.last_runtime_toggle_time = time.time()
        self.toggle_runtime_event_group()

    def _on_mouse_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        pid_match = re.search(r"\((\d+)\)", self.selected_process.get())
        if not pid_match or not ProcessUtils.is_process_active(int(pid_match.group(1))):
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
            and self.is_running.get()
            and bool(normalize_runtime_toggle_trigger(self.runtime_toggle_key))
            and current_time - self.last_runtime_toggle_time
            >= RUNTIME_TOGGLE_DEBOUNCE_SECONDS
            and self._target_process_is_active()
        )

    def _on_runtime_toggle_mouse_scroll(
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

    def _on_runtime_toggle_mouse_click(
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

    def clear_local_logs(self) -> None:
        log_dir = Path("logs")
        confirmed = ask_confirm(
            self if "tk" in self.__dict__ else None,
            title=txt("Confirm", "확인"),
            message=txt(
                "Delete old log files?",
                "오래된 로그 파일을 삭제하시겠습니까?",
            ),
            ok_text=txt("OK", "확인"),
            cancel_text=txt("Cancel", "취소"),
        )
        if not confirmed:
            return

        deleted_size, count = 0, 0
        if log_dir.exists():
            for p in log_dir.glob("*"):
                if p.name != "keysym.log" and p.is_file():
                    try:
                        deleted_size += p.stat().st_size
                        p.unlink()
                        count += 1
                    except Exception as e:
                        logger.warning(f"Del failed {p}: {e}")

        # No follow-up dialog (Cancel or OK) — keep feedback in logs/status only.
        if count:
            logger.info(
                "Cleared {count} old log files ({size:.2f} MB)",
                count=count,
                size=deleted_size / 1048576,
            )
        else:
            logger.info("No old log files to clear")
        run_status = self.__dict__.get("lbl_run_status")
        if run_status is not None:
            run_status.config(
                text=(
                    txt(
                        "Cleared {count} old log file(s).",
                        "오래된 로그 {count}개 삭제했습니다.",
                        count=count,
                    )
                    if count
                    else txt(
                        "No old logs to clear.",
                        "정리할 오래된 로그가 없습니다.",
                    )
                )
            )

    def toggle_start_stop(self, event: object | None = None) -> None:
        # Start/stop can take hundreds of ms (processor + UI + sound). A second
        # Option+Shift during that window must not be dropped silently.
        if self.toggle_transition_in_progress:
            self._pending_start_stop_toggle = True
            return
        self.toggle_transition_in_progress = True
        try:
            if not self.is_running.get():
                if self.start_simulation():
                    self.is_running.set(True)
                    self.update_ui()
                else:
                    self.update_ui()
            else:
                self.is_running.set(False)
                self.stop_simulation()
        finally:
            self.toggle_transition_in_progress = False
            if getattr(self, "_pending_start_stop_toggle", False):
                self._pending_start_stop_toggle = False
                # Defer so we do not recurse inside the input drain stack.
                try:
                    self.after(0, self.toggle_start_stop)
                except Exception:
                    self.toggle_start_stop()

    def start_simulation(self) -> bool:
        if not (
            self.selected_process.get()
            and "(" in self.selected_process.get()
            and self._get_run_profile_names()
        ):
            return False

        session, compose_errors = self._compose_selected_run(migrate=True)
        if compose_errors or session is None:
            return False

        events = self._runnable_events(list(session.events))
        if not events:
            return False
        self._configure_runtime_toggle_session(
            enabled=bool(session.runtime_toggle_enabled),
            toggle_key=session.runtime_toggle_key,
            events=events,
        )

        set_name = self.selected_modkey_set.get() or DEFAULT_MODKEY_SET_NAME
        try:
            mod_keys = get_modkey_set(set_name, self.modkey_sets_path)
        except Exception as exc:
            logger.warning(f"ModKey set load failed for '{set_name}': {exc}")
            mod_keys = default_modification_keys()

        self.terminate_event.clear()
        self.keystroke_processor = KeystrokeProcessor(
            self,
            self.selected_process.get(),
            events,
            mod_keys,
            self.terminate_event,
        )
        if not self.keystroke_processor.event_data_list:
            self.keystroke_processor = None
            self._reset_runtime_toggle_session()
            return False

        # Keep the macOS bg key poller alive while Option+Shift may still be held.
        if platform.system() != "Darwin" or not self.__dict__.get(
            "ctrl_check_active", False
        ):
            self.setup_event_handlers()

        self.keystroke_processor.start()
        self._save_latest_state()
        self.sound_player.play_start_sound()
        return True

    def stop_simulation(self) -> None:
        if self.keystroke_processor:
            safe_call(self.keystroke_processor.stop)
            self.keystroke_processor = None
        self.terminate_event.set()
        self._reset_runtime_toggle_session()
        if platform.system() != "Darwin" or not self.settings.toggle_start_stop_mac:
            self.setup_event_handlers()

        if safe_call(self.winfo_exists):
            self.sound_player.play_stop_sound()
            self.update_ui()

    def toggle_runtime_event_group(self) -> bool:
        if not (
            self.is_running.get()
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
        self._update_main_status()
        hotkey_hint = self.__dict__.get("lbl_hotkey_hint")
        if hotkey_hint is not None:
            hotkey_hint.config(text=self._get_hotkey_hint_text())
        return True

    def update_ui(self) -> None:
        running = self.is_running.get()
        state = "disabled" if running else "normal"
        readonly_state = "disabled" if running else "readonly"
        readiness = self._get_readiness_snapshot()

        self.process_frame.process_combobox.config(state=readonly_state)
        self.process_frame.refresh_button.config(state=state)
        self.profile_frame.profile_combobox.config(state=readonly_state)
        self.profile_frame.edit_button.config(state=state)
        self.profile_frame.copy_button.config(state=state)
        self.profile_frame.del_button.config(state=state)
        self.profile_frame.sort_button.config(state=state)
        run_set_frame = self.__dict__.get("run_set_frame")
        if run_set_frame is not None:
            run_set_frame.sets_combobox.config(state=readonly_state)
            if running:
                run_set_frame.edit_button.config(state="disabled")
                run_set_frame.copy_button.config(state="disabled")
                run_set_frame.del_button.config(state="disabled")
            else:
                run_set_frame._update_action_states()
            # Keep "current profile" label in sync with profile combobox.
            run_set_frame._refresh_display_value()
        modkey_frame = self.__dict__.get("modkey_set_frame")
        if modkey_frame is not None:
            modkey_frame.sets_combobox.config(state=readonly_state)
            modkey_frame.edit_button.config(state=state)
            modkey_frame.copy_button.config(state=state)
            modkey_frame.del_button.config(state=state)

        run_start_button = self.__dict__.get("run_start_button")
        if run_start_button is not None:
            can_press = bool(running or readiness["can_start"])
            self._run_start_enabled = can_press
            label = txt("Stop", "중지") if running else txt("Start", "시작")
            start_state = "normal" if can_press else "disabled"
            # Prefer single config() for Button/mocks; Label ignores state=.
            try:
                run_start_button.config(text=label, state=start_state)  # type: ignore[attr-defined]
            except tk.TclError:
                try:
                    run_start_button.configure(text=label)  # type: ignore[attr-defined]
                except tk.TclError:
                    pass
            # Label-based control: colors encode enablement (Aqua ignores Button bg/fg).
            if running:
                self._apply_run_stop_button(run_start_button)
            elif can_press:
                self._apply_accent_button(run_start_button)
            else:
                self._apply_run_disabled_button(run_start_button)
        self.button_frame.quick_events_button.config(state=state)
        self.button_frame.settings_button.config(state=state)
        self.button_frame.clear_logs_button.config(state=state)
        self._update_main_status()

    def open_modkeys(self) -> None:
        if self.is_running.get():
            return
        set_name = self.selected_modkey_set.get()
        if not set_name:
            return
        win = ModificationKeysWindow(
            self, set_name, sets_path=self.modkey_sets_path
        )
        # Only block when a real Tk interpreter is attached (skip unit stubs).
        if "tk" in self.__dict__:
            safe_call(self.wait_window, win)
        self._update_main_status()

    def open_profile(self) -> None:
        if self.is_running.get():
            return
        if self.selected_profile.get():
            KeystrokeProfiles(
                self,
                self.selected_profile.get(),
                self.reload_profiles,
                profiles_dir=self.profiles_dir,
            )

    def reload_profiles(self, new_name: str) -> None:
        self.profile_frame.load_profiles(select_name=new_name)
        self._sync_run_set_available()
        self.update_ui()

    def sort_profile_events(self) -> None:
        if self.is_running.get():
            return
        self.unbind_events()
        if self.selected_profile.get():
            KeystrokeSortEvents(
                self,
                self.selected_profile.get(),
                self.reload_profiles,
                profiles_dir=self.profiles_dir,
            )

    def open_quick_events(self) -> None:
        if self.is_running.get():
            return
        KeystrokeQuickEventEditor(
            self,
            profiles_dir=self.profiles_dir,
            on_close=self.update_ui,
        )

    def open_settings(self) -> None:
        existing_window = self.settings_window
        if existing_window and safe_call(existing_window.winfo_exists):
            window = cast(Any, existing_window)
            safe_call(window.lift)
            safe_call(window.focus_force)
            safe_call(window.grab_set)
            return
        if existing_window:
            self.settings_window = None
        self.unbind_events()
        self.settings_window = KeystrokeSettings(self)

    def _restore_window_position(self) -> None:
        pos = StateUtils.parse_slash_int_pair(
            (StateUtils.load_main_app_state() or {}).get("main_pos")
        )
        if pos is not None:
            try:
                self.geometry(f"+{pos[0]}+{pos[1]}")
                return
            except tk.TclError:
                pass
        WindowUtils.center_window(self)

    def _save_latest_state(self) -> None:
        main_pos = None
        try:
            main_pos = f"{self.winfo_x()}/{self.winfo_y()}"
        except tk.TclError:
            pass
        StateUtils.save_main_app_state(
            process=self.selected_process.get().split(" (")[0],
            profile=self.selected_profile.get(),
            run_set=self.selected_run_set.get() or CURRENT_RUN_SET_ID,
            modkey_set=self.selected_modkey_set.get(),
            main_pos=main_pos,
        )

    def unbind_events(self) -> None:
        safe_call(self.unbind, "<Escape>")
        self.input_listener_session.stop()
        self.keyboard_listener = None
        self.start_stop_mouse_listener = None
        self.runtime_toggle_mouse_listener = None

        self.ctrl_check_active = False
        self._mac_hotkey_tap_listener = None
        self._mac_key_poll_listener = None

    def on_closing(self, event: object | None = None) -> None:
        if getattr(self, "_is_closing", False):
            return
        self._is_closing = True
        logger.info("Shutting down...")

        self.terminate_event.set()
        safe_call(self.stop_simulation)
        safe_call(self._save_latest_state)
        safe_call(self.unbind_events)
        sound_player = getattr(self, "sound_player", None)
        if sound_player is not None:
            safe_call(getattr(sound_player, "close", lambda: None))
        safe_call(self.destroy)
        safe_call(self.quit)
