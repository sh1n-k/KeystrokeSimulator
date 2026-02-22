import json
import platform
import re
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
from i18n import dual_text_width, normalize_language, set_language, txt

from keystroke_models import ProfileModel, EventModel, UserSettings
from keystroke_modkeys import ModificationKeysWindow
from keystroke_profile_storage import (
    copy_profile as copy_profile_storage,
    delete_profile_files,
    ensure_quick_profile,
    list_profile_names,
    load_profile,
    load_profile_meta_favorite,
)
from keystroke_processor import KeystrokeProcessor
from keystroke_profiles import KeystrokeProfiles
from keystroke_quick_event_editor import KeystrokeQuickEventEditor
from keystroke_settings import KeystrokeSettings
from keystroke_sort_events import KeystrokeSortEvents
from keystroke_sounds import SoundPlayer
from profile_display import QUICK_PROFILE_NAME, build_profile_display_values
from keystroke_utils import (
    ProcessUtils,
    StateUtils,
    WindowUtils,
    KeyUtils,
    ProcessCollector,
)


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
            if profile_name in self.favorite_names and profile_name != QUICK_PROFILE_NAME
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
        self.profiles_dir.mkdir(exist_ok=True)
        ensure_quick_profile(self.profiles_dir)

        favs, non_favs = [], []
        for name in list_profile_names(self.profiles_dir):
            if name == QUICK_PROFILE_NAME:
                continue
            try:
                (favs if load_profile_meta_favorite(self.profiles_dir, name) else non_favs).append(
                    name
                )
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

        target_name = select_name or self.selected_profile_var.get() or QUICK_PROFILE_NAME
        if not self.set_selected_profile(target_name):
            self.profile_combobox.current(0)
            self._on_profile_selected()

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
        if (self.profiles_dir / f"{dst_name}.json").exists() or (
            self.profiles_dir / f"{dst_name}.pkl"
        ).exists():
            messagebox.showwarning(
                txt("Warning", "경고"),
                txt("Profile '{name}' already exists.", "'{name}' 프로필이 이미 존재합니다.", name=dst_name),
                parent=self,
            )
            return
        try:
            copy_profile_storage(self.profiles_dir, curr, dst_name)
            self.load_profiles(select_name=dst_name)
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
                txt("The default profile cannot be deleted.", "기본 프로필은 삭제할 수 없습니다."),
                parent=self,
            )
            return
        if messagebox.askokcancel(
            txt("Warning", "경고"),
            txt("Delete profile '{name}'?", "프로필 '{name}'을(를) 삭제하시겠습니까?", name=curr),
        ):
            delete_profile_files(self.profiles_dir, curr)
            self.load_profiles()


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
        self.keyboard_listener = None
        self.alt_pressed = False
        self.shift_pressed = False
        self.last_alt_shift_toggle_time = 0
        self.ctrl_check_thread = None
        self.ctrl_check_active = False

        self._create_ui()
        self._load_settings_and_state()
        self._setup_event_handlers()

    def _create_ui(self):
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
        self.settings.language = normalize_language(getattr(self.settings, "language", None))
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

    def _refresh_ui_texts(self):
        if hasattr(self, "process_frame"):
            self.process_frame.refresh_texts()
        if hasattr(self, "profile_frame"):
            self.profile_frame.refresh_texts()
        if hasattr(self, "button_frame"):
            self.button_frame.refresh_texts()
        if hasattr(self, "profile_button_frame"):
            self.profile_button_frame.refresh_texts()

    def _setup_event_handlers(self):
        self.unbind_events()
        self.bind("<Escape>", self.on_closing)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        if platform.system() == "Darwin" and self.settings.toggle_start_stop_mac:
            self.ctrl_check_active = True
            self.ctrl_check_thread = threading.Thread(
                target=self._check_for_long_alt_shift, daemon=True
            )
            self.ctrl_check_thread.start()
            return

        key = self.settings.start_stop_key
        if platform.system() == "Windows" and self.settings.use_alt_shift_hotkey:
            self.keyboard_listener = pynput.keyboard.Listener(
                on_press=self._on_key_press, on_release=self._on_key_release
            )
            self.keyboard_listener.start()
        elif key.startswith("W_"):
            self.start_stop_mouse_listener = pynput.mouse.Listener(
                on_scroll=self._on_mouse_scroll
            )
            self.start_stop_mouse_listener.start()
        elif key != "DISABLED":
            self.keyboard_listener = pynput.keyboard.Listener(
                on_press=self._on_single_key_press, on_release=self._on_key_release
            )
            self.keyboard_listener.start()

    def _on_key_press(self, key):
        if time.time() - self.last_alt_shift_toggle_time < 0.2:
            return
        if key in (pynput.keyboard.Key.alt_l, pynput.keyboard.Key.alt_r):
            self.alt_pressed = True
        if key in (pynput.keyboard.Key.shift_l, pynput.keyboard.Key.shift_r):
            self.shift_pressed = True
        if self.alt_pressed and self.shift_pressed:
            self.last_alt_shift_toggle_time = time.time()
            self.after(0, self.toggle_start_stop)

    def _on_key_release(self, key):
        if key in (pynput.keyboard.Key.alt_l, pynput.keyboard.Key.alt_r):
            self.alt_pressed = False
        if key in (pynput.keyboard.Key.shift_l, pynput.keyboard.Key.shift_r):
            self.shift_pressed = False

    def _on_single_key_press(self, key):
        key_str = str(key).replace("Key.", "").replace("'", "").upper()
        if key_str == self.settings.start_stop_key.upper():
            self.after(0, self.toggle_start_stop)

    def _check_for_long_alt_shift(self):
        last_state, last_time = False, 0
        while self.ctrl_check_active:
            try:
                curr_time = time.time()
                if curr_time - last_time < 0.1:
                    time.sleep(0.01)
                    continue

                curr_state = KeyUtils.mod_key_pressed(
                    "alt"
                ) and KeyUtils.mod_key_pressed("shift")
                if curr_state and not last_state:
                    self.after(0, self.toggle_start_stop)
                    last_time = curr_time
                last_state = curr_state
                time.sleep(0.01)
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
        if not self.is_running.get():
            if self.start_simulation():
                self.is_running.set(True)
                self.update_ui()
        else:
            self.is_running.set(False)
            self.stop_simulation()

    def _start_simulation(self):
        if not (
            self.selected_process.get()
            and "(" in self.selected_process.get()
            and self.selected_profile.get()
        ):
            return False

        try:
            profile = load_profile(Path(self.profiles_dir), self.selected_profile.get(), migrate=True)
        except Exception:
            profile = ProfileModel()

        # include condition-only events even if they have no key
        events = [
            p
            for p in profile.event_list
            if p.use_event
            and (p.key_to_enter or not getattr(p, "execute_action", True))
        ]
        if not events:
            return False

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

        if safe_call(self.winfo_exists):
            self.sound_player.play_stop_sound()
            self._update_ui()

    def update_ui(self):
        return self._update_ui()

    def _update_ui(self):
        running = self.is_running.get()
        state = "disabled" if running else "normal"
        readonly_state = "disabled" if running else "readonly"

        self.process_frame.process_combobox.config(state=readonly_state)
        self.process_frame.refresh_button.config(state=state)
        self.profile_frame.profile_combobox.config(state=readonly_state)
        self.profile_frame.copy_button.config(state=state)
        self.profile_frame.del_button.config(state=state)

        self.button_frame.start_stop_button.config(
            text=txt("Stop", "중지") if running else txt("Start", "시작")
        )
        self.button_frame.settings_button.config(state=state)
        self.button_frame.clear_logs_button.config(state=state)

        self.profile_button_frame.settings_button.config(state=state)
        self.profile_button_frame.sort_button.config(state=state)

    def open_modkeys(self):
        if self.selected_profile.get():
            ModificationKeysWindow(self, self.selected_profile.get())

    def open_profile(self):
        if self.selected_profile.get():
            KeystrokeProfiles(self, self.selected_profile.get(), self.reload_profiles)

    def reload_profiles(self, new_name):
        self.profile_frame.load_profiles(select_name=new_name)

    def sort_profile_events(self):
        self.unbind_events()
        if self.selected_profile.get():
            KeystrokeSortEvents(self, self.selected_profile.get(), self.reload_profiles)

    def open_quick_events(self):
        KeystrokeQuickEventEditor(self)

    def open_settings(self):
        if not self.settings_window:
            self.unbind_events()
            self.settings_window = KeystrokeSettings(self)

    def _save_latest_state(self):
        StateUtils.save_main_app_state(
            process=self.selected_process.get().split(" (")[0],
            profile=self.selected_profile.get(),
        )

    def unbind_events(self):
        safe_call(self.unbind, "<Escape>")

        for listener in (self.keyboard_listener, self.start_stop_mouse_listener):
            if listener:
                safe_call(listener.stop)
        self.keyboard_listener = None
        self.start_stop_mouse_listener = None

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
