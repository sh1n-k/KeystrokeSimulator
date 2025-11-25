import json
import pickle
import platform
import re
import shutil
import threading
import time
import tkinter as tk
from dataclasses import fields, asdict
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Callable, List, Dict, Optional

from loguru import logger
import pynput.keyboard
import pynput.mouse

from keystroke_models import ProfileModel, EventModel, UserSettings
from keystroke_modkeys import ModificationKeysWindow
from keystroke_processor import KeystrokeProcessor
from keystroke_profiles import KeystrokeProfiles
from keystroke_quick_event_editor import KeystrokeQuickEventEditor
from keystroke_settings import KeystrokeSettings
from keystroke_sort_events import KeystrokeSortEvents
from keystroke_sounds import SoundPlayer
from keystroke_utils import (
    ProcessUtils,
    StateUtils,
    WindowUtils,
    KeyUtils,
    ProcessCollector,
)


class ProcessFrame(tk.Frame):
    def __init__(self, master, textvariable, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        tk.Label(self, text="Process:").pack(side=tk.LEFT, padx=5)
        self.process_combobox = ttk.Combobox(
            self, textvariable=textvariable, state="readonly"
        )
        self.process_combobox.pack(side=tk.LEFT, padx=5)
        self.refresh_button = tk.Button(
            self, text="Refresh", command=self.refresh_processes
        )
        self.refresh_button.pack(side=tk.LEFT)
        self.refresh_processes()

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
        tk.Label(self, text="Profiles:").pack(side=tk.LEFT, padx=5)
        self.profile_combobox = ttk.Combobox(
            self, textvariable=textvariable, state="readonly"
        )
        self.profile_combobox.pack(side=tk.LEFT, padx=5)

        # [수정됨] update_ui에서 참조할 수 있도록 self 변수에 명시적 할당
        self.copy_button = tk.Button(self, text="Copy", command=self.copy_profile)
        self.copy_button.pack(side=tk.LEFT)

        self.del_button = tk.Button(self, text="Delete", command=self.delete_profile)
        self.del_button.pack(side=tk.LEFT)

        self.load_profiles()

    def load_profiles(self):
        self.profiles_dir.mkdir(exist_ok=True)
        quick_pkl = self.profiles_dir / "Quick.pkl"
        if not quick_pkl.exists():
            with open(quick_pkl, "wb") as f:
                pickle.dump(ProfileModel(), f)

        favs, non_favs = [], []
        for p_file in self.profiles_dir.glob("*.pkl"):
            if p_file.name == "Quick.pkl":
                continue
            try:
                with open(p_file, "rb") as f:
                    data = pickle.load(f)
                    (favs if getattr(data, "favorite", False) else non_favs).append(
                        p_file.stem
                    )
            except Exception as e:
                logger.warning(f"Load failed {p_file}: {e}")
                non_favs.append(p_file.stem)

        sorted_profiles = ["Quick"] + sorted(favs) + sorted(non_favs)
        self.profile_combobox["values"] = sorted_profiles
        if sorted_profiles:
            self.profile_combobox.current(0)

    def copy_profile(self):
        if not (curr := self.profile_combobox.get()):
            return
        src = self.profiles_dir / f"{curr}.pkl"
        dst_name = f"{curr} - Copied"
        shutil.copy(src, self.profiles_dir / f"{dst_name}.pkl")
        self.load_profiles()
        self.profile_combobox.set(dst_name)

    def delete_profile(self):
        curr = self.profile_combobox.get()
        if not curr or curr == "Quick":
            return
        if messagebox.askokcancel("Warning", f"Delete profile '{curr}'."):
            (self.profiles_dir / f"{curr}.pkl").unlink(missing_ok=True)
            self.load_profiles()


class ButtonFrame(tk.Frame):
    def __init__(self, master, toggle_cb, events_cb, settings_cb, clear_cb, **kwargs):
        super().__init__(master, **kwargs)
        buttons = [
            ("Start", toggle_cb),
            ("Quick Events", events_cb),
            ("Settings", settings_cb),
            ("Clear Logs", clear_cb),
        ]
        self.btns = {}
        for text, cmd in buttons:
            btn = tk.Button(self, text=text, width=10, height=1, command=cmd)
            btn.pack(side=tk.LEFT, padx=5)
            self.btns[text] = btn
        self.start_stop_button = self.btns["Start"]
        self.settings_button = self.btns["Settings"]
        self.clear_logs_button = self.btns["Clear Logs"]


class ProfileButtonFrame(tk.Frame):
    def __init__(self, master, mod_cb, edit_cb, sort_cb, **kwargs):
        super().__init__(master, **kwargs)
        buttons = [
            ("ModKeys", mod_cb),
            ("Edit Profile", edit_cb),
            ("Sort Profile", sort_cb),
        ]
        self.btns = {}
        for text, cmd in buttons:
            btn = tk.Button(self, text=text, width=10, height=1, command=cmd)
            btn.pack(side=tk.LEFT, padx=5)
            self.btns[text] = btn
        self.settings_button = self.btns["Edit Profile"]
        self.sort_button = self.btns["Sort Profile"]


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

        self.create_ui()
        self.load_settings_and_state()
        self.setup_event_handlers()

    def create_ui(self):
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
        WindowUtils.center_window(self)

    def clear_local_logs(self):
        log_dir = Path("logs")
        if not messagebox.askokcancel("Confirm", "Delete old log files?"):
            return
        if not log_dir.exists():
            return messagebox.showinfo("Info", "No logs.")

        deleted_size = 0
        count = 0
        for p in log_dir.glob("*"):
            if p.name != "keysym.log" and p.is_file():
                try:
                    deleted_size += p.stat().st_size
                    p.unlink()
                    count += 1
                except Exception as e:
                    logger.warning(f"Del failed {p}: {e}")

        if count:
            messagebox.showinfo(
                "Success",
                f"{count} files cleared.\nSaved: {deleted_size/1048576:.2f} MB",
            )
        else:
            messagebox.showinfo("Info", "No old logs to clear.")

    def load_settings_and_state(self):
        self.load_settings()
        self.load_latest_state()

    # 변경 후
    def load_settings(self):
        s_file = Path("user_settings.json")
        try:
            data = json.loads(s_file.read_text(encoding="utf-8")) if s_file.exists() else {}
            valid_keys = {f.name for f in fields(UserSettings)}
            self.settings = UserSettings(**{k: v for k, v in data.items() if k in valid_keys})
        except Exception:
            self.settings = UserSettings()

        # Save clean settings
        s_file.write_text(json.dumps(asdict(self.settings), indent=2), encoding="utf-8")

    def load_latest_state(self):
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
            self.selected_profile.set(prof)

    def setup_event_handlers(self):
        self.bind("<Escape>", self.on_closing)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.unbind_events()

        if platform.system() == "Darwin" and self.settings.toggle_start_stop_mac:
            self.ctrl_check_active = True
            self.ctrl_check_thread = threading.Thread(
                target=self.check_for_long_alt_shift, daemon=True
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
                on_scroll=self.on_mouse_scroll
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
        if (
            str(key).replace("Key.", "").replace("'", "").upper()
            == self.settings.start_stop_key.upper()
        ):
            self.after(0, self.toggle_start_stop)

    def check_for_long_alt_shift(self):
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

    def on_mouse_scroll(self, x, y, dx, dy):
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

    def toggle_start_stop(self, event=None):
        self.is_running.set(not self.is_running.get())
        if self.is_running.get():
            self.start_simulation()
        else:
            self.stop_simulation()

    def start_simulation(self):
        if not (
            self.selected_process.get()
            and "(" in self.selected_process.get()
            and self.selected_profile.get()
        ):
            return

        try:
            with open(
                Path(self.profiles_dir) / f"{self.selected_profile.get()}.pkl", "rb"
            ) as f:
                profile = pickle.load(f)
        except Exception:
            profile = ProfileModel()

        events = [p for p in profile.event_list if p.key_to_enter and p.use_event]
        if not events:
            return

        self.terminate_event.clear()
        self.keystroke_processor = KeystrokeProcessor(
            self,
            self.selected_process.get(),
            events,
            profile.modification_keys or {},
            self.terminate_event,
        )
        self.keystroke_processor.start()
        self.save_latest_state()
        self.sound_player.play_start_sound()
        self.update_ui()

    def stop_simulation(self):
        if self.keystroke_processor:
            self.keystroke_processor.stop()
            self.keystroke_processor = None
        self.terminate_event.set()
        self.sound_player.play_stop_sound()
        self.update_ui()

    def update_ui(self):
        running = self.is_running.get()
        state = "disabled" if running else "normal"
        readonly_state = "disabled" if running else "readonly"

        self.process_frame.process_combobox.config(state=readonly_state)
        self.process_frame.refresh_button.config(state=state)
        self.profile_frame.profile_combobox.config(state=readonly_state)
        self.profile_frame.copy_button.config(state=state)
        self.profile_frame.del_button.config(state=state)

        self.button_frame.start_stop_button.config(text="Stop" if running else "Start")
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
        self.profile_frame.load_profiles()
        vals = self.profile_frame.profile_combobox["values"]
        if new_name in vals:
            self.profile_frame.profile_combobox.set(new_name)
        elif vals:
            self.profile_frame.profile_combobox.current(0)

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

    def save_latest_state(self):
        StateUtils.save_main_app_state(
            process=self.selected_process.get().split(" (")[0],
            profile=self.selected_profile.get(),
        )

    def unbind_events(self):
        self.unbind("<Escape>")
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        if self.start_stop_mouse_listener:
            self.start_stop_mouse_listener.stop()
            self.start_stop_mouse_listener = None
        self.ctrl_check_active = False
        if self.ctrl_check_thread:
            self.ctrl_check_thread.join(0.5)

    def on_closing(self, event=None):
        logger.info("Shutting down...")
        self.terminate_event.set()
        self.stop_simulation()
        self.save_latest_state()
        self.unbind_events()
        self.destroy()
        self.quit()
        if self.secure_callback:
            self.secure_callback()
