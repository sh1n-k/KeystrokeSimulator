import base64
import json
import os
from pathlib import Path
import pickle
import platform
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, List, Optional

import keyboard
from loguru import logger
import pynput

from keystroke_engine import KeystrokeEngine
from keystroke_models import ProfileModel, EventModel, UserSettings
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
        edit_callback: Callable,
        sort_callback: Callable,
        *args,
        **kwargs,
    ):
        super().__init__(master, *args, **kwargs)
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

        self.settings_button.pack(side=tk.LEFT, padx=5)
        self.sort_button.pack(side=tk.LEFT, padx=5)


class KeystrokeSimulatorApp(tk.Tk):
    def __init__(self, device_id=""):
        super().__init__()
        self.title("Python 3.12")
        self.profiles_dir = "profiles"
        self.device_id = device_id
        self.production_mode = device_id != ""
        self.is_running = tk.BooleanVar(value=False)
        self.settings: UserSettings
        self.selected_process = tk.StringVar()
        self.selected_profile = tk.StringVar()
        self.keystroke_engines = []

        self.init_profiles()
        self.settings_window = None
        self.process_frame = ProcessFrame(self, textvariable=self.selected_process)
        self.profile_frame = ProfileFrame(
            self, textvariable=self.selected_profile, profiles_dir=self.profiles_dir
        )
        self.button_frame = ButtonFrame(
            self, self.toggle_start_stop, self.open_quick_events, self.open_settings
        )
        self.profile_button_frame = ProfileButtonFrame(
            self,
            self.open_profile,
            self.sort_profile_events,
        )

        self.process_frame.pack(pady=1)
        self.profile_frame.pack(pady=1)
        self.button_frame.pack(pady=5)
        self.profile_button_frame.pack(pady=5)
        self.set_ttk_style()
        self.load_settings()
        self.bind_events()
        self.load_latest_state()
        self.terminate_event = threading.Event()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.start_stop_mouse_listener = None

        SoundUtils.initialize()
        WindowUtils.center_window(self)

    def init_profiles(self):
        if not os.path.isdir(self.profiles_dir):
            try:
                shutil.rmtree(self.profiles_dir)
            except FileNotFoundError as e:
                pass

        if not os.path.exists(self.profiles_dir):
            os.makedirs(self.profiles_dir)

        profile_quick_path = Path(f"{self.profiles_dir}/Quick.pkl")
        if not os.path.exists(profile_quick_path):
            Path(profile_quick_path).touch()
            with open(profile_quick_path, "wb") as f:
                pickle.dump(ProfileModel(), f)
            self._load_profile()

    def set_ttk_style(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TFrame", background="black")
        style.configure("TLabel", background="black", foreground="white")
        style.configure("TButton", background="white", foreground="black")
        style.configure("TEntry", fieldbackground="white", foreground="black")

    def load_settings(self):
        try:
            with open("user_settings.b64", "r") as file:
                settings_base64 = file.read()
            settings_json = base64.b64decode(settings_base64).decode("utf-8")
            loaded_settings = json.loads(settings_json)
            self.settings = UserSettings(**loaded_settings)
            logger.debug(f"Loaded settings: {loaded_settings}")
        except FileNotFoundError:
            self.settings = UserSettings()

    def bind_events(self):
        self.bind("<Escape>", self.on_closing)
        start_stop_key = self.settings.start_stop_key
        system = platform.system()

        if start_stop_key.startswith("W_"):
            self.start_stop_mouse_listener = pynput.mouse.Listener(
                on_scroll=self.on_mouse_scroll
            )
            self.start_stop_mouse_listener.start()
        else:
            if system == "Windows":
                keyboard.on_press_key(start_stop_key, self.toggle_start_stop)
            elif system == "Darwin":
                keyboard.on_press_key(
                    KeyUtils.get_keycode(start_stop_key), self.toggle_start_stop
                )

    def on_mouse_scroll(self, x, y, dx, dy):
        if KeystrokeEngine._is_process_active_windows(
            KeystrokeEngine.parse_process_id(self.selected_process.get())
        ):
            if self.settings.start_stop_key == "W_UP" and dy > 0:
                self.toggle_start_stop()
            elif self.settings.start_stop_key == "W_DN" and dy < 0:
                self.toggle_start_stop()

    def unbind_events(self):
        self.unbind("<Escape>")
        keyboard.unhook_all()

        if self.start_stop_mouse_listener:
            self.start_stop_mouse_listener.stop()
            self.start_stop_mouse_listener = None

    def toggle_start_stop(self, event=None):
        self.is_running.set(not self.is_running.get())
        if self.is_running.get():
            event_list = self._load_profile().event_list
            if not event_list or len(event_list) == 0:
                return
            self.start_simulation()
        else:
            self.stop_simulation()

    def start_simulation(self):
        if not self._validate_simulation_prerequisites():
            return

        profile = self._load_profile()
        if not profile:
            return

        event_list = [p for p in profile.event_list if p.key_to_enter and p.use_event]
        if not event_list:
            return

        self.terminate_event.clear()
        self._create_and_start_engines(event_list)
        self.save_latest_state()

        SoundUtils.play_sound(self.settings.start_sound)
        self.update_ui()

    def _validate_simulation_prerequisites(self) -> bool:
        target_process = self.selected_process.get()
        target_profile = self.selected_profile.get()

        if not target_process or " (" not in target_process:
            logger.info("Invalid process selected")
            return False
        if not target_profile:
            logger.info("No profile selected")
            return False
        return True

    def _load_profile(self) -> Optional[ProfileModel]:
        target_profile = self.selected_profile.get()
        try:
            with open(f"{self.profiles_dir}/{target_profile}.pkl", "rb") as f:
                profile: ProfileModel = pickle.load(f)
                if len(profile.event_list) < 1:
                    raise ValueError("Empty profile!")
                return profile
        except Exception as e:
            logger.info(f"Failed to load profile: {e}")
            return ProfileModel()

    def _create_and_start_engines(self, event_list: List[EventModel]):
        event_chunks = self._chunk_events(event_list)
        target_process = self.selected_process.get()

        self.keystroke_engines = [
            KeystrokeEngine(self, target_process, chunk, self.terminate_event)
            for chunk in event_chunks
        ]

        for engine in self.keystroke_engines:
            engine.start()

    def _chunk_events(self, event_list: List[EventModel]) -> List[List[EventModel]]:
        num_events = len(event_list)
        num_threads = (num_events + 9) // 10
        chunk_size, remainder = divmod(num_events, num_threads)

        return [
            event_list[
                i * chunk_size
                + min(i, remainder) : (i + 1) * chunk_size
                + min(i + 1, remainder)
            ]
            for i in range(num_threads)
        ]

    def stop_simulation(self):
        self.terminate_event.set()
        if self.keystroke_engines:
            for engine in self.keystroke_engines:
                engine.join(timeout=0.1)
            self.keystroke_engines = []
            SoundUtils.play_sound(self.settings.stop_sound)
            self.update_ui()

    def update_ui(self):
        state = "disable" if self.is_running.get() else "normal"
        self.process_frame.process_combobox.config(
            state="disable" if self.is_running.get() else "readonly"
        )
        self.process_frame.refresh_button.config(state=state)
        self.profile_button_frame.settings_button.config(state=state)
        self.profile_frame.profile_combobox.config(
            state="disable" if self.is_running.get() else "readonly"
        )
        self.profile_frame.copy_button.config(state=state)
        self.profile_frame.del_button.config(state=state)
        self.button_frame.start_stop_button.config(
            text="Stop" if self.is_running.get() else "Start"
        )
        self.button_frame.settings_button.config(state=state)
        self.profile_button_frame.sort_button.config(state=state)

    def open_profile(self):
        profile_name = self.selected_profile.get()
        if profile_name:
            KeystrokeProfiles(self, profile_name, self.reload_profiles)

    def reload_profiles(self, new_profile_name):
        self.profile_frame.load_profiles()
        if new_profile_name in self.profile_frame.profile_combobox["values"]:
            self.profile_frame.profile_combobox.set(new_profile_name)
        elif self.profile_frame.profile_combobox["values"]:
            self.profile_frame.profile_combobox.current(0)

    def sort_profile_events(self):
        self.unbind_events()
        profile_name = self.selected_profile.get()
        if profile_name:
            KeystrokeSortEvents(self, profile_name, self.reload_profiles)

    def open_quick_events(self):
        KeystrokeQuickEventEditor(self)

    def open_settings(self):
        if self.settings_window is not None:
            return

        self.unbind_events()
        self.settings_window = KeystrokeSettings(self)

    def load_latest_state(self):
        state = StateUtils.load_main_app_state()
        if not state:
            return

        if "process" in state:
            for process in self.process_frame.process_combobox["values"]:
                if process.startswith(state["process"]):
                    self.selected_process.set(process)
            logger.debug(f"Set default process to: {state['process']}")
        if "profile" in state:
            self.selected_profile.set(state["profile"])
            logger.debug(f"Set default profile to: {state['profile']}")

    def save_latest_state(self):
        StateUtils.save_main_app_state(
            process=self.selected_process.get().split(" (")[0],
            profile=self.selected_profile.get(),
        )

    def on_closing(self, event=None):
        logger.info("Shutting down the application and terminating threads...")
        self.terminate_event.set()
        self.stop_simulation()
        self.save_latest_state()
        keyboard.unhook_all()
        self.destroy()
        logger.info("Bye")
