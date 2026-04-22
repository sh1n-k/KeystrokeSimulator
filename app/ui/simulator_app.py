import json
import os
import platform
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from dataclasses import fields, asdict
from pathlib import Path
from tkinter import ttk, messagebox

from loguru import logger
import pynput.keyboard
import pynput.mouse
from app.utils.i18n import dual_text_width, normalize_language, set_language, txt

from app.core.validation import (
    find_duplicate_event_names,
    runtime_toggle_validation_errors,
)
from app.core.models import ProfileModel, EventModel, UserSettings
from app.ui.modkeys import ModificationKeysWindow
from app.storage.profile_storage import (
    copy_profile as copy_profile_storage,
    delete_profile_files,
    ensure_quick_profile,
    list_profile_names,
    load_profile_favorites,
    load_profile,
    load_profile_meta_favorite,
)
from app.core.processor import KeystrokeProcessor
from app.ui.profiles import KeystrokeProfiles
from app.ui.quick_event_editor import KeystrokeQuickEventEditor
from app.ui.settings import KeystrokeSettings
from app.ui.sort_events import KeystrokeSortEvents
from app.utils.sounds import SoundPlayer
from app.storage.profile_display import QUICK_PROFILE_NAME, build_profile_display_values
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
    is_supported_runtime_toggle_trigger,
    is_wheel_runtime_toggle_trigger,
    normalize_runtime_toggle_listener_key,
    normalize_runtime_toggle_trigger,
    runtime_toggle_member_count,
)
from app.utils.system import (
    ProcessUtils,
    PermissionUtils,
    StateUtils,
    WindowUtils,
    KeyUtils,
    ProcessCollector,
)

STATUS_BG_INFO = "#eef3ff"
STATUS_FG_INFO = "#1e3a8a"
STATUS_BG_OK = "#e6f4ea"
STATUS_FG_OK = "#1e5f3a"
STATUS_BG_WARN = "#fff4cc"
STATUS_FG_WARN = "#7a5b00"
STATUS_BG_ERR = "#fdecea"
STATUS_FG_ERR = "#9f1f1f"


def safe_call(func, *args, **kwargs):
    """예외를 무시하고 함수 호출"""
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


class ProcessFrame(tk.Frame):
    def __init__(self, master, textvariable, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.lbl_process = tk.Label(self)
        self.lbl_process.pack(side=tk.LEFT, padx=5)
        self.process_combobox = ttk.Combobox(
            self, textvariable=textvariable, state="readonly"
        )
        self.process_combobox.pack(side=tk.LEFT, padx=5)
        self.refresh_button = tk.Button(self, command=self.refresh_processes)
        self.refresh_button.pack(side=tk.LEFT)
        self.refresh_texts()
        self.refresh_processes()

    def refresh_texts(self):
        self.lbl_process.config(text=txt("Process:", "프로세스:"))
        self.refresh_button.config(
            text=txt("Refresh", "새로고침"),
            width=dual_text_width("Refresh", "새로고침", padding=2, min_width=8),
        )

    def refresh_processes(self):
        curr_val = self.process_combobox.get()
        curr_name = (
            curr_val.rsplit(" (", 1)[0] if curr_val and "(" in curr_val else None
        )

        procs = sorted(ProcessCollector.get(), key=lambda x: x[0].lower())
        self.process_combobox["values"] = [f"{n} ({p})" for n, p, _ in procs]

        idx = next((i for i, (n, _, _) in enumerate(procs) if n == curr_name), 0)
        if procs:
            self.process_combobox.current(idx)
            self.process_combobox.event_generate("<<ComboboxSelected>>")


class ProfileFrame(tk.Frame):
    def __init__(self, master, textvariable, profiles_dir, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.profiles_dir = Path(profiles_dir)
        self.selected_profile_var = textvariable
        self.profile_display_var = tk.StringVar()
        self.profile_names = []
        self.name_to_index = {}
        self.favorite_names = set()
        self._profile_favorite_cache = {}

        self._normal_font = tkfont.nametofont("TkTextFont").copy()
        self._bold_font = tkfont.nametofont("TkTextFont").copy()
        self._bold_font.configure(weight="bold")

        self.lbl_profiles = tk.Label(self)
        self.lbl_profiles.pack(side=tk.LEFT, padx=5)
        self.profile_combobox = ttk.Combobox(
            self, textvariable=self.profile_display_var, state="readonly"
        )
        self.profile_combobox.pack(side=tk.LEFT, padx=5)
        self.profile_combobox.bind(
            "<<ComboboxSelected>>",
            self._on_profile_selected,
        )
        self.copy_button = tk.Button(self, command=self.copy_profile)
        self.copy_button.pack(side=tk.LEFT)
        self.del_button = tk.Button(self, command=self.delete_profile)
        self.del_button.pack(side=tk.LEFT)
        self.refresh_texts()
        self.load_profiles()

    def _apply_selected_profile_font(self, profile_name: str):
        font = (
            self._bold_font
            if profile_name in self.favorite_names
            and profile_name != QUICK_PROFILE_NAME
            else self._normal_font
        )
        self.profile_combobox.configure(font=font)

    def _on_profile_selected(self, _event=None):
        idx = self.profile_combobox.current()
        if not (0 <= idx < len(self.profile_names)):
            return
        profile_name = self.profile_names[idx]
        self.selected_profile_var.set(profile_name)
        self._apply_selected_profile_font(profile_name)

    def set_selected_profile(self, profile_name: str) -> bool:
        idx = self.name_to_index.get(profile_name)
        if idx is None:
            return False
        self.profile_combobox.current(idx)
        self._on_profile_selected()
        return True

    def get_selected_profile_name(self) -> str:
        idx = self.profile_combobox.current()
        if 0 <= idx < len(self.profile_names):
            return self.profile_names[idx]
        return self.selected_profile_var.get()

    def load_profiles(self, select_name: str | None = None):
        started = time.perf_counter()
        self.profiles_dir.mkdir(exist_ok=True)
        ensure_quick_profile(self.profiles_dir)

        names = [
            name
            for name in list_profile_names(self.profiles_dir)
            if name != QUICK_PROFILE_NAME
        ]
        favs, non_favs = [], []
        favorite_map = {}
        try:
            favorite_map = load_profile_favorites(self.profiles_dir, names)
        except Exception as e:
            logger.warning(f"Favorite map load failed: {e}")

        for name in names:
            try:
                is_favorite = favorite_map.get(name)
                if is_favorite is None:
                    is_favorite = load_profile_meta_favorite(self.profiles_dir, name)
                (favs if is_favorite else non_favs).append(name)
            except Exception as e:
                logger.warning(f"Load failed {name}: {e}")
                non_favs.append(name)

        self.favorite_names = set(favs)
        sorted_profiles = [QUICK_PROFILE_NAME] + sorted(favs) + sorted(non_favs)
        self.profile_names = sorted_profiles
        self.name_to_index = {name: idx for idx, name in enumerate(sorted_profiles)}

        self.profile_combobox["values"] = build_profile_display_values(
            sorted_profiles,
            self.favorite_names,
            quick_profile_name=QUICK_PROFILE_NAME,
        )

        if not sorted_profiles:
            self.selected_profile_var.set("")
            self.profile_display_var.set("")
            self._apply_selected_profile_font("")
            return

        target_name = (
            select_name or self.selected_profile_var.get() or QUICK_PROFILE_NAME
        )
        if not self.set_selected_profile(target_name):
            self.profile_combobox.current(0)
            self._on_profile_selected()
        if os.getenv("KEYSIM_PROFILE_PERF") == "1":
            print(
                f"[perf] load_profiles: {(time.perf_counter() - started) * 1000.0:.3f}ms"
            )

    def refresh_texts(self):
        self.lbl_profiles.config(text=txt("Profiles:", "프로필:"))
        self.copy_button.config(
            text=txt("Copy", "복사"),
            width=dual_text_width("Copy", "복사", padding=2, min_width=9),
        )
        self.del_button.config(
            text=txt("Delete", "삭제"),
            width=dual_text_width("Delete", "삭제", padding=2, min_width=9),
        )

    def copy_profile(self):
        if not (curr := self.get_selected_profile_name()):
            return
        dst_name = f"{curr} - Copied"
        if (self.profiles_dir / f"{dst_name}.json").exists():
            messagebox.showwarning(
                txt("Warning", "경고"),
                txt(
                    "Profile '{name}' already exists.",
                    "'{name}' 프로필이 이미 존재합니다.",
                    name=dst_name,
                ),
                parent=self,
            )
            return
        try:
            copy_profile_storage(self.profiles_dir, curr, dst_name)
            self.load_profiles(select_name=dst_name)
            messagebox.showinfo(
                txt("Profile Copied", "프로필 복사 완료"),
                txt(
                    "Copied '{src}' to '{dst}' and selected it.",
                    "'{src}' 프로필을 '{dst}'(으)로 복사하고 선택했습니다.",
                    src=curr,
                    dst=dst_name,
                ),
                parent=self,
            )
        except Exception as e:
            messagebox.showerror(
                txt("Error", "오류"),
                txt("Copy failed: {error}", "복사 실패: {error}", error=e),
                parent=self,
            )

    def delete_profile(self):
        curr = self.get_selected_profile_name()
        if not curr:
            return
        if curr == QUICK_PROFILE_NAME:
            messagebox.showinfo(
                txt("Info", "안내"),
                txt(
                    "The default profile cannot be deleted.",
                    "기본 프로필은 삭제할 수 없습니다.",
                ),
                parent=self,
            )
            return
        if messagebox.askokcancel(
            txt("Warning", "경고"),
            txt(
                "Delete profile '{name}'?",
                "프로필 '{name}'을(를) 삭제하시겠습니까?",
                name=curr,
            ),
            parent=self,
        ):
            delete_profile_files(self.profiles_dir, curr)
            self.load_profiles()
            messagebox.showinfo(
                txt("Profile Deleted", "프로필 삭제 완료"),
                txt(
                    "Deleted '{name}'.",
                    "'{name}' 프로필을 삭제했습니다.",
                    name=curr,
                ),
                parent=self,
            )


class ButtonFrame(tk.Frame):
    def __init__(self, master, toggle_cb, events_cb, settings_cb, clear_cb, **kwargs):
        super().__init__(master, **kwargs)
        btns_config = [
            ("start", ("Start", "시작"), toggle_cb),
            ("quick_events", ("Quick Events", "빠른 이벤트"), events_cb),
            ("settings", ("Settings", "설정"), settings_cb),
            ("clear_logs", ("Clear Logs", "로그 삭제"), clear_cb),
        ]
        self.btns = {}
        for key, label_pair, cmd in btns_config:
            btn = tk.Button(
                self,
                text=txt(*label_pair),
                width=dual_text_width(*label_pair, padding=2, min_width=9),
                height=1,
                command=cmd,
            )
            btn.pack(side=tk.LEFT, padx=5)
            self.btns[key] = btn
        self.start_stop_button = self.btns["start"]
        self.quick_events_button = self.btns["quick_events"]
        self.settings_button = self.btns["settings"]
        self.clear_logs_button = self.btns["clear_logs"]

    def refresh_texts(self):
        for key, label_pair in {
            "start": ("Start", "시작"),
            "quick_events": ("Quick Events", "빠른 이벤트"),
            "settings": ("Settings", "설정"),
            "clear_logs": ("Clear Logs", "로그 삭제"),
        }.items():
            self.btns[key].config(
                text=txt(*label_pair),
                width=dual_text_width(*label_pair, padding=2, min_width=9),
            )


class ProfileButtonFrame(tk.Frame):
    def __init__(self, master, mod_cb, edit_cb, sort_cb, **kwargs):
        super().__init__(master, **kwargs)
        btns_config = [
            ("modkeys", ("ModKeys", "수정키"), mod_cb),
            ("edit_profile", ("Edit Profile", "프로필 편집"), edit_cb),
            ("sort_profile", ("Sort Profile", "프로필 정렬"), sort_cb),
        ]
        self.btns = {}
        for key, label_pair, cmd in btns_config:
            btn = tk.Button(
                self,
                text=txt(*label_pair),
                width=dual_text_width(*label_pair, padding=2, min_width=9),
                height=1,
                command=cmd,
            )
            btn.pack(side=tk.LEFT, padx=5)
            self.btns[key] = btn
        self.settings_button = self.btns["edit_profile"]
        self.modkeys_button = self.btns["modkeys"]
        self.sort_button = self.btns["sort_profile"]

    def refresh_texts(self):
        for key, label_pair in {
            "modkeys": ("ModKeys", "수정키"),
            "edit_profile": ("Edit Profile", "프로필 편집"),
            "sort_profile": ("Sort Profile", "프로필 정렬"),
        }.items():
            self.btns[key].config(
                text=txt(*label_pair),
                width=dual_text_width(*label_pair, padding=2, min_width=9),
            )


class KeystrokeSimulatorApp(tk.Tk):
    def __init__(self, secure_callback=None):
        super().__init__()
        self.secure_callback = secure_callback
        self.title("Python 3.12")
        self.profiles_dir = "profiles"
        self.is_running = tk.BooleanVar(value=False)
        self.selected_process = tk.StringVar()
        self.selected_profile = tk.StringVar()
        self.keystroke_processor = None
        self.terminate_event = threading.Event()
        self.settings_window = None
        self.latest_scroll_time = None
        self.sound_player = SoundPlayer()

        # Input Listeners
        self.start_stop_mouse_listener = None
        self.runtime_toggle_mouse_listener = None
        self.keyboard_listener = None
        self.alt_pressed = False
        self.shift_pressed = False
        self.last_alt_shift_toggle_time = 0
        self.ctrl_check_thread = None
        self.ctrl_check_active = False
        self._selection_trace_handles = []
        self.runtime_toggle_enabled = False
        self.runtime_toggle_key = None
        self.runtime_toggle_active = False
        self.runtime_toggle_member_count = 0
        self.last_runtime_toggle_time = 0
        self.latest_runtime_scroll_time = None
        self.toggle_transition_in_progress = False

        self._create_ui()
        self._bind_selection_traces()
        self._load_settings_and_state()
        self._setup_event_handlers()
        self._update_ui()

    def _create_ui(self):
        self.status_frame = tk.LabelFrame(self, padx=10, pady=8)
        self.status_frame.pack(fill="x", padx=10, pady=(10, 5))

        self.lbl_status_badge = tk.Label(
            self.status_frame,
            relief="groove",
            borderwidth=1,
            padx=8,
            pady=2,
        )
        self.lbl_status_badge.pack(anchor="w")
        self.lbl_status_title = tk.Label(
            self.status_frame,
            font=tkfont.nametofont("TkHeadingFont")
            if "TkHeadingFont" in tkfont.names()
            else tkfont.nametofont("TkDefaultFont"),
            anchor="w",
            justify="left",
        )
        self.lbl_status_title.pack(anchor="w", pady=(6, 2))
        self.lbl_status_detail = tk.Label(
            self.status_frame,
            anchor="w",
            justify="left",
            fg="#555555",
            wraplength=560,
        )
        self.lbl_status_detail.pack(anchor="w")
        self.lbl_hotkey_hint = tk.Label(
            self.status_frame,
            anchor="w",
            justify="left",
            fg="#666666",
            wraplength=560,
        )
        self.lbl_hotkey_hint.pack(anchor="w", pady=(4, 0))

        self.process_frame = ProcessFrame(self, self.selected_process)
        self.profile_frame = ProfileFrame(
            self, self.selected_profile, self.profiles_dir
        )
        self.button_frame = ButtonFrame(
            self,
            self.toggle_start_stop,
            self.open_quick_events,
            self.open_settings,
            self.clear_local_logs,
        )
        self.profile_button_frame = ProfileButtonFrame(
            self, self.open_modkeys, self.open_profile, self.sort_profile_events
        )

        for f in (
            self.process_frame,
            self.profile_frame,
            self.button_frame,
            self.profile_button_frame,
        ):
            f.pack(pady=5)

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TEntry", fieldbackground="white")
        self._refresh_ui_texts()
        WindowUtils.center_window(self)

    def _bind_selection_traces(self):
        for var in (self.selected_process, self.selected_profile):
            self._selection_trace_handles.append(
                var.trace_add("write", lambda *_: self.after_idle(self._update_ui))
            )

    def _load_settings_and_state(self):
        # Load settings
        s_file = Path("user_settings.json")
        valid_keys = {f.name for f in fields(UserSettings)}
        try:
            data = (
                json.loads(s_file.read_text(encoding="utf-8"))
                if s_file.exists()
                else {}
            )
            self.settings = UserSettings(
                **{k: v for k, v in data.items() if k in valid_keys}
            )
        except Exception:
            self.settings = UserSettings()
        self.settings.language = normalize_language(
            getattr(self.settings, "language", None)
        )
        set_language(self.settings.language)
        s_file.write_text(json.dumps(asdict(self.settings), indent=2), encoding="utf-8")
        self._refresh_ui_texts()

        # Load state
        state = StateUtils.load_main_app_state() or {}
        if proc := state.get("process"):
            match = next(
                (
                    p
                    for p in self.process_frame.process_combobox["values"]
                    if p.startswith(proc)
                ),
                None,
            )
            if match:
                self.selected_process.set(match)
        if prof := state.get("profile"):
            self.profile_frame.set_selected_profile(prof)
        self._update_ui()

    def _refresh_ui_texts(self):
        if hasattr(self, "status_frame"):
            self.status_frame.config(text=txt("Ready Check", "실행 준비"))
        if hasattr(self, "process_frame"):
            self.process_frame.refresh_texts()
        if hasattr(self, "profile_frame"):
            self.profile_frame.refresh_texts()
        if hasattr(self, "button_frame"):
            self.button_frame.refresh_texts()
        if hasattr(self, "profile_button_frame"):
            self.profile_button_frame.refresh_texts()
        if hasattr(self, "lbl_hotkey_hint"):
            self.lbl_hotkey_hint.config(text=self._get_hotkey_hint_text())
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
                "{base}\nRuntime extra group: {trigger} ({state})",
                "{base}\n실행 중 추가 이벤트 묶음: {trigger} ({state})",
                base=hint,
                trigger=display_runtime_toggle_trigger(self.runtime_toggle_key),
                state=toggle_state,
            )
        return hint

    @staticmethod
    def _listener_key_name(key) -> str:
        return normalize_runtime_toggle_listener_key(key)

    def _selected_process_pid(self) -> int | None:
        pid_match = re.search(r"\((\d+)\)", self.selected_process.get())
        return int(pid_match.group(1)) if pid_match else None

    def _target_process_is_active(self) -> bool:
        return ProcessUtils.is_process_active(self._selected_process_pid())

    def _reset_runtime_toggle_session(self):
        self.runtime_toggle_enabled = False
        self.runtime_toggle_key = None
        self.runtime_toggle_active = False
        self.runtime_toggle_member_count = 0
        self.latest_runtime_scroll_time = None

    def _runtime_toggle_conflicts_with_start_stop(self, toggle_key: str | None) -> bool:
        profile = ProfileModel(
            runtime_toggle_enabled=True,
            runtime_toggle_key=toggle_key,
        )
        return bool(
            runtime_toggle_validation_errors(
                profile,
                [],
                settings=getattr(self, "settings", None),
                os_name=platform.system(),
            )
        )

    def _runtime_toggle_validation_errors(
        self, profile: ProfileModel, events: list[EventModel]
    ) -> list[str]:
        return runtime_toggle_validation_errors(
            profile,
            events,
            settings=getattr(self, "settings", None),
            os_name=platform.system(),
        )

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
            and not self._runtime_toggle_validation_errors(profile, events)
        )
        self.runtime_toggle_enabled = enabled
        self.runtime_toggle_key = toggle_key
        self.runtime_toggle_member_count = member_count

    @staticmethod
    def _find_duplicate_event_names(events: list[EventModel]) -> list[str]:
        return find_duplicate_event_names(events)

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

    def _get_readiness_snapshot(self) -> dict[str, object]:
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
                Path(self.profiles_dir), self.selected_profile.get(), migrate=False
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
        duplicate_names = self._find_duplicate_event_names(events)
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

        toggle_validation_errors = self._runtime_toggle_validation_errors(
            profile, events
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
            missing_labels = []
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

    def _update_main_status(self):
        if not hasattr(self, "lbl_status_badge"):
            return
        snapshot = self._get_readiness_snapshot()
        self.lbl_status_badge.config(
            text=snapshot["badge_text"],
            bg=snapshot["bg"],
            fg=snapshot["fg"],
        )
        self.lbl_status_title.config(text=snapshot["title"])
        self.lbl_status_detail.config(text=snapshot["detail"])
        self.lbl_hotkey_hint.config(text=self._get_hotkey_hint_text())

    def _setup_event_handlers(self):
        self.unbind_events()
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
            self.ctrl_check_thread = threading.Thread(
                target=self._check_for_long_alt_shift, daemon=True
            )
            self.ctrl_check_thread.start()

        key = self.settings.start_stop_key
        if key.startswith("W_"):
            self.start_stop_mouse_listener = pynput.mouse.Listener(
                on_scroll=self._on_mouse_scroll
            )
            self.start_stop_mouse_listener.start()

        if self.runtime_toggle_enabled and (
            is_wheel_runtime_toggle_trigger(runtime_toggle_trigger)
            or is_mouse_button_runtime_toggle_trigger(runtime_toggle_trigger)
        ):
            self.runtime_toggle_mouse_listener = pynput.mouse.Listener(
                on_scroll=self._on_runtime_toggle_mouse_scroll,
                on_click=self._on_runtime_toggle_mouse_click,
            )
            self.runtime_toggle_mouse_listener.start()

        should_listen_keyboard = (
            (
                self.runtime_toggle_enabled
                and is_keyboard_runtime_toggle_trigger(runtime_toggle_trigger)
            )
            or (platform.system() == "Windows" and self.settings.use_alt_shift_hotkey)
            or (key != "DISABLED" and not key.startswith("W_"))
        )
        if should_listen_keyboard and not use_mac_polling:
            self.keyboard_listener = pynput.keyboard.Listener(
                on_press=self._on_key_press, on_release=self._on_key_release
            )
            self.keyboard_listener.start()

    def _on_key_press(self, key):
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
            self.after(0, self.toggle_start_stop)
            return

        key_str = self._listener_key_name(key)
        if self._should_toggle_runtime_group(key_str, now):
            self.last_runtime_toggle_time = now
            self.after(0, self.toggle_runtime_event_group)
            return

        if self._should_toggle_start_stop(key_str):
            self.after(0, self.toggle_start_stop)

    def _on_key_release(self, key):
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

    def _check_for_long_alt_shift(self):
        last_state, last_time = False, 0
        last_runtime_toggle_state = False
        idle_sleep = 0.01
        while self.ctrl_check_active:
            try:
                curr_time = time.time()
                if curr_time - last_time < 0.1:
                    time.sleep(idle_sleep)
                    continue

                start_stop_enabled = bool(
                    platform.system() == "Darwin"
                    and getattr(self.settings, "toggle_start_stop_mac", False)
                )
                curr_state = (
                    start_stop_enabled
                    and KeyUtils.mod_key_pressed("alt")
                    and KeyUtils.mod_key_pressed("shift")
                )
                if start_stop_enabled and curr_state and not last_state:
                    self.after(0, self.toggle_start_stop)
                    last_time = curr_time
                    idle_sleep = 0.01
                last_state = curr_state

                runtime_toggle_pressed = (
                    self.runtime_toggle_enabled
                    and self.is_running.get()
                    and self._target_process_is_active()
                    and is_keyboard_runtime_toggle_trigger(self.runtime_toggle_key)
                    and KeyUtils.key_pressed(self.runtime_toggle_key)
                )
                if (
                    runtime_toggle_pressed
                    and not last_runtime_toggle_state
                    and curr_time - self.last_runtime_toggle_time
                    >= RUNTIME_TOGGLE_DEBOUNCE_SECONDS
                ):
                    self.last_runtime_toggle_time = curr_time
                    self.after(0, self.toggle_runtime_event_group)
                last_runtime_toggle_state = bool(runtime_toggle_pressed)

                idle_sleep = 0.01 if curr_state else min(0.05, idle_sleep + 0.005)
                time.sleep(idle_sleep)
            except Exception:
                time.sleep(0.1)

    def _on_mouse_scroll(self, x, y, dx, dy):
        pid_match = re.search(r"\((\d+)\)", self.selected_process.get())
        if not pid_match or not ProcessUtils.is_process_active(int(pid_match.group(1))):
            return

        curr_time = time.time()
        if self.latest_scroll_time and curr_time - self.latest_scroll_time <= 0.75:
            return

        key = self.settings.start_stop_key
        if (key == "W_UP" and dy > 0) or (key == "W_DN" and dy < 0):
            self.after(0, self.toggle_start_stop)
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

    def _on_runtime_toggle_mouse_scroll(self, x, y, dx, dy):
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
            self.after(0, self.toggle_runtime_event_group)

    def _on_runtime_toggle_mouse_click(self, x, y, button, pressed):
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
            self.after(0, self.toggle_runtime_event_group)

    def clear_local_logs(self):
        log_dir = Path("logs")
        if not messagebox.askokcancel(
            txt("Confirm", "확인"),
            txt("Delete old log files?", "오래된 로그 파일을 삭제하시겠습니까?"),
        ):
            return
        if not log_dir.exists():
            return messagebox.showinfo(
                txt("Info", "안내"), txt("No logs.", "로그가 없습니다.")
            )

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

    def toggle_start_stop(self, event=None):
        if self.toggle_transition_in_progress:
            return
        self.toggle_transition_in_progress = True
        if not self.is_running.get():
            try:
                if self.start_simulation():
                    self.is_running.set(True)
                    self.update_ui()
                else:
                    self._update_ui()
            finally:
                self.toggle_transition_in_progress = False
            return

        try:
            self.is_running.set(False)
            self.stop_simulation()
        finally:
            self.toggle_transition_in_progress = False

    def _start_simulation(self):
        if not (
            self.selected_process.get()
            and "(" in self.selected_process.get()
            and self.selected_profile.get()
        ):
            return False

        try:
            profile = load_profile(
                Path(self.profiles_dir), self.selected_profile.get(), migrate=True
            )
        except Exception:
            profile = ProfileModel()

        profile_events = list(profile.event_list or [])
        if self._find_duplicate_event_names(profile_events):
            return False
        if self._runtime_toggle_validation_errors(profile, profile_events):
            return False
        events = self._runnable_events(profile_events)
        if not events:
            return False
        self._configure_runtime_toggle_session(profile, events)
        # Keep the mac polling thread alive while Option+Shift is still held.
        if platform.system() != "Darwin" or not self.__dict__.get(
            "ctrl_check_active", False
        ):
            self._setup_event_handlers()

        self.terminate_event.clear()
        self.keystroke_processor = KeystrokeProcessor(
            self,
            self.selected_process.get(),
            events,
            profile.modification_keys or {},
            self.terminate_event,
        )
        self.keystroke_processor.start()
        self._save_latest_state()
        self.sound_player.play_start_sound()
        return True

    def _stop_simulation(self):
        if self.keystroke_processor:
            safe_call(self.keystroke_processor.stop)
            self.keystroke_processor = None
        self.terminate_event.set()
        self._reset_runtime_toggle_session()
        if platform.system() != "Darwin" or not self.settings.toggle_start_stop_mac:
            self._setup_event_handlers()

        if safe_call(self.winfo_exists):
            self.sound_player.play_stop_sound()
            self._update_ui()

    def toggle_runtime_event_group(self):
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

    def update_ui(self):
        return self._update_ui()

    def _update_ui(self):
        running = self.is_running.get()
        state = "disabled" if running else "normal"
        readonly_state = "disabled" if running else "readonly"
        readiness = self._get_readiness_snapshot()

        self.process_frame.process_combobox.config(state=readonly_state)
        self.process_frame.refresh_button.config(state=state)
        self.profile_frame.profile_combobox.config(state=readonly_state)
        self.profile_frame.copy_button.config(state=state)
        self.profile_frame.del_button.config(state=state)

        self.button_frame.start_stop_button.config(
            text=txt("Stop", "중지") if running else txt("Start", "시작"),
            state="normal" if running or readiness["can_start"] else "disabled",
        )
        self.button_frame.quick_events_button.config(state=state)
        self.button_frame.settings_button.config(state=state)
        self.button_frame.clear_logs_button.config(state=state)

        self.profile_button_frame.modkeys_button.config(state=state)
        self.profile_button_frame.settings_button.config(state=state)
        self.profile_button_frame.sort_button.config(state=state)
        self._update_main_status()

    def open_modkeys(self):
        if self.is_running.get():
            return
        if self.selected_profile.get():
            ModificationKeysWindow(self, self.selected_profile.get())

    def open_profile(self):
        if self.selected_profile.get():
            KeystrokeProfiles(self, self.selected_profile.get(), self.reload_profiles)

    def reload_profiles(self, new_name):
        self.profile_frame.load_profiles(select_name=new_name)
        self._update_ui()

    def sort_profile_events(self):
        self.unbind_events()
        if self.selected_profile.get():
            KeystrokeSortEvents(self, self.selected_profile.get(), self.reload_profiles)

    def open_quick_events(self):
        if self.is_running.get():
            return
        KeystrokeQuickEventEditor(self)

    def open_settings(self):
        existing_window = self.settings_window
        if existing_window and safe_call(existing_window.winfo_exists):
            safe_call(existing_window.lift)
            safe_call(existing_window.focus_force)
            safe_call(existing_window.grab_set)
            return
        if existing_window:
            self.settings_window = None
        self.unbind_events()
        self.settings_window = KeystrokeSettings(self)

    def _save_latest_state(self):
        StateUtils.save_main_app_state(
            process=self.selected_process.get().split(" (")[0],
            profile=self.selected_profile.get(),
        )

    def unbind_events(self):
        safe_call(self.unbind, "<Escape>")

        for listener in (
            self.keyboard_listener,
            self.start_stop_mouse_listener,
            self.runtime_toggle_mouse_listener,
        ):
            if listener:
                safe_call(listener.stop)
        self.keyboard_listener = None
        self.start_stop_mouse_listener = None
        self.runtime_toggle_mouse_listener = None

        self.ctrl_check_active = False
        if self.ctrl_check_thread and self.ctrl_check_thread.is_alive():
            safe_call(self.ctrl_check_thread.join, timeout=0.5)
        self.ctrl_check_thread = None

    def load_settings(self):
        self._load_settings_and_state()

    def setup_event_handlers(self):
        self._setup_event_handlers()

    def start_simulation(self):
        return self._start_simulation()

    def stop_simulation(self):
        return self._stop_simulation()

    def on_closing(self, event=None):
        if getattr(self, "_is_closing", False):
            return
        self._is_closing = True
        logger.info("Shutting down...")

        self.terminate_event.set()
        safe_call(self._stop_simulation)
        safe_call(self._save_latest_state)
        safe_call(self.unbind_events)
        safe_call(self.destroy)
        safe_call(self.quit)

        if self.secure_callback:
            safe_call(self.secure_callback)
