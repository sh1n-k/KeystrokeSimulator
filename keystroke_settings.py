import base64
import json
import tkinter as tk
from dataclasses import asdict
from tkinter import ttk, filedialog, messagebox
from typing import Callable

from loguru import logger

from keystroke_models import UserSettings
from keystroke_utils import WindowUtils


class KeystrokeSettings(tk.Toplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.title("Settings")
        self.settings = UserSettings()
        self._setup_window()
        self._create_widgets()
        self._load_settings()

    def _setup_window(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", self.on_close)
        WindowUtils.center_window(self)

    def _create_widgets(self):
        self._create_start_stop_key()
        self._create_time_entries()
        self._create_num_of_events_entry()
        self._create_max_key_count_entry()
        self._create_sound_selectors()
        self._create_buttons()
        self._create_warning_label()

    # UI Creation Methods
    def _create_start_stop_key(self):
        ttk.Label(self, text="Start/Stop Key:").grid(
            row=0, column=0, padx=10, pady=5, sticky=tk.W
        )

        self.start_stop_key = ttk.Combobox(self, values=["Press Key"], state="readonly")
        self.start_stop_key.grid(row=0, column=1, padx=10, pady=5)
        self.start_stop_key.current(0)
        self.start_stop_key.bind("<Key>", self._on_key_press)

        self.wheel_up_var = tk.BooleanVar()
        self.wheel_up_checkbox = ttk.Checkbutton(
            self,
            text="Wheel UP",
            variable=self.wheel_up_var,
            command=self._on_checkbox_change,
        )
        self.wheel_up_checkbox.grid(row=0, column=2, padx=5, pady=5)

        self.wheel_down_var = tk.BooleanVar()
        self.wheel_down_checkbox = ttk.Checkbutton(
            self,
            text="Wheel Down",
            variable=self.wheel_down_var,
            command=self._on_checkbox_change,
        )
        self.wheel_down_checkbox.grid(row=0, column=3, padx=5, pady=5)

    def _create_time_entries(self):
        validation_command = (self.register(self._validate_numeric_entry), "%P")
        self._create_entry_pair("Key pressed time (min, max):", 1, validation_command)
        self._create_entry_pair("Delay between loop (min, max):", 2, validation_command)

    def _create_entry_pair(self, label: str, row: int, validation_command: Callable):
        ttk.Label(self, text=label).grid(
            row=row, column=0, padx=10, pady=5, sticky=tk.W
        )
        setattr(
            self,
            f"entry_min_{row}",
            ttk.Entry(self, validate="key", validatecommand=validation_command),
        )
        getattr(self, f"entry_min_{row}").grid(row=row, column=1, padx=10, pady=5)
        setattr(
            self,
            f"entry_max_{row}",
            ttk.Entry(self, validate="key", validatecommand=validation_command),
        )
        getattr(self, f"entry_max_{row}").grid(row=row, column=2, padx=10, pady=5)

    def _create_num_of_events_entry(self):
        ttk.Label(self, text="Num of events per Thread").grid(
            row=3, column=0, padx=10, pady=5, sticky=tk.W
        )
        setattr(
            self,
            f"events_per_thread",
            ttk.Entry(
                self,
                validate="key",
                validatecommand=(self.register(self._validate_events_per_thread), "%P"),
            ),
        )
        getattr(self, f"events_per_thread").grid(row=3, column=1, padx=10, pady=5)

    def _create_max_key_count_entry(self):
        ttk.Label(self, text="Max Key Count").grid(
            row=4, column=0, padx=10, pady=5, sticky=tk.W
        )
        setattr(
            self,
            f"max_key_count",
            ttk.Entry(
                self,
                validate="key",
                validatecommand=(self.register(self._validate_max_key_count), "%P"),
            ),
        )
        getattr(self, f"max_key_count").grid(row=4, column=1, padx=10, pady=5)

    def _create_sound_selectors(self):
        self._create_sound_selector("Start Sound:", 5, self._select_sound)
        self._create_sound_selector("Stop Sound:", 6, self._select_sound)

    def _create_sound_selector(self, label: str, row: int, command: Callable):
        ttk.Label(self, text=label).grid(
            row=row, column=0, padx=10, pady=5, sticky=tk.W
        )
        sound_label = ttk.Label(self, text="Select file", wraplength=140)
        sound_label.grid(row=row, column=1, padx=10, pady=5, sticky=tk.W)
        sound_button = ttk.Button(
            self, text="Browse", command=lambda: command(sound_label)
        )
        sound_button.grid(row=row, column=2, padx=10, pady=5)

    def _create_buttons(self):
        ttk.Button(self, text="Reset", command=self.on_reset).grid(
            row=8, column=0, padx=10, pady=10
        )
        ttk.Button(self, text="OK", command=self.on_ok).grid(
            row=8, column=1, padx=10, pady=10
        )
        ttk.Button(self, text="Cancel", command=self.on_close).grid(
            row=8, column=2, padx=10, pady=10
        )

    def _create_warning_label(self):
        self.warning_label = ttk.Label(
            self, text="\n", background="white", foreground="red"
        )
        self.warning_label.grid(row=7, column=0, columnspan=5, pady=5)
        self.warning_label.config(
            text="For Start/Stop, set only A-Z, 0-9, and special character keys.\n\nStart/Stop 은 A-Z, 0-9, 특수문자 키만 설정하세요."
        )

    # Settings Management Methods
    def _load_settings(self):
        try:
            with open("user_settings.b64", "r") as file:
                settings_base64 = file.read()
            settings_json = base64.b64decode(settings_base64).decode("utf-8")
            loaded_settings = json.loads(settings_json)
            self.settings = UserSettings(**loaded_settings)
        except Exception as e:
            print("Error loading settings:", e)
            self.settings = UserSettings()
        finally:
            self._update_ui_from_settings()

    def _update_ui_from_settings(self):
        self._update_start_stop_key()
        self._update_time_entries()
        self._update_num_of_events()
        self._update_max_key_count()
        self._update_sound_labels()

    def _update_start_stop_key(self):
        if self.settings.start_stop_key == "W_UP":
            self.wheel_up_var.set(True)
            self.start_stop_key.config(state="disabled")
            self.wheel_down_checkbox.config(state="disabled")
        elif self.settings.start_stop_key == "W_DN":
            self.wheel_down_var.set(True)
            self.start_stop_key.config(state="disabled")
            self.wheel_up_checkbox.config(state="disabled")
        else:
            self.start_stop_key.set(self.settings.start_stop_key)
            self.wheel_up_var.set(False)
            self.wheel_down_var.set(False)
            self.start_stop_key.config(state="readonly")
            self.wheel_up_checkbox.config(state="normal")
            self.wheel_down_checkbox.config(state="normal")

    def _update_time_entries(self):
        self._set_entry_values(1, "key_pressed_time")
        self._set_entry_values(2, "delay_between_loop")

    def _update_num_of_events(self):
        self._set_num_of_events_value()

    def _update_max_key_count(self):
        getattr(self, "max_key_count").delete(0, tk.END)
        getattr(self, "max_key_count").insert(
            0, str(getattr(self.settings, "max_key_count", "10"))
        )

    def _update_sound_labels(self):
        self._set_sound_label(5, self.settings.start_sound)
        self._set_sound_label(6, self.settings.stop_sound)

    def _set_entry_values(self, row, prefix):
        getattr(self, f"entry_min_{row}").delete(0, tk.END)
        getattr(self, f"entry_min_{row}").insert(
            0, str(getattr(self.settings, f"{prefix}_min"))
        )
        getattr(self, f"entry_max_{row}").delete(0, tk.END)
        getattr(self, f"entry_max_{row}").insert(
            0, str(getattr(self.settings, f"{prefix}_max"))
        )

    def _set_num_of_events_value(self):
        getattr(self, "events_per_thread").delete(0, tk.END)
        getattr(self, "events_per_thread").insert(
            0, str(getattr(self.settings, f"events_per_thread"))
        )

    def _set_sound_label(self, row, filepath):
        sound_label = self.grid_slaves(row=row, column=1)[0]
        sound_label.config(text=filepath)

    # Event Handlers
    def _on_checkbox_change(self):
        if self.wheel_up_var.get() or self.wheel_down_var.get():
            self.start_stop_key.config(state="disabled")
        else:
            self.start_stop_key.config(state="readonly")

        self.wheel_up_checkbox.config(
            state="normal" if not self.wheel_down_var.get() else "disabled"
        )
        self.wheel_down_checkbox.config(
            state="normal" if not self.wheel_up_var.get() else "disabled"
        )

        self._store_wheel_settings()

    def _on_key_press(self, event):
        valid_keys = (
                set(f"F{i}" for i in range(1, 13))
                | set(chr(i) for i in range(ord("A"), ord("Z") + 1))
                | set(chr(i) for i in range(ord("0"), ord("9") + 1))
                | set("`[];',./-=\\")
        )

        key = event.char.upper() or event.keysym.upper()
        if key in valid_keys:
            self.start_stop_key.set(key)
            self.settings.start_stop_key = self.start_stop_key.get()

    def _select_sound(self, label):
        filepath = filedialog.askopenfilename(
            title="Select Sound File",
            filetypes=[("Sound Files", "*.mp3 *.wav *.ogg"), ("All Files", "*.*")],
        )
        if filepath:
            label.config(text=filepath)

    # Validation Methods
    @staticmethod
    def _validate_numeric_entry(P):
        return P == "" or (P.isdigit() and 0 <= int(P) < 1000 and not P.startswith("0"))

    @staticmethod
    def _validate_events_per_thread(P):
        if P == "":
            return True
        try:
            value = int(P)
            return 1 <= value <= 15
        except ValueError:
            return False

    @staticmethod
    def _validate_max_key_count(P):
        if P == "":
            return True
        if not P.isdigit():
            return False
        if P.startswith("0") and len(P) > 1:
            return False
        value = int(P)
        return 1 <= value <= 50

    def validate_start_stop_key(self):
        if self.settings.start_stop_key in ["Press Key", ""]:
            self.show_warning("Please select a Start/Stop key.")
            return False
        return True

    def validate_and_set_time_settings(self):
        time_settings = [
            (1, "key_pressed_time", 95, 135),
            (2, "delay_between_loop", 100, 150),
        ]

        for row, prefix, min_default, max_default in time_settings:
            min_value = int(getattr(self, f"entry_min_{row}").get() or min_default)
            max_value = int(getattr(self, f"entry_max_{row}").get() or max_default)

            if not self.validate_min_max_values(min_value, max_value):
                return False

            setattr(self.settings, f"{prefix}_min", min_value)
            setattr(self.settings, f"{prefix}_max", max_value)

        events_per_thread = int(getattr(self, f"events_per_thread").get() or 1)
        if events_per_thread < 1 or events_per_thread > 15:
            self.show_warning(
                "Select the number of events between 1-15.\n이벤트 수는 1-15 사이에서 선택하세요."
            )
            return False
        setattr(self.settings, "events_per_thread", events_per_thread)

        max_key_count = getattr(self, "max_key_count").get()
        if max_key_count:
            max_key_count = int(max_key_count)
            if max_key_count < 10 or max_key_count > 50:
                self.show_warning(
                    "Max Key Count must be between 10 and 50.\nMax Key Count는 10에서 50 사이여야 합니다."
                )
                return False
        else:
            max_key_count = 10  # Default value if empty

        self.settings.max_key_count = max_key_count

        return True

    def validate_min_max_values(self, min_value, max_value):
        if min_value >= max_value:
            self.show_warning("Check the Min and Max values.\n최소, 최대값을 확인하세요.")
            return False
        if min_value < 75 or max_value > 200:
            self.show_warning(
                "The Min value cannot be set below 75 and the Max value cannot be set above 200.\n"
                "Min 값은 75 미만,  Max 값은 200 초과할 수 없습니다."
            )
            return False
        return True

    # Action Methods
    def on_reset(self):
        if messagebox.askokcancel("Warning", f"Resets the values.\n설정값이 초기화 됩니다."):
            self.settings = UserSettings()  # Reset to default values
            self._update_ui_from_settings()
            self.warning_label.config(
                text="Settings have been reset to default values."
            )

    def on_ok(self):
        if not self.validate_start_stop_key():
            return

        self._store_wheel_settings()

        if not self.validate_and_set_time_settings():
            return
        self.set_max_key_count()
        self.set_sound_settings()
        self.save_settings()

        self.on_close()

    def on_close(self, event=None):
        self.master.settings_window = None
        self.master.load_settings()
        self.master.bind_events()
        self.destroy()

    # Helper Methods
    def _store_wheel_settings(self):
        if self.wheel_up_var.get():
            self.settings.start_stop_key = "W_UP"
        elif self.wheel_down_var.get():
            self.settings.start_stop_key = "W_DN"
        else:
            self.settings.start_stop_key = self.start_stop_key.get()

    def set_max_key_count(self):
        max_key_count = getattr(self, "max_key_count").get()
        if max_key_count:
            max_key_count = int(max_key_count)
            if 10 <= max_key_count <= 50:
                self.settings.max_key_count = max_key_count
            else:
                self.settings.max_key_count = 10  # Default if out of range
        else:
            self.settings.max_key_count = 10  # Default if empty

    def set_sound_settings(self):
        sound_settings = [(4, "start"), (5, "stop")]

        for row, prefix in sound_settings:
            sound_label = self.grid_slaves(row=row, column=1)[0]
            setattr(
                self.settings,
                f"{prefix}_sound",
                (
                    sound_label["text"]
                    if sound_label["text"] != "Select file"
                    else f"{prefix}.mp3"
                ),
            )

    def save_settings(self):
        settings_dict = asdict(self.settings)
        settings_json = json.dumps(settings_dict).encode("utf-8")
        settings_base64 = base64.b64encode(settings_json).decode("utf-8")
        with open("user_settings.b64", "w") as file:
            file.write(settings_base64)

        logger.debug(f"Saved settings: {settings_dict}")

    def show_warning(self, message):
        self.warning_label.config(text=message)
