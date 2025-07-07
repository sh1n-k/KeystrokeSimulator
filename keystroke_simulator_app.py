import base64
import json
import os
import pickle
import platform
import shutil
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import Callable, List, Dict, Optional

import keyboard
from loguru import logger

from keystroke_models import ProfileModel, EventModel, UserSettings
from keystroke_modkeys import ModificationKeysWindow
from keystroke_processor import KeystrokeProcessor
from keystroke_profiles import KeystrokeProfiles
from keystroke_quick_event_editor import KeystrokeQuickEventEditor
from keystroke_settings import KeystrokeSettings
from keystroke_sort_events import KeystrokeSortEvents
from keystroke_utils import (
    SoundUtils,
    StateUtils,
    WindowUtils,
    KeyUtils,
    ProcessCollector,
)


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
        # 현재 선택된 값에서 Process Name 추출
        current_value = self.process_combobox.get()
        current_process_name = None

        if current_value:
            # "Process Name (PID)" 형태에서 Process Name 추출
            # 마지막 괄호와 그 내용을 제거
            if current_value.endswith(")") and "(" in current_value:
                current_process_name = current_value.rsplit(" (", 1)[0]

        # 새로운 프로세스 목록 가져오기
        processes = ProcessCollector.get()
        sorted_processes = sorted(processes, key=lambda x: x[0].lower())

        # 콤보박스 값 설정
        process_values = [f"{name} ({pid})" for name, pid, _ in sorted_processes]
        self.process_combobox["values"] = process_values

        # 이전에 선택된 Process Name과 일치하는 항목 찾기
        selected_index = 0  # 기본값

        if current_process_name:
            for i, (name, pid, _) in enumerate(sorted_processes):
                if name == current_process_name:
                    selected_index = i
                    break

        # 콤보박스 선택 설정
        if sorted_processes:
            self.process_combobox.current(selected_index)
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
        profile_files.sort(reverse=False)
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
    def __init__(self, secure_callback=None):
        super().__init__()
        self.initialize_app()
        self.create_ui()
        self.load_settings_and_state()
        self.setup_event_handlers()
        self.secure_callback = secure_callback

    def initialize_app(self):
        self.title("Python 3.12")
        self.profiles_dir = "profiles"
        self.is_running = tk.BooleanVar(value=False)
        self.selected_process = tk.StringVar()
        self.selected_profile = tk.StringVar()
        self.keystroke_processor = None
        self.terminate_event = threading.Event()
        self.settings_window = None
        self.latest_scroll_time = None

        # Variables for Start/Stop toggle
        self.start_stop_mouse_listener = None
        self.last_ctrl_press_time = 0
        self.ctrl_check_thread = None
        self.ctrl_check_active = False

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

        self.process_activation_func = (
            KeystrokeProcessor._is_process_active_windows
            if platform.system() == "Windows"
            else KeystrokeProcessor._is_process_active_darwin
        )

    def setup_start_stop_handler(self):
        if platform.system() == "Darwin":
            if self.settings.toggle_start_stop_mac:
                # Setup double Ctrl press detection for macOS
                self.setup_ctrl_double_press_handler()
        else:
            # Existing code for Windows
            start_stop_key = self.settings.start_stop_key
            if start_stop_key.startswith("W_"):
                import pynput

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

    def setup_ctrl_double_press_handler(self):
        """Sets up a thread to detect double Ctrl presses on macOS"""

        # Start a thread to check for Ctrl key presses
        self.ctrl_check_active = True
        self.ctrl_check_thread = threading.Thread(target=self.check_for_long_alt_shift)
        self.ctrl_check_thread.daemon = True
        self.ctrl_check_thread.start()

    def check_for_long_alt_shift(self):
        """Thread method to detect long Alt+Shift key press (1+ seconds) on macOS"""
        import time

        last_combo_state = False
        combo_press_start_time = 0
        last_toggle_time = 0
        toggle_cooldown = 0.25
        long_press_threshold = 0.01  # 1초 이상 눌러야 함
        toggle_executed = False  # 한 번의 키 조합 누름에 대해 토글이 실행되었는지 추적

        while self.ctrl_check_active:
            try:
                current_time = time.time()

                # 쿨다운 체크
                if current_time - last_toggle_time < toggle_cooldown:
                    # logger.debug(f"[{time.ctime(current_time)}] 쿨다운 중... (남은 시간: {toggle_cooldown - (current_time - last_toggle_time):.4f}s)")
                    time.sleep(0.05)
                    continue

                # Alt와 Shift 키가 모두 눌렸는지 확인
                alt_pressed = KeyUtils.mod_key_pressed("alt")
                shift_pressed = KeyUtils.mod_key_pressed("shift")
                current_combo_state = alt_pressed and shift_pressed

                # Alt+Shift 조합이 방금 눌렸을 때 (rising edge)
                if current_combo_state and not last_combo_state:
                    combo_press_start_time = current_time
                    toggle_executed = (
                        False  # 새로운 키 조합 누름이므로 토글 실행 플래그 리셋
                    )

                # Alt+Shift 조합이 방금 떼어졌을 때 (falling edge)
                elif not current_combo_state and last_combo_state:
                    press_duration = current_time - combo_press_start_time
                    combo_press_start_time = 0
                    toggle_executed = False  # 키가 떼어졌으므로 토글 실행 플래그 리셋

                # Alt+Shift 조합이 계속 눌려있는 상태에서 1초가 지났을 때 토글 실행
                elif (
                    current_combo_state
                    and last_combo_state
                    and combo_press_start_time > 0
                    and not toggle_executed
                ):
                    press_duration = current_time - combo_press_start_time

                    # 정확히 1초 지났을 때 토글 (키를 떼지 않아도)
                    if (
                        press_duration >= long_press_threshold
                        and (current_time - last_toggle_time) >= toggle_cooldown
                    ):
                        self.after(0, self.toggle_start_stop)
                        last_toggle_time = current_time
                        toggle_executed = True  # 토글이 실행되었음을 표시

                # 이전 상태 업데이트
                last_combo_state = current_combo_state

                # CPU 사용량 방지를 위한 짧은 대기
                time.sleep(0.01)

            except Exception as e:
                logger.error(f"Error in check_for_long_ctrl: {e}")
                time.sleep(0.1)

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
        if not self.process_activation_func(
            KeystrokeProcessor.parse_process_id(self.selected_process.get())
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
        self._create_and_start_processor(event_list, modification_keys)
        self.save_latest_state()

        SoundUtils.play_sound(self.settings.start_sound)
        self.update_ui()

    def _create_and_start_processor(
        self, event_list: List[EventModel], modification_keys: Dict
    ):
        """
        Creates and starts the KeystrokeProcessor.
        """
        self.keystroke_processor = KeystrokeProcessor(
            main_app=self,
            target_process=self.selected_process.get(),
            event_list=event_list,
            modification_keys=modification_keys,
            terminate_event=self.terminate_event,
        )
        self.keystroke_processor.start()
        logger.debug("KeystrokeProcessor started.")

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

    def stop_simulation(self):
        if self.keystroke_processor:
            self.keystroke_processor.stop()
            self.keystroke_processor = None

        self.terminate_event.set()
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

    # def bind_events(self):
    #     self.bind("<Escape>", self.on_closing)
    #     self.protocol("WM_DELETE_WINDOW", self.on_closing)
    #
    #     start_stop_key = self.settings.start_stop_key
    #     if start_stop_key.startswith("W_"):
    #         import pynput
    #         self.start_stop_mouse_listener = pynput.mouse.Listener(
    #             on_scroll=self.on_mouse_scroll
    #         )
    #         self.start_stop_mouse_listener.start()
    #     else:
    #         key = (
    #             KeyUtils.get_keycode(start_stop_key)
    #             if platform.system() == "Darwin"
    #             else start_stop_key
    #         )
    #         keyboard.on_press_key(key, self.toggle_start_stop)

    def unbind_events(self):
        self.unbind("<Escape>")

        if platform.system() != "Darwin":
            keyboard.unhook_all()
        if self.start_stop_mouse_listener:
            self.start_stop_mouse_listener.stop()
            self.start_stop_mouse_listener = None

        # Stop the Ctrl check thread (MacOS)
        self.ctrl_check_active = False
        if self.ctrl_check_thread and self.ctrl_check_thread.is_alive():
            self.ctrl_check_thread.join(timeout=0.5)

    def on_closing(self, event=None):
        logger.info("Shutting down the application and terminating threads...")
        self.terminate_event.set()
        self.stop_simulation()
        self.save_latest_state()
        self.unbind_events()
        self.destroy()
        self.quit()
        if self.secure_callback:
            self.secure_callback()
        logger.info("Bye")
