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
    HoverTip,
    ModKeySetFrame,
    ProcessFrame,
    RunTargetFrame,
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
    list_run_set_names,
    upsert_run_set,
)
from app.storage.profile_storage import (
    list_profile_names,
    load_profile,
)
from app.storage.settings_storage import load_user_settings, save_user_settings
from app.core.processor import KeystrokeProcessor
from app.ui.capture_hud import CaptureHud
from app.ui.workspace import Workspace
from app.ui.settings import KeystrokeSettings
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
    # One-line status text and the single fix action shown when blocked.
    summary: NotRequired[str]
    action: NotRequired[str]


def safe_call(func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R | None:
    """예외를 무시하고 함수 호출"""
    try:
        return func(*args, **kwargs)
    except Exception:
        return None



class KeystrokeSimulatorApp(tk.Tk):
    # Class-level default: Tk.__getattr__ recurses on instances without .tk.
    _quick_hud: CaptureHud | None = None
    _workspace: Workspace | None = None

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
        # Paper-tone root + ttk styles.
        self.configure(bg=theme.SURFACE_PAPER)
        try:
            ttk.Style(self).theme_use("default")
        except tk.TclError:
            pass
        theme.install_styles(self)
        f = theme.fonts()

        # --- Title bar with the ⚙ tools menu ---------------------------------
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
        # A plain Label: Aqua draws an up/down indicator on every Menubutton.
        self.tools_button: tk.Label = tk.Label(
            self.context_bar,
            text=theme.ICON_TOOLS,
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_SECONDARY,
            font=f["heading"],
            cursor="hand2",
            padx=theme.SPACE_1,
        )
        self.tools_button.pack(side=tk.RIGHT)
        self.tools_menu: tk.Menu = tk.Menu(self.tools_button, tearoff=0)
        self.tools_button.bind("<Button-1>", self._show_tools_menu)
        self._tools_menus: list[tk.Menu] = [self.tools_menu]
        if platform.system() == "Darwin":
            # macOS: the same tools live in the system menu bar.
            menubar = tk.Menu(self)
            self.menubar_tools: tk.Menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label=txt("Tools", "도구"), menu=self.menubar_tools)
            self.config(menu=menubar)
            self._tools_menus.append(self.menubar_tools)
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x", side="top")

        # --- Run dock (bottom, packed before body so it stays anchored) -------
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).pack(fill="x", side="bottom")
        self.run_dock: tk.Frame = tk.Frame(
            self,
            bg=theme.SURFACE_PAPER,
            padx=theme.SPACE_3,
            pady=theme.SPACE_3,
        )
        self.run_dock.pack(fill="x", side="bottom")

        self.body: tk.Frame = tk.Frame(
            self,
            bg=theme.SURFACE_PAPER,
            padx=theme.SPACE_3,
            pady=theme.SPACE_3,
        )
        self.body.pack(fill="both", expand=True, side="top")
        self.target_card: tk.Frame
        self.target_card, target_body = self._make_card(self.body, "")
        self.target_card.pack(fill="x")
        self.process_frame: ProcessFrame = ProcessFrame(target_body, self.selected_process)
        self.process_frame.configure(bg=theme.SURFACE_CANVAS)
        self.process_frame.pack(fill="x", pady=(0, theme.SPACE_1))
        self.run_target_frame: RunTargetFrame = RunTargetFrame(
            target_body,
            self.selected_profile,
            self.selected_run_set,
            profiles_dir=self.profiles_dir,
            sets_path=self.run_sets_path,
            edit_cb=self.open_workspace_for,
        )
        self.run_target_frame.configure(bg=theme.SURFACE_CANVAS)
        self.run_target_frame.pack(fill="x", pady=(0, theme.SPACE_1))
        self.modkey_set_frame: ModKeySetFrame = ModKeySetFrame(
            target_body,
            self.selected_modkey_set,
            sets_path=self.modkey_sets_path,
            edit_cb=self.open_modkeys,
        )
        self.modkey_set_frame.configure(bg=theme.SURFACE_CANVAS)
        self.modkey_set_frame.pack(fill="x")

        # --- Status: one line, plus one fix button only when blocked ---------
        status_row = tk.Frame(self.body, bg=theme.SURFACE_PAPER)
        status_row.pack(fill="x", pady=(theme.SPACE_3, 0))
        self.lbl_status_badge: tk.Label = tk.Label(
            status_row,
            bg=theme.STATUS_READY_BG,
            fg=theme.STATUS_READY_FG,
            font=f["body_bold"],
            padx=theme.SPACE_2,
            pady=theme.SPACE_1,
            anchor="w",
            justify="left",
        )
        self.lbl_status_badge.pack(side=tk.LEFT, fill="x", expand=True)
        self.status_tooltip = HoverTip(self.lbl_status_badge)
        self._status_action: str | None = None
        self.btn_status_fix: tk.Button = tk.Button(
            status_row, command=self._on_status_fix
        )
        self._apply_outline_button(self.btn_status_fix)

        for widget in (
            self.process_frame.lbl_process,
            self.run_target_frame.lbl_target,
            self.modkey_set_frame.lbl_sets,
        ):
            widget.configure(
                bg=theme.SURFACE_CANVAS,
                fg=theme.INK_SECONDARY,
                font=f["body"],
            )
        for btn in (self.process_frame.refresh_button, self.run_target_frame.edit_button):
            self._apply_outline_button(btn)

        # --- Run dock contents ------------------------------------------------
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

    # Tools menu entries: (key, en, ko, command, idle_only).
    def _tools_entries(self) -> list[tuple[str, str, str, VoidCallback, bool]]:
        return [
            ("workspace", "Open workspace…", "작업 공간 열기…", self.open_profile, False),
            ("quick", "Quick events…", "빠른 이벤트…", self.open_quick_events, True),
            ("sep", "", "", lambda: None, False),
            ("modkey_edit", "Edit modifier keys…", "수정키 세트 편집…", self.open_modkeys, True),
            ("modkey_copy", "Duplicate modifier keys", "수정키 세트 복사", self._copy_modkey_set, True),
            ("modkey_delete", "Delete modifier keys", "수정키 세트 삭제", self._delete_modkey_set, True),
            ("sep", "", "", lambda: None, False),
            ("settings", "Settings…", "설정…", self.open_settings, True),
            ("clear_logs", "Clear logs", "로그 삭제", self.clear_local_logs, True),
        ]

    def _show_tools_menu(self, _event: object | None = None) -> None:
        button = self.tools_button
        self.tools_menu.tk_popup(
            button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()
        )

    def _build_tools_menus(self) -> None:
        for menu in getattr(self, "_tools_menus", []):
            menu.delete(0, "end")
            for key, en, ko, command, _idle in self._tools_entries():
                if key == "sep":
                    menu.add_separator()
                else:
                    menu.add_command(label=txt(en, ko), command=command)

    def _sync_tools_menus(self, running: bool) -> None:
        for menu in self.__dict__.get("_tools_menus", []):
            for index, (key, _en, _ko, _cmd, idle_only) in enumerate(
                self._tools_entries()
            ):
                if key == "sep":
                    continue
                state = "disabled" if running and idle_only else "normal"
                safe_call(menu.entryconfigure, index, state=state)

    def _copy_modkey_set(self) -> None:
        self.modkey_set_frame.copy_set()
        self._update_main_status()

    def _delete_modkey_set(self) -> None:
        self.modkey_set_frame.delete_set()
        self._update_main_status()

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
        if title:
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
            pady=(theme.SPACE_1 if title else theme.SPACE_3, theme.SPACE_3),
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
            self.run_target_frame.set_target("profile", prof)
        self._restore_run_set_selection(state)
        modkey_set = state.get("modkey_set")
        if isinstance(modkey_set, str) and modkey_set:
            self.modkey_set_frame.set_selected_set(modkey_set)
        self.update_ui()

    def _refresh_ui_texts(self) -> None:
        if hasattr(self, "process_frame"):
            self.process_frame.refresh_texts()
        if hasattr(self, "run_target_frame"):
            self.run_target_frame.refresh_texts()
        if hasattr(self, "modkey_set_frame"):
            self.modkey_set_frame.refresh_texts()
        self._build_tools_menus()
        run_start_button = self.__dict__.get("run_start_button")
        if run_start_button is not None:
            self._apply_accent_button(run_start_button)
        if hasattr(self, "lbl_status_badge"):
            self._update_main_status()

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
                "{base}\nHotkey set: {trigger} ({state})",
                "{base}\n단축키 묶음: {trigger} ({state})",
                base=hint,
                trigger=display_runtime_toggle_trigger(self.runtime_toggle_key),
                state=toggle_state,
            )
        return hint

    def _hotkey_short(self) -> str:
        """시작 버튼에 붙이는 짧은 단축키 표시. 꺼져 있으면 빈 문자열."""
        settings = self.__dict__.get("settings")
        if settings is None:
            return ""
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

    def _restore_run_set_selection(self, state: dict[str, object]) -> None:
        """Restore a named run set, or migrate the legacy run_profiles list.

        Earlier versions stored the virtual "__current__" set for single-profile
        runs; that simply means the profile stays selected.
        """
        frame = self.__dict__.get("run_target_frame")
        if frame is None:
            return
        run_set = state.get("run_set")
        if isinstance(run_set, str) and run_set.strip():
            if not is_current_run_set(run_set):
                frame.set_target("run_set", run_set.strip())
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
                existing = set(frame.run_set_names)
                name = migrated
                n = 2
                while name in existing:
                    name = f"{migrated} {n}"
                    n += 1
                upsert_run_set(name, run_profiles, self.run_sets_path)
                frame.load(select=("run_set", name))
            except Exception as exc:
                logger.warning(f"Legacy run profile migration failed: {exc}")
            return

    def _get_run_profile_names(self) -> list[str]:
        frame = self.__dict__.get("run_target_frame")
        if frame is not None:
            names = frame.get_run_profiles()
            if names:
                return names
        selected = self.selected_profile.get()
        return [selected] if selected else []

    def _run_set_status_label(self) -> str:
        """Short label for status lines: the profile, or the named set."""
        set_id = (self.selected_run_set.get() or "").strip()
        if set_id and not is_current_run_set(set_id):
            return txt("Set {name}", "세트 {name}", name=set_id)
        return (self.selected_profile.get() or "—").strip() or "—"

    def _run_target_label(self, profile_names: list[str] | None = None) -> str:
        """"BM_야수" 또는 "세트 레이드 (프로필 2개)"."""
        target = self._run_set_status_label()
        members = self._run_set_members_status_label(profile_names)
        return target if members in ("—", target) else f"{target} ({members})"

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
                "Stop to change the target, run or modifier keys. Workspace edits apply from the next start.",
                "대상·실행·수정키를 바꾸려면 중지하세요. 작업 공간 편집은 다음 시작부터 반영됩니다.",
            )
            summary = self._run_target_label()
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
                    "Pick the process you want to watch in the Target list.",
                    "감시할 대상을 대상 목록에서 고르세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
                "action": "process",
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
                    "Choose a profile or a run set in the Run list.",
                    "실행 목록에서 프로필이나 실행 세트를 고르세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
                "action": "workspace",
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
                "bg": STATUS_BG_ERR,
                "fg": STATUS_FG_ERR,
                "action": "workspace",
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
                "title": txt("Nothing to run yet.", "실행할 이벤트가 아직 없습니다."),
                "detail": txt(
                    "Add at least one event in the workspace or with Quick events.",
                    "작업 공간이나 빠른 이벤트에서 이벤트를 하나 이상 추가하세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
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
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
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
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
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
                "bg": STATUS_BG_ERR,
                "fg": STATUS_FG_ERR,
                "missing_permissions": missing_permissions,
                "action": "permissions",
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
                    "Open the workspace and capture a screen for events missing one.",
                    "작업 공간에서 화면이 빠진 이벤트를 다시 캡처하세요.",
                ),
                "bg": STATUS_BG_WARN,
                "fg": STATUS_FG_WARN,
                "action": "workspace",
            }

        target_label = self._run_target_label(list(session.profile_names))
        modkey_set_name = self.selected_modkey_set.get() or DEFAULT_MODKEY_SET_NAME
        rules = sum(1 for evt in runnable_events if evt.execute_action)
        signals = len(runnable_events) - rules
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
            "bg": STATUS_BG_OK,
            "fg": STATUS_FG_OK,
        }

    def _status_detail_with_selection(self, detail: str) -> str:
        """Append the run target + modkey set when not already present."""
        profile_name = (self.selected_profile.get() or "").strip()
        modkey_set_name = (self.selected_modkey_set.get() or "").strip()
        if not profile_name and not modkey_set_name:
            return detail
        if "Modifier keys " in detail or "수정키 " in detail:
            return detail
        line = txt(
            "Run {target} · Modifier keys {modkey_set}",
            "실행 {target} · 수정키 {modkey_set}",
            target=self._run_target_label(),
            modkey_set=modkey_set_name or "—",
        )
        return f"{detail}\n{line}" if detail else line

    def _update_main_status(self) -> None:
        """상태는 한 줄. 막혔을 때만 해결 버튼 하나를 보인다."""
        if not hasattr(self, "lbl_status_badge"):
            return
        snapshot = self._get_readiness_snapshot()
        bg: str = snapshot["bg"]
        fg: str = snapshot["fg"]
        running = self.is_running.get()
        if running:
            bg, fg = STATUS_BG_RUN, STATUS_FG_RUN
        icon = self._icon_for_status(bg, running)
        summary = snapshot.get("summary") or snapshot["title"]
        self.lbl_status_badge.config(
            text=f"{icon}  {snapshot['badge_text']} · {summary}",
            bg=bg,
            fg=fg,
        )
        tooltip = self.__dict__.get("status_tooltip")
        if tooltip is not None:
            hint = self._get_hotkey_hint_text()
            detail = self._status_detail_with_selection(snapshot["detail"])
            tooltip.update_text(f"{detail}\n{hint}" if hint else detail)
        action = None if running else snapshot.get("action")
        self._status_action = action
        fix = self.__dict__.get("btn_status_fix")
        if fix is not None:
            if action:
                fix.config(text=self._status_action_label(action))
                fix.pack(side=tk.RIGHT, padx=(theme.SPACE_2, 0))
            else:
                fix.pack_forget()
        self._missing_permissions = list(snapshot.get("missing_permissions", []))
        if hasattr(self, "lbl_run_status"):
            self.lbl_run_status.config(text=self._run_dock_text(snapshot, running))

    @staticmethod
    def _status_action_label(action: str) -> str:
        return {
            "permissions": txt("Open settings", "권한 설정 열기"),
            "process": txt("Refresh", "새로고침"),
        }.get(action, txt("Open workspace", "작업 공간에서 보기"))

    def _on_status_fix(self) -> None:
        action = getattr(self, "_status_action", None)
        if action == "permissions":
            missing = getattr(self, "_missing_permissions", [])
            if missing:
                self._open_macos_permission_setting(missing[0])
        elif action == "process":
            self.process_frame.refresh_processes()
        elif action == "workspace":
            self.open_profile()

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
        """상태 줄과 겹치지 않게, 실행 중 멈추는 방법만 알린다."""
        if running:
            return txt(
                "Press the hotkey or Stop to halt.",
                "단축키나 중지로 멈춥니다.",
            )
        return ""

    def setup_event_handlers(self) -> None:
        self.unbind_events()
        self.input_listener_session.start()
        # Esc는 앱을 끄지 않는다(M-05). 창 닫기로만 종료한다.
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
        # 빠른 캡처 HUD는 모달이 아니다. 실행 중 전역 CTRL을 캡처·저장으로
        # 받지 않도록 실행 전에 닫는다.
        quick_hud = self._quick_hud
        if quick_hud is not None and quick_hud.is_open():
            quick_hud.close()
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
            logger.warning(f"Modifier key set load failed for '{set_name}': {exc}")
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
        return True

    def update_ui(self) -> None:
        running = self.is_running.get()
        state = "disabled" if running else "normal"
        readonly_state = "disabled" if running else "readonly"
        readiness = self._get_readiness_snapshot()

        self.process_frame.process_combobox.config(state=readonly_state)
        self.process_frame.refresh_button.config(state=state)
        self.run_target_frame.combobox.config(state=readonly_state)
        # 작업 공간은 실행 중에도 연다. 편집은 다음 시작부터 반영된다.
        self.run_target_frame.edit_button.config(state="normal")
        self.modkey_set_frame.sets_combobox.config(state=readonly_state)
        self._sync_tools_menus(running)

        run_start_button = self.__dict__.get("run_start_button")
        if run_start_button is not None:
            can_press = bool(running or readiness["can_start"])
            self._run_start_enabled = can_press
            label = (
                f"{theme.ICON_STOP} {txt('Stop', '중지')}"
                if running
                else f"{theme.ICON_START} {txt('Start', '시작')}"
            )
            if hotkey := self._hotkey_short():
                label = f"{label}  {hotkey}"
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
        workspace = self._workspace
        if workspace is not None and workspace.is_open():
            workspace.set_running(running)
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
        """작업 공간을 연다. 모달이 아니며 실행 중에도 편집할 수 있다."""
        frame = self.__dict__.get("run_target_frame")
        if frame is not None:
            self.open_workspace_for(frame.get_target())
            return
        self._open_workspace(profile=self.selected_profile.get() or None)

    def open_workspace_for(self, target: tuple[str, str]) -> None:
        """"편집…": 실행 콤보에서 고른 프로필이나 실행 세트로 연다(M-06)."""
        kind, name = target
        if kind == "run_set":
            self._open_workspace(profile=self.selected_profile.get() or None, run_set=name)
        else:
            self._open_workspace(profile=name or None)

    def _open_workspace(
        self, *, profile: str | None = None, run_set: str | None = None
    ) -> None:
        workspace = self._workspace
        if workspace is not None and workspace.is_open():
            if run_set:
                workspace.select_item("run_set", run_set)
            elif profile:
                workspace.select_item("profile", profile)
            return
        self._workspace = Workspace(
            self,
            profiles_dir=self.profiles_dir,
            run_sets_path=self.run_sets_path,
            running_getter=self.is_running.get,
            settings_getter=lambda: getattr(self, "settings", None),
            on_catalog_changed=self.reload_profiles,
            on_run_set_renamed=self._on_run_set_renamed,
            on_close=self._on_workspace_closed,
            profile=profile,
            run_set=run_set,
        )

    def _on_run_set_renamed(self, old: str, new: str) -> None:
        """고른 실행 세트의 이름이 바뀌면 새 이름을 계속 고른다."""
        if (self.selected_run_set.get() or "").strip() == old:
            self.selected_run_set.set(new)

    def _on_workspace_closed(self) -> None:
        self._workspace = None
        self.reload_profiles(None)

    def reload_profiles(self, new_name: str | None) -> None:
        """작업 공간에서 프로필·실행 세트가 바뀌면 실행 콤보를 다시 읽는다.
        고른 프로필이 사라졌을 때만(이름 변경) 새 이름으로 옮긴다."""
        frame = self.run_target_frame
        kind, name = frame.get_target()
        if kind == "profile" and new_name and name not in list_profile_names(self.profiles_dir):
            name = new_name
        if kind == "run_set" and name not in list_run_set_names(self.run_sets_path):
            kind, name = "profile", self.selected_profile.get()
        frame.load(select=(kind, name))
        self.update_ui()

    def open_quick_events(self) -> None:
        if self.is_running.get():
            return
        # HUD는 모달이 아니므로 두 번 열지 않고 기존 창을 앞으로 가져온다.
        existing = self._quick_hud
        if existing is not None and existing.is_open():
            safe_call(cast(Any, existing.win).lift)
            return
        self._quick_hud = CaptureHud(
            self,
            mode="continuous",
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
