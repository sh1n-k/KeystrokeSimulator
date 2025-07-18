import base64
import json
import platform
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
        self.is_windows = platform.system() == "Windows"
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
        self._create_epsilon_explanation()
        self._create_buttons()
        self._create_warning_label()

    # UI Creation Methods
    def _create_start_stop_key(self):
        ttk.Label(self, text="Start/Stop Key (시작/중지 키):").grid(
            row=0, column=0, padx=10, pady=5, sticky=tk.W
        )

        # Create frame for Start/Stop key controls
        key_frame = ttk.Frame(self)
        key_frame.grid(row=0, column=1, columnspan=3, padx=10, pady=5, sticky=tk.W)

        # For macOS, only show enable/disable checkbox
        if not self.is_windows:
            self.enable_key_var = tk.BooleanVar(value=True)
            self.enable_key_checkbox = ttk.Checkbutton(
                key_frame,
                text="Enable Start/Stop Key (시작/중지 키 활성화)",
                variable=self.enable_key_var,
                command=self._on_enable_key_change,
            )
            self.enable_key_checkbox.pack(side=tk.LEFT, padx=(0, 10))

            # Create but don't display the combo box (needed for internal logic)
            self.start_stop_key = ttk.Combobox(
                self, values=["Press Key"], state="readonly"
            )
            self.start_stop_key.current(0)
            self.start_stop_key.bind("<Key>", self._on_key_press)
        else:
            # Add key selection dropdown (Windows only)
            self.start_stop_key = ttk.Combobox(
                key_frame, values=["Press Key"], state="readonly"
            )
            self.start_stop_key.pack(side=tk.LEFT, padx=(0, 10))
            self.start_stop_key.current(0)
            self.start_stop_key.bind("<Key>", self._on_key_press)

    def _create_time_entries(self):
        validation_command = (self.register(self._validate_numeric_entry), "%P")
        self._create_entry_pair(
            "Key pressed time (키 누름 시간) (min, max):", 1, validation_command
        )
        self._create_entry_pair(
            "Delay between loop (루프 간 지연) (min, max):", 2, validation_command
        )

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
        ttk.Label(self, text="Cluster epsilon value (클러스터 엡실론 값)").grid(
            row=3, column=0, padx=10, pady=5, sticky=tk.W
        )
        setattr(
            self,
            f"cluster_epsilon_value",
            ttk.Entry(
                self,
                validate="key",
                validatecommand=(
                    self.register(self._validate_cluster_epsilon_value),
                    "%P",
                ),
            ),
        )
        getattr(self, f"cluster_epsilon_value").grid(row=3, column=1, padx=10, pady=5)

    def _create_max_key_count_entry(self):
        # 이 옵션은 현재 프로세서에서 사용되지 않으므로 제거
        # TODO: 향후 필요시 실제 기능에 맞게 재구현
        pass

    def _create_epsilon_explanation(self):
        # Create explanation frame
        explanation_frame = ttk.LabelFrame(
            self, text="클러스터 엡실론 값 설명 (Cluster Epsilon Value Explanation)"
        )
        explanation_frame.grid(
            row=5, column=0, columnspan=3, padx=10, pady=10, sticky="ew"
        )

        # Explanation text
        explanation_text = (
            "• 화면에서 감지할 영역들을 그룹화하는 데 사용되는 값입니다\n"
            "• 값이 클수록 더 넓은 범위의 점들이 하나의 그룹으로 묶입니다\n"
            "• 값이 작을수록 더 세밀하게 영역을 구분합니다\n"
            "• 권장 범위: 8-12 (정밀), 15-25 (일반), 30-40 (큰 요소), 50+ (넓은 영역)\n"
            "• 기본값: 20 (100x100 캡처 이미지에 최적화)\n"
            "• 캡처 이미지 크기: 100x100 픽셀"
        )

        explanation_label = ttk.Label(
            explanation_frame, text=explanation_text, justify=tk.LEFT
        )
        explanation_label.pack(padx=10, pady=5, anchor="w")

    def _create_buttons(self):
        ttk.Button(self, text="Reset", command=self.on_reset).grid(
            row=9, column=0, padx=10, pady=10
        )
        ttk.Button(self, text="OK", command=self.on_ok).grid(
            row=9, column=1, padx=10, pady=10
        )
        ttk.Button(self, text="Cancel", command=self.on_close).grid(
            row=9, column=2, padx=10, pady=10
        )

    def _create_warning_label(self):
        self.warning_label = ttk.Label(
            self, text="\n", background="white", foreground="red"
        )
        self.warning_label.grid(row=8, column=0, columnspan=5, pady=5)

        if self.is_windows:
            warning_text = "For Start/Stop, set only A-Z, 0-9, and special character keys.\n\nStart/Stop 은 A-Z, 0-9, 특수문자 키만 설정하세요."
        else:
            warning_text = "On macOS, you can only enable/disable the start/stop key function.\n\nmacOS에서는 start/stop key 기능의 사용 여부만 선택할 수 있습니다."

        self.warning_label.config(text=warning_text)

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

    def _update_start_stop_key(self):
        if not self.is_windows:
            # For macOS, use the toggle_start_stop_mac property to set checkbox state
            self.enable_key_var.set(self.settings.toggle_start_stop_mac)
        else:
            # For Windows, handle key selection
            self.start_stop_key.set(self.settings.start_stop_key)
            self.start_stop_key.config(state="readonly")

    def _update_time_entries(self):
        self._set_entry_values(1, "key_pressed_time")
        self._set_entry_values(2, "delay_between_loop")

    def _update_num_of_events(self):
        self._set_num_of_events_value()

    def _update_max_key_count(self):
        # Max Key Count 옵션이 제거되었으므로 비어있는 메서드
        pass

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
        getattr(self, "cluster_epsilon_value").delete(0, tk.END)
        getattr(self, "cluster_epsilon_value").insert(
            0, str(getattr(self.settings, f"cluster_epsilon_value"))
        )

    # Event Handlers
    def _on_enable_key_change(self):
        # For macOS: Enable/disable the start/stop key
        if not self.is_windows:
            key_enabled = self.enable_key_var.get()

            # Update toggle state in settings
            self.settings.toggle_start_stop_mac = key_enabled

            # Update the stored key setting
            if not key_enabled:
                self.settings.start_stop_key = "DISABLED"
            elif self.settings.start_stop_key == "DISABLED":
                # If re-enabling, set to default key
                self.settings.start_stop_key = "`"

    def _on_key_press(self, event):
        if not self.is_windows and not self.enable_key_var.get():
            return  # Ignore key press if key is disabled on macOS

        valid_keys = (
            set(f"F{i}" for i in range(1, 13))
            | set(chr(i) for i in range(ord("A"), ord("Z") + 1))
            | set(chr(i) for i in range(ord("0"), ord("9") + 1))
            | set("`[];',./-=\"")
        )

        key = event.char.upper() or event.keysym.upper()
        if key in valid_keys:
            self.start_stop_key.set(key)
            self.settings.start_stop_key = self.start_stop_key.get()

    # Validation Methods
    @staticmethod
    def _validate_numeric_entry(P):
        return P == "" or (P.isdigit() and 0 <= int(P) < 1000 and not P.startswith("0"))

    @staticmethod
    def _validate_cluster_epsilon_value(P):
        if P == "":
            return True
        if not P.isdigit():
            return False
        if P.startswith("0") and len(P) > 1:
            return False
        try:
            value = int(P)
            return 0 <= value <= 200
        except ValueError:
            return False

    @staticmethod
    def _validate_max_key_count(P):
        # Max Key Count 옵션이 제거되었으므로 비어있는 메서드
        return True

    def validate_start_stop_key(self):
        # Skip validation if on macOS and key is disabled
        if not self.is_windows and not self.enable_key_var.get():
            return True

        if self.settings.start_stop_key in ["Press Key", "", "DISABLED"]:
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

        cluster_epsilon_value = int(getattr(self, f"cluster_epsilon_value").get() or 1)
        if cluster_epsilon_value < 10 or cluster_epsilon_value > 200:
            self.show_warning(
                "Select the value of epsilon between 10-200.\n클러스터 입실론 값은 10-200 사이에서 선택하세요."
            )
            return False
        setattr(self.settings, "cluster_epsilon_value", cluster_epsilon_value)

        # Max Key Count 옵션이 제거되었으므로 삭제
        # max_key_count 처리 제거

        return True

    def validate_min_max_values(self, min_value, max_value):
        if min_value >= max_value:
            self.show_warning(
                "Check the Min and Max values.\n최소, 최대값을 확인하세요."
            )
            return False
        if min_value < 50 or max_value > 500:
            self.show_warning(
                "The Min value cannot be set below 50 and the Max value cannot be set above 500.\n"
                "Min 값은 50 미만,  Max 값은 500 초과할 수 없습니다."
            )
            return False
        return True

    # Action Methods
    def on_reset(self):
        if messagebox.askokcancel(
            "Warning", f"Resets the values.\n설정값이 초기화 됩니다."
        ):
            self.settings = UserSettings()  # Reset to default values
            self._update_ui_from_settings()
            self.warning_label.config(
                text="Settings have been reset to default values."
            )

    def on_ok(self):
        # For macOS, handle key enable/disable differently
        if not self.is_windows:
            # Save the toggle state
            self.settings.toggle_start_stop_mac = self.enable_key_var.get()

            if not self.enable_key_var.get():
                self.settings.start_stop_key = "DISABLED"
            elif (
                self.settings.start_stop_key == "DISABLED"
                or self.settings.start_stop_key in ["Press Key", ""]
            ):
                self.show_warning("Please select a Start/Stop key.")
                return
        else:
            if not self.validate_start_stop_key():
                return

        if not self.validate_and_set_time_settings():
            return
        # Max Key Count 옵션이 제거되었으므로 set_max_key_count() 호출 제거
        self.save_settings()

        self.on_close()

    def on_close(self, event=None):
        self.master.settings_window = None
        self.master.load_settings()
        self.master.setup_event_handlers()
        self.destroy()

    # Helper Methods
    def set_max_key_count(self):
        # Max Key Count 옵션이 제거되었으므로 비어있는 메서드
        pass

    def save_settings(self):
        settings_dict = asdict(self.settings)
        settings_json = json.dumps(settings_dict).encode("utf-8")
        settings_base64 = base64.b64encode(settings_json).decode("utf-8")
        with open("user_settings.b64", "w") as file:
            file.write(settings_base64)

        logger.debug(f"Saved settings: {settings_dict}")

    def show_warning(self, message):
        self.warning_label.config(text=message)
