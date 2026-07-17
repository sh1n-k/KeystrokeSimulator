from __future__ import annotations

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

from app.core.validation import find_duplicate_event_names
from app.core.models import EventModel, ProfileModel, UserSettings
from app.ui.modkeys import ModificationKeysWindow
from app.ui.main_frames import ButtonFrame, ProcessFrame, ProfileButtonFrame, ProfileFrame
from app.ui.input_listener_session import InputListener, InputListenerSession
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
    collect_runtime_toggle_validation_errors,
    normalize_runtime_toggle_listener_key,
    normalize_runtime_toggle_trigger,
    runtime_toggle_member_count,
)
from app.utils.system import (
    ProcessUtils,
    PermissionUtils,
)
from app.utils.exception_hooks import install_exception_hooks
from app.utils.keys import KeyUtils
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
        self.is_running: tk.BooleanVar = tk.BooleanVar(value=False)
        self.selected_process: tk.StringVar = tk.StringVar()
        self.selected_profile: tk.StringVar = tk.StringVar()
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
        self._mac_poll_after_id: str | None = None
        self._mac_alt_shift_state = False
        self._mac_runtime_toggle_state = False
        self._selection_trace_handles: list[str] = []
        self.runtime_toggle_enabled: bool = False
        self.runtime_toggle_key: str | None = None
        self.runtime_toggle_active: bool = False
        self.runtime_toggle_member_count: int = 0
        self.last_runtime_toggle_time: float = 0
        self.latest_runtime_scroll_time: float | None = None
        self.toggle_transition_in_progress: bool = False

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
        self.nav_rail: tk.Frame = self._build_main_nav_rail(self.body)
        self.nav_rail.pack(side=tk.LEFT, fill="y", padx=(0, theme.SPACE_3))
        self.workspace: tk.Frame = tk.Frame(self.body, bg=theme.SURFACE_PAPER)
        self.workspace.pack(side=tk.LEFT, fill="both", expand=True)

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
            target_body, self.selected_profile, self.profiles_dir
        )
        self.profile_frame.configure(bg=theme.SURFACE_CANVAS)
        self.profile_frame.pack(fill="x")

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
        self.button_frame.pack(fill="x", pady=(0, theme.SPACE_1))
        self.profile_button_frame: ProfileButtonFrame = ProfileButtonFrame(
            tools_body,
            self.open_modkeys,
            self.open_profile,
            self.sort_profile_events,
        )
        self.profile_button_frame.configure(bg=theme.SURFACE_CANVAS)
        self.profile_button_frame.pack(fill="x")

        for sec in (
            self.button_frame.quick_events_button,
            self.button_frame.settings_button,
            self.button_frame.clear_logs_button,
            self.profile_button_frame.modkeys_button,
            self.profile_button_frame.edit_profile_button,
            self.profile_button_frame.sort_button,
            self.process_frame.refresh_button,
            self.profile_frame.copy_button,
            self.profile_frame.del_button,
        ):
            self._apply_outline_button(sec)

        # Calm labels inside Process/Profile rows to the canvas tone.
        for w in (self.process_frame.lbl_process, self.profile_frame.lbl_profiles):
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
        self.run_start_button: tk.Button = tk.Button(
            self.run_dock,
            text=txt("Start", "시작"),
            command=self.toggle_start_stop,
        )
        self._apply_accent_button(self.run_start_button)
        self.run_start_button.pack(side=tk.RIGHT)

        style = ttk.Style(self)
        style.configure("TEntry", fieldbackground=theme.SURFACE_CANVAS)
        self._refresh_ui_texts()
        WindowUtils.center_window(self)

    # ---------------------------------------------------------------
    # Helpers used by _create_ui
    # ---------------------------------------------------------------
    def _build_main_nav_rail(self, parent: tk.Misc) -> tk.Frame:
        f = theme.fonts()
        rail = tk.Frame(
            parent,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_2,
            pady=theme.SPACE_3,
            width=88,
        )
        rail.pack_propagate(False)

        def make_item(icon: str, en: str, ko: str, command: VoidCallback) -> None:
            item = tk.Label(
                rail,
                text=f"{icon}\n{txt(en, ko)}",
                bg=theme.SURFACE_PANEL,
                fg=theme.INK_SECONDARY,
                font=f["caption"],
                justify="center",
                cursor="hand2",
                padx=theme.SPACE_1,
                pady=theme.SPACE_2,
            )
            item.pack(fill="x", pady=(0, theme.SPACE_2))
            item.bind("<Button-1>", lambda _e: command())

        make_item("▣", "Process", "프로세스", self._focus_process_selector)
        make_item("◇", "Profile", "프로필", self._focus_profile_selector)
        make_item("▤", "Tools", "도구", self._focus_tools_section)
        return rail

    def _focus_process_selector(self) -> None:
        widget = getattr(getattr(self, "process_frame", None), "process_combobox", None)
        self._focus_combobox(widget)

    def _focus_profile_selector(self) -> None:
        widget = getattr(getattr(self, "profile_frame", None), "profile_combobox", None)
        if widget is not None:
            self._focus_combobox(widget)

    @staticmethod
    def _focus_combobox(widget: ttk.Combobox | None) -> None:
        if widget is None:
            return
        widget.focus_set()
        try:
            widget.tk.call("ttk::combobox::Post", widget)
        except (AttributeError, tk.TclError):
            try:
                widget.event_generate("<Button-1>")
            except (AttributeError, tk.TclError):
                pass

    def _focus_tools_section(self) -> None:
        widget = getattr(getattr(self, "button_frame", None), "quick_events_button", None)
        if widget is not None:
            widget.focus_set()

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

    @staticmethod
    def _apply_accent_button(btn: tk.Button) -> None:
        f = theme.fonts()
        btn.configure(
            bg=theme.SIGNAL_BASE,
            fg=theme.INK_INVERSE,
            activebackground=theme.SIGNAL_HOVER,
            activeforeground=theme.INK_INVERSE,
            disabledforeground=theme.SURFACE_PAPER,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=f["body_bold"],
            padx=theme.SPACE_3,
            pady=theme.SPACE_1,
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

        for var in (self.selected_process, self.selected_profile):
            self._selection_trace_handles.append(var.trace_add("write", schedule_update))

    def load_settings(self) -> None:
        # Load settings
        s_file = Path("user_settings.json")
        self.settings, can_save_settings = load_user_settings(s_file)
        self.settings.language = normalize_language(self.settings.language)
        set_language(self.settings.language)
        if can_save_settings:
            save_user_settings(self.settings, s_file)
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
        if hasattr(self, "button_frame"):
            self.button_frame.refresh_texts()
        run_start_button = self.__dict__.get("run_start_button")
        if run_start_button is not None:
            self._apply_accent_button(run_start_button)
        if hasattr(self, "profile_button_frame"):
            self.profile_button_frame.refresh_texts()
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
                "{base}\nRuntime extra group: {trigger} ({state})",
                "{base}\n실행 중 추가 이벤트 묶음: {trigger} ({state})",
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
        self, profile: ProfileModel, events: list[EventModel]
    ) -> None:
        self._reset_runtime_toggle_session()
        toggle_key = normalize_runtime_toggle_trigger(
            getattr(profile, "runtime_toggle_key", None)
        )
        member_count = runtime_toggle_member_count(events)
        enabled = bool(
            getattr(profile, "runtime_toggle_enabled", False)
            and toggle_key
            and member_count > 0
            and not collect_runtime_toggle_validation_errors(
                profile,
                events,
                settings=getattr(self, "settings", None),
                os_name=platform.system(),
            )
        )
        self.runtime_toggle_enabled = enabled
        self.runtime_toggle_key = toggle_key
        self.runtime_toggle_member_count = member_count

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
                "Stop first if you want to change process, profile, or event settings.",
                "프로세스, 프로필, 이벤트 설정을 바꾸려면 먼저 중지하세요.",
            )
            if self.runtime_toggle_enabled and self.runtime_toggle_key:
                detail = txt(
                    "{detail}\nExtra group: {trigger} ({state})",
                    "{detail}\n추가 이벤트 묶음: {trigger} ({state})",
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

        if not self.selected_profile.get():
            return {
                "can_start": False,
                "badge_text": txt("Select Profile", "프로필 선택"),
                "title": txt(
                    "Select a profile with saved events.",
                    "저장된 이벤트가 있는 프로필을 선택하세요.",
                ),
                "detail": txt(
                    "Use Quick for fast capture or open Profile Manager to edit events.",
                    "빠른 캡처는 Quick을, 상세 편집은 프로필 편집을 사용하세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
            }

        try:
            profile = load_profile(
                self.profiles_dir, self.selected_profile.get(), migrate=False
            )
        except Exception as exc:
            return {
                "can_start": False,
                "badge_text": txt("Profile Error", "프로필 오류"),
                "title": txt(
                    "The selected profile could not be loaded.",
                    "선택한 프로필을 불러오지 못했습니다.",
                ),
                "detail": txt(
                    "Open the profile again or choose another profile.\nError: {error}",
                    "프로필을 다시 열거나 다른 프로필을 선택하세요.\n오류: {error}",
                    error=exc,
                ),
                "bg": STATUS_BG_ERR,
                "fg": STATUS_FG_ERR,
            }

        events = list(profile.event_list or [])
        runnable_events = self._runnable_events(events)
        duplicate_names = find_duplicate_event_names(events)
        if duplicate_names:
            dup_text = ", ".join(duplicate_names)
            return {
                "can_start": False,
                "badge_text": txt("Duplicate Events", "중복 이벤트"),
                "title": txt(
                    "Duplicate event names were found in this profile.",
                    "이 프로필에서 중복 이벤트 이름이 발견되었습니다.",
                ),
                "detail": txt(
                    "Rename duplicated event names before starting.\nDuplicates: {names}",
                    "시작하기 전에 중복 이벤트 이름을 변경하세요.\n중복: {names}",
                    names=dup_text,
                ),
                "bg": STATUS_BG_ERR,
                "fg": STATUS_FG_ERR,
            }
        enabled_count = sum(1 for evt in events if getattr(evt, "use_event", True))
        runnable_count = len(runnable_events)

        if not events:
            return {
                "can_start": False,
                "badge_text": txt("Add Events", "이벤트 추가"),
                "title": txt(
                    "This profile has no events yet.",
                    "이 프로필에는 아직 이벤트가 없습니다.",
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
                    "All events in this profile are disabled.",
                    "이 프로필의 모든 이벤트가 비활성화되어 있습니다.",
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

        toggle_validation_errors = collect_runtime_toggle_validation_errors(
            profile,
            events,
            settings=getattr(self, "settings", None),
            os_name=platform.system(),
        )
        if toggle_validation_errors:
            return {
                "can_start": False,
                "badge_text": txt("Toggle Conflict", "토글 충돌"),
                "title": txt(
                    "Runtime Event Group trigger settings need attention.",
                    "실행 중 추가 이벤트 묶음의 트리거 설정을 확인해야 합니다.",
                ),
                "detail": toggle_validation_errors[0],
                "bg": STATUS_BG_ERR,
                "fg": STATUS_FG_ERR,
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

        return {
            "can_start": True,
            "badge_text": txt("Ready", "준비 완료"),
            "title": txt(
                "Everything is ready to start monitoring.",
                "모니터링을 시작할 준비가 끝났습니다.",
            ),
            "detail": txt(
                "Profile '{name}' has {count} runnable event(s).",
                "프로필 '{name}'에 실행 가능한 이벤트가 {count}개 있습니다.",
                name=self.selected_profile.get(),
                count=runnable_count,
            ),
            "bg": STATUS_BG_INFO,
            "fg": STATUS_FG_INFO,
        }

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
        self.lbl_status_detail.config(text=snapshot["detail"])
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
        use_mac_polling = platform.system() == "Darwin" and (
            self.settings.toggle_start_stop_mac
            or (
                self.runtime_toggle_enabled
                and is_keyboard_runtime_toggle_trigger(runtime_toggle_trigger)
            )
        )
        if use_mac_polling:
            self.ctrl_check_active = True
            self._check_for_long_alt_shift()

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
        if should_listen_keyboard and not use_mac_polling:
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

    def _check_for_long_alt_shift(self) -> None:
        if not self.ctrl_check_active:
            return
        curr_time = time.time()
        try:
            start_stop_enabled = bool(
                platform.system() == "Darwin"
                and getattr(self.settings, "toggle_start_stop_mac", False)
            )
            curr_state = (
                start_stop_enabled
                and KeyUtils.mod_key_pressed("alt")
                and KeyUtils.mod_key_pressed("shift")
            )
            if start_stop_enabled and curr_state and not self._mac_alt_shift_state:
                self.toggle_start_stop()
            self._mac_alt_shift_state = curr_state

            runtime_toggle_pressed = (
                self.runtime_toggle_enabled
                and self.is_running.get()
                and self._target_process_is_active()
                and is_keyboard_runtime_toggle_trigger(self.runtime_toggle_key)
                and KeyUtils.key_pressed(self.runtime_toggle_key)
            )
            if (
                runtime_toggle_pressed
                and not self._mac_runtime_toggle_state
                and curr_time - self.last_runtime_toggle_time
                >= RUNTIME_TOGGLE_DEBOUNCE_SECONDS
            ):
                self.last_runtime_toggle_time = curr_time
                self.toggle_runtime_event_group()
            self._mac_runtime_toggle_state = bool(runtime_toggle_pressed)
        finally:
            self._mac_poll_after_id = self.after(50, self._check_for_long_alt_shift)

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
        if not messagebox.askokcancel(
            txt("Confirm", "확인"),
            txt("Delete old log files?", "오래된 로그 파일을 삭제하시겠습니까?"),
        ):
            return
        if not log_dir.exists():
            messagebox.showinfo(
                txt("Info", "안내"), txt("No logs.", "로그가 없습니다.")
            )
            return

        deleted_size, count = 0, 0
        for p in log_dir.glob("*"):
            if p.name != "keysym.log" and p.is_file():
                try:
                    deleted_size += p.stat().st_size
                    p.unlink()
                    count += 1
                except Exception as e:
                    logger.warning(f"Del failed {p}: {e}")

        msg = (
            txt(
                "{count} files cleared.\nSaved: {size:.2f} MB",
                "{count}개 파일을 정리했습니다.\n확보 용량: {size:.2f} MB",
                count=count,
                size=deleted_size / 1048576,
            )
            if count
            else txt("No old logs to clear.", "정리할 오래된 로그가 없습니다.")
        )
        messagebox.showinfo(
            txt("Success", "완료") if count else txt("Info", "안내"),
            msg,
        )

    def toggle_start_stop(self, event: object | None = None) -> None:
        if self.toggle_transition_in_progress:
            return
        self.toggle_transition_in_progress = True
        if not self.is_running.get():
            try:
                if self.start_simulation():
                    self.is_running.set(True)
                    self.update_ui()
                else:
                    self.update_ui()
            finally:
                self.toggle_transition_in_progress = False
            return

        try:
            self.is_running.set(False)
            self.stop_simulation()
        finally:
            self.toggle_transition_in_progress = False

    def start_simulation(self) -> bool:
        if not (
            self.selected_process.get()
            and "(" in self.selected_process.get()
            and self.selected_profile.get()
        ):
            return False

        try:
            profile = load_profile(
                self.profiles_dir, self.selected_profile.get(), migrate=True
            )
        except Exception:
            profile = ProfileModel()

        profile_events = list(profile.event_list or [])
        if find_duplicate_event_names(profile_events):
            return False
        if collect_runtime_toggle_validation_errors(
            profile,
            profile_events,
            settings=getattr(self, "settings", None),
            os_name=platform.system(),
        ):
            return False
        events = self._runnable_events(profile_events)
        if not events:
            return False
        self._configure_runtime_toggle_session(profile, events)

        self.terminate_event.clear()
        self.keystroke_processor = KeystrokeProcessor(
            self,
            self.selected_process.get(),
            events,
            profile.modification_keys or {},
            self.terminate_event,
        )
        if not self.keystroke_processor.event_data_list:
            self.keystroke_processor = None
            self._reset_runtime_toggle_session()
            return False

        # Keep the macOS Tk polling loop alive while Option+Shift is still held.
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
        self.profile_frame.copy_button.config(state=state)
        self.profile_frame.del_button.config(state=state)

        run_start_button = self.__dict__.get("run_start_button")
        if run_start_button is not None:
            run_start_button.config(
                text=txt("Stop", "중지") if running else txt("Start", "시작"),
                state="normal" if running or readiness["can_start"] else "disabled",
            )
            if running:
                run_start_button.configure(
                    bg=theme.STATUS_RUNNING_FG,
                    fg=theme.INK_INVERSE,
                    activebackground=theme.STATUS_ERROR_FG,
                    activeforeground=theme.INK_INVERSE,
                )
            else:
                run_start_button.configure(
                    bg=theme.SIGNAL_BASE,
                    fg=theme.INK_INVERSE,
                    activebackground=theme.SIGNAL_HOVER,
                    activeforeground=theme.INK_INVERSE,
                )
        self.button_frame.quick_events_button.config(state=state)
        self.button_frame.settings_button.config(state=state)
        self.button_frame.clear_logs_button.config(state=state)

        self.profile_button_frame.modkeys_button.config(state=state)
        self.profile_button_frame.edit_profile_button.config(state=state)
        self.profile_button_frame.sort_button.config(state=state)
        self._update_main_status()

    def open_modkeys(self) -> None:
        if self.is_running.get():
            return
        if self.selected_profile.get():
            ModificationKeysWindow(
                self, self.selected_profile.get(), profiles_dir=self.profiles_dir
            )

    def open_profile(self) -> None:
        if self.selected_profile.get():
            KeystrokeProfiles(
                self,
                self.selected_profile.get(),
                self.reload_profiles,
                profiles_dir=self.profiles_dir,
            )

    def reload_profiles(self, new_name: str) -> None:
        self.profile_frame.load_profiles(select_name=new_name)
        self.update_ui()

    def sort_profile_events(self) -> None:
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

    def _save_latest_state(self) -> None:
        StateUtils.save_main_app_state(
            process=self.selected_process.get().split(" (")[0],
            profile=self.selected_profile.get(),
        )

    def unbind_events(self) -> None:
        safe_call(self.unbind, "<Escape>")
        self.input_listener_session.stop()
        self.keyboard_listener = None
        self.start_stop_mouse_listener = None
        self.runtime_toggle_mouse_listener = None

        self.ctrl_check_active = False
        if self._mac_poll_after_id is not None:
            safe_call(self.after_cancel, self._mac_poll_after_id)
            self._mac_poll_after_id = None

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
