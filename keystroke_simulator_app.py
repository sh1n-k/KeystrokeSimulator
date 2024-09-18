import base64
from collections import deque
import json
import os
from pathlib import Path
import pickle
import platform
import shutil
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Dict, List, Optional, Deque

import keyboard
from loguru import logger
import pynput

from keystroke_engine import KeystrokeEngine
from keystroke_models import ProfileModel, EventModel, UserSettings
from keystroke_modkeys import ModificationKeysWindow
from keystroke_processors import ProcessCollector
from keystroke_profiles import KeystrokeProfiles
from keystroke_quick_event_editor import KeystrokeQuickEventEditor
from keystroke_settings import KeystrokeSettings
from keystroke_sort_events import KeystrokeSortEvents
from keystroke_utils import SoundUtils, StateUtils, WindowUtils, KeyUtils


class ProcessFrame(tk.Frame):
    def __init__(self, master, textvariable, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.process_label = tk.Label(
            self,
            text="Process:",
        )
        self.process_combobox = ttk.Combobox(
            self,
            textvariable=textvariable,
            state="readonly",
        )
        self.refresh_button = tk.Button(
            self,
            text="Refresh",
            command=self.refresh_processes,
        )

        self.process_label.pack(side=tk.LEFT, padx=5)
        self.process_combobox.pack(side=tk.LEFT, padx=5)
        self.refresh_button.pack(side=tk.LEFT)
        self.refresh_processes()

    def refresh_processes(self):
        processes = ProcessCollector.get()
        sorted_processes = sorted(processes, key=lambda x: x[0].lower())
        self.process_combobox["values"] = [
            f"{name} ({pid})" for name, pid, _ in sorted_processes
        ]
        if sorted_processes:
            self.process_combobox.current(0)
            self.process_combobox.event_generate("<<ComboboxSelected>>")


class ProfileFrame(tk.Frame):
    def __init__(self, master, textvariable, profiles_dir, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.profiles_dir = profiles_dir
        self.profile_label = tk.Label(
            self,
            text="Profiles:",
        )
        self.profile_combobox = ttk.Combobox(
            self,
            textvariable=textvariable,
            state="readonly",
        )
        self.copy_button = tk.Button(self, text="Copy", command=self.copy_profile)
        self.del_button = tk.Button(self, text="Delete", command=self.delete_profile)

        self.profile_label.pack(side=tk.LEFT, padx=5)
        self.profile_combobox.pack(side=tk.LEFT, padx=5)
        self.copy_button.pack(side=tk.LEFT)
        self.del_button.pack(side=tk.LEFT)

        self.load_profiles()

    def load_profiles(self):
        if not os.path.exists(self.profiles_dir):
            os.makedirs(self.profiles_dir)
            with open(f"{self.profiles_dir}/Quick.pkl", "wb") as f:
                pickle.dump(ProfileModel(), f)
        profile_files = [
            os.path.splitext(f)[0]
            for f in os.listdir(self.profiles_dir)
            if f.endswith(".pkl")
        ]
        if "Quick" in profile_files:
            profile_files.insert(0, profile_files.pop(profile_files.index("Quick")))
        self.profile_combobox["values"] = profile_files
        if profile_files:
            self.profile_combobox.current(0)

    def copy_profile(self):
        current_profile = self.profile_combobox.get()
        if not current_profile:
            return
        new_profile_name = self._copy_profile(current_profile)
        self.load_profiles()
        self.profile_combobox.set(new_profile_name)

    def _copy_profile(self, profile_name: str) -> str:
        source_file = os.path.join(self.profiles_dir, f"{profile_name}.pkl")
        new_profile_name = f"{profile_name} - Copied"
        destination_file = os.path.join(self.profiles_dir, f"{new_profile_name}.pkl")
        shutil.copy(source_file, destination_file)
        return new_profile_name

    def delete_profile(self):
        current_profile = self.profile_combobox.get()
        if not current_profile or current_profile == "Quick":
            return
        if messagebox.askokcancel("Warning", f"Delete profile '{current_profile}'."):
            self._delete_profile(current_profile)
            self.load_profiles()

    def _delete_profile(self, profile_name: str):
        profile_file = os.path.join(self.profiles_dir, f"{profile_name}.pkl")
        if os.path.exists(profile_file):
            os.remove(profile_file)


class ButtonFrame(tk.Frame):
    def __init__(
        self,
        master,
        toggle_callback: Callable,
        events_callback: Callable,
        settings_callback: Callable,
        *args,
        **kwargs,
    ):
        super().__init__(master, *args, **kwargs)
        self.start_stop_button = tk.Button(
            self,
            text="Start",
            width=10,
            height=1,
            command=toggle_callback,
        )
        self.events_button = tk.Button(
            self,
            text="Quick Events",
            width=10,
            height=1,
            command=events_callback,
        )
        self.settings_button = tk.Button(
            self,
            text="Settings",
            width=10,
            height=1,
            command=settings_callback,
        )

        self.start_stop_button.pack(side=tk.LEFT, padx=5)
        self.events_button.pack(side=tk.LEFT, padx=5)
        self.settings_button.pack(side=tk.LEFT, padx=5)


class ProfileButtonFrame(tk.Frame):
    def __init__(
        self,
        master,
        modkeys_callback: Callable,
        edit_callback: Callable,
        sort_callback: Callable,
        *args,
        **kwargs,
    ):
        super().__init__(master, *args, **kwargs)
        self.modkeys_button = tk.Button(  # Add this new button
            self,
            text="ModKeys",
            width=10,
            height=1,
            command=modkeys_callback,
        )
        self.settings_button = tk.Button(
            self,
            text="Edit Profile",
            width=10,
            height=1,
            command=edit_callback,
        )
        self.sort_button = tk.Button(
            self,
            text="Sort Profile",
            width=10,
            height=1,
            command=sort_callback,
        )

        self.modkeys_button.pack(side=tk.LEFT, padx=5)
        self.settings_button.pack(side=tk.LEFT, padx=5)
        self.sort_button.pack(side=tk.LEFT, padx=5)


class KeystrokeSimulatorApp(tk.Tk):
    def __init__(self, device_id=""):
        super().__init__()
        self.initialize_app(device_id)
        self.create_ui()
        self.load_settings_and_state()
        self.setup_event_handlers()

    def initialize_app(self, device_id):
        self.title("Python 3.12")
        self.profiles_dir = "profiles"
        self.device_id = device_id
        self.is_running = tk.BooleanVar(value=False)
        self.selected_process = tk.StringVar()
        self.selected_profile = tk.StringVar()
        self.keystroke_engines = []
        self.terminate_event = threading.Event()
        self.settings_window = None
        self.latest_scroll_time = None
        self.start_stop_mouse_listener = None
        SoundUtils.initialize()

    def create_ui(self):
        self.process_frame = ProcessFrame(self, textvariable=self.selected_process)
        self.profile_frame = ProfileFrame(
            self, textvariable=self.selected_profile, profiles_dir=self.profiles_dir
        )
        self.button_frame = ButtonFrame(
            self, self.toggle_start_stop, self.open_quick_events, self.open_settings
        )
        self.profile_button_frame = ProfileButtonFrame(
            self, self.open_modkeys, self.open_profile, self.sort_profile_events
        )

        for frame in (
            self.process_frame,
            self.profile_frame,
            self.button_frame,
            self.profile_button_frame,
        ):
            frame.pack(pady=5)

        self.set_ttk_style()
        WindowUtils.center_window(self)

    def load_settings_and_state(self):
        self.init_profiles()
        self.load_settings()
        self.load_latest_state()

    def setup_event_handlers(self):
        self.bind("<Escape>", self.on_closing)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.setup_start_stop_handler()

        self.process_acvivation_func = (
            KeystrokeEngine._is_process_active_windows
            if platform.system() == "Windows"
            else KeystrokeEngine._is_process_active_darwin
        )

    def setup_start_stop_handler(self):
        start_stop_key = self.settings.start_stop_key
        if start_stop_key.startswith("W_"):
            self.start_stop_mouse_listener = pynput.mouse.Listener(
                on_scroll=self.on_mouse_scroll
            )
            self.start_stop_mouse_listener.start()
        else:
            key = (
                KeyUtils.get_keycode(start_stop_key)
                if platform.system() == "Darwin"
                else start_stop_key
            )
            keyboard.on_press_key(key, self.toggle_start_stop)

    def init_profiles(self):
        os.makedirs(self.profiles_dir, exist_ok=True)
        quick_profile_path = Path(f"{self.profiles_dir}/Quick.pkl")
        if not quick_profile_path.exists():
            quick_profile_path.touch()
            with open(quick_profile_path, "wb") as f:
                pickle.dump(ProfileModel(), f)

    def set_ttk_style(self):
        style = ttk.Style(self)
        style.theme_use("default")
        for element in ("TFrame", "TLabel", "TButton", "TEntry"):
            style.configure(element)
        style.configure("TEntry", fieldbackground="white")

    def load_settings(self):
        try:
            with open("user_settings.b64", "r") as file:
                settings_json = base64.b64decode(file.read()).decode("utf-8")
            self.settings = UserSettings(**json.loads(settings_json))
        except FileNotFoundError:
            self.settings = UserSettings()

    def on_mouse_scroll(self, x, y, dx, dy):
        if not self.process_acvivation_func(
            KeystrokeEngine.parse_process_id(self.selected_process.get())
        ):
            return

        current_time = time.time()
        if self.latest_scroll_time and current_time - self.latest_scroll_time <= 0.75:
            return

        if (self.settings.start_stop_key == "W_UP" and dy > 0) or (
            self.settings.start_stop_key == "W_DN" and dy < 0
        ):
            self.toggle_start_stop()

        self.latest_scroll_time = current_time

    def toggle_start_stop(self, event=None):
        self.is_running.set(not self.is_running.get())
        if self.is_running.get():
            self.start_simulation()
        else:
            self.stop_simulation()

    def start_simulation(self):
        if not self._validate_simulation_prerequisites():
            return

        profile = self._load_profile()
        event_list = [p for p in profile.event_list if p.key_to_enter and p.use_event]
        if not event_list:
            return

        modification_keys = profile.modification_keys
        if not modification_keys:
            modification_keys = {}

        self.terminate_event.clear()
        self._create_and_start_engines(event_list, modification_keys)
        self.save_latest_state()

        SoundUtils.play_sound(self.settings.start_sound)
        self.update_ui()

    def _create_and_start_engines(
        self, event_list: List[EventModel], modification_keys: Dict
    ):
        independent_events = [event for event in event_list if event.independent_thread]
        regular_events = deque(
            [event for event in event_list if not event.independent_thread]
        )

        self.keystroke_engines = []
        self._process_independent_events(independent_events, modification_keys)
        self._process_regular_events(regular_events, modification_keys)
        self._process_mod_keys(modification_keys)

        logger.debug(f"engines: {self.keystroke_engines}")

        for engine in self.keystroke_engines:
            engine.start()

    def _validate_simulation_prerequisites(self) -> bool:
        return (
            self.selected_process.get()
            and " (" in self.selected_process.get()
            and self.selected_profile.get()
        )

    def _load_profile(self) -> Optional[ProfileModel]:
        try:
            with open(
                f"{self.profiles_dir}/{self.selected_profile.get()}.pkl", "rb"
            ) as f:
                profile = pickle.load(f)
                if not profile.event_list:
                    raise ValueError("Empty profile!")
                return profile
        except Exception as e:
            logger.info(f"Failed to load profile: {e}")
            return ProfileModel()

    def _process_independent_events(
        self, independent_events: List[EventModel], modification_keys: Dict
    ):
        for event in independent_events:
            engine = KeystrokeEngine(
                self,
                self.selected_process.get(),
                [event],
                modification_keys,
                self.terminate_event,
            )
            logger.debug(f"independent engine: {engine}")
            self.keystroke_engines.append(engine)

    def _process_regular_events(
        self, regular_events: Deque[EventModel], modification_keys: Dict
    ):
        num_regular_events = len(regular_events)
        events_per_thread = self.settings.events_per_thread

        if num_regular_events == 0:
            return

        num_engines = max(
            1, (num_regular_events + events_per_thread - 1) // events_per_thread
        )

        for _ in range(num_engines):
            chunk = [
                regular_events.popleft()
                for _ in range(min(events_per_thread, len(regular_events)))
            ]
            engine = KeystrokeEngine(
                self,
                self.selected_process.get(),
                chunk,
                modification_keys,
                self.terminate_event,
            )
            logger.debug(f"regular engine: {engine}")
            self.keystroke_engines.append(engine)

    def _process_mod_keys(self, modification_keys: Dict):
        if any(modification_keys[key]["enabled"] for key in modification_keys):
            engine = KeystrokeEngine(
                self,
                self.selected_process.get(),
                [],
                modification_keys,
                self.terminate_event,
                is_mod_key_handler=True,
            )
            logger.debug(f"mod engine: {engine}")
            self.keystroke_engines.append(engine)

    def stop_simulation(self):
        self.terminate_event.set()
        for engine in self.keystroke_engines:
            engine.join(timeout=0.1)
        self.keystroke_engines.clear()
        SoundUtils.play_sound(self.settings.stop_sound)
        self.update_ui()

    def update_ui(self):
        is_running = self.is_running.get()
        state = "disable" if is_running else "normal"
        readonly_state = "disable" if is_running else "readonly"

        self.process_frame.process_combobox.config(state=readonly_state)
        self.process_frame.refresh_button.config(state=state)
        self.profile_button_frame.settings_button.config(state=state)
        self.profile_frame.profile_combobox.config(state=readonly_state)
        self.profile_frame.copy_button.config(state=state)
        self.profile_frame.del_button.config(state=state)
        self.button_frame.start_stop_button.config(
            text="Stop" if is_running else "Start"
        )
        self.button_frame.settings_button.config(state=state)
        self.profile_button_frame.sort_button.config(state=state)

    def open_modkeys(self):
        if self.selected_profile.get():
            self.modkeys_window = ModificationKeysWindow(
                self, self.selected_profile.get()
            )

    def open_profile(self):
        if self.selected_profile.get():
            KeystrokeProfiles(self, self.selected_profile.get(), self.reload_profiles)

    def reload_profiles(self, new_profile_name):
        self.profile_frame.load_profiles()
        if new_profile_name in self.profile_frame.profile_combobox["values"]:
            self.profile_frame.profile_combobox.set(new_profile_name)
        elif self.profile_frame.profile_combobox["values"]:
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

    def load_latest_state(self):
        state = StateUtils.load_main_app_state()
        if state:
            if "process" in state:
                for process in self.process_frame.process_combobox["values"]:
                    if process.startswith(state["process"]):
                        self.selected_process.set(process)
                        break
            if "profile" in state:
                self.selected_profile.set(state["profile"])

    def save_latest_state(self):
        StateUtils.save_main_app_state(
            process=self.selected_process.get().split(" (")[0],
            profile=self.selected_profile.get(),
        )

    def bind_events(self):
        self.bind("<Escape>", self.on_closing)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        start_stop_key = self.settings.start_stop_key
        if start_stop_key.startswith("W_"):
            self.start_stop_mouse_listener = pynput.mouse.Listener(
                on_scroll=self.on_mouse_scroll
            )
            self.start_stop_mouse_listener.start()
        else:
            key = (
                KeyUtils.get_keycode(start_stop_key)
                if platform.system() == "Darwin"
                else start_stop_key
            )
            keyboard.on_press_key(key, self.toggle_start_stop)

    def unbind_events(self):
        self.unbind("<Escape>")
        keyboard.unhook_all()
        if self.start_stop_mouse_listener:
            self.start_stop_mouse_listener.stop()
            self.start_stop_mouse_listener = None

    def on_closing(self, event=None):
        logger.info("Shutting down the application and terminating threads...")
        self.terminate_event.set()
        self.stop_simulation()
        self.save_latest_state()
        self.unbind_events()
        self.destroy()
        logger.info("Bye")
