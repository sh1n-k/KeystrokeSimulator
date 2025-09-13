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
        # [추가됨] Windows 전용 BooleanVar 초기화
        if self.is_windows:
            self.use_alt_shift_var = tk.BooleanVar()
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
    # [수정됨] Windows 환경에 Alt+Shift 체크박스 추가
    def _create_start_stop_key(self):
        ttk.Label(self, text="Start/Stop Key (시작/중지 키):").grid(
            row=0, column=0, padx=10, pady=5, sticky=tk.W
        )

        key_frame = ttk.Frame(self)
        key_frame.grid(row=0, column=1, columnspan=3, padx=10, pady=5, sticky=tk.W)

        if not self.is_windows:
            self.enable_key_var = tk.BooleanVar(value=True)
            self.enable_key_checkbox = ttk.Checkbutton(
                key_frame,
                text="Enable Start/Stop Key (Alt+Shift)",
                variable=self.enable_key_var,
                command=self._on_enable_key_change,
            )
            self.enable_key_checkbox.pack(side=tk.LEFT, padx=(0, 10))
            self.start_stop_key = ttk.Combobox(
                self, values=["Press Key"], state="readonly"
            )
            self.start_stop_key.current(0)
            self.start_stop_key.bind("<Key>", self._on_key_press)
        else:
            self.start_stop_key = ttk.Combobox(
                key_frame, values=["Press Key"], state="readonly"
            )
            self.start_stop_key.pack(side=tk.LEFT, padx=(0, 10))
            self.start_stop_key.current(0)
            self.start_stop_key.bind("<Key>", self._on_key_press)

            # [추가됨] Alt+Shift 단축키 사용 체크박스
            self.alt_shift_checkbox = ttk.Checkbutton(
                key_frame,
                text="Use Alt+Shift",
                variable=self.use_alt_shift_var,
                command=self._on_alt_shift_toggle,
            )
            self.alt_shift_checkbox.pack(side=tk.LEFT)

    # [추가됨] Alt+Shift 체크박스 상태에 따라 Combobox 활성화/비활성화 처리
    def _on_alt_shift_toggle(self):
        """Disables or enables the key selection combobox based on the checkbox state."""
        if self.use_alt_shift_var.get():
            self.start_stop_key.config(state="disabled")
        else:
            self.start_stop_key.config(state="readonly")

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
        pass

    def _create_epsilon_explanation(self):
        explanation_frame = ttk.LabelFrame(
            self, text="클러스터 엡실론 값 설명 (Cluster Epsilon Value Explanation)"
        )
        explanation_frame.grid(
            row=5, column=0, columnspan=3, padx=10, pady=10, sticky="ew"
        )
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
            warning_text = "On macOS, the start/stop hotkey is Alt+Shift.\n\nmacOS에서는 start/stop 단축키가 Alt+Shift로 고정됩니다."
        self.warning_label.config(text=warning_text)

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

    # [수정됨] 설정 파일 로드 시 Windows Alt+Shift 체크박스 상태 반영
    def _update_start_stop_key(self):
        if not self.is_windows:
            self.enable_key_var.set(self.settings.toggle_start_stop_mac)
        else:
            self.start_stop_key.set(self.settings.start_stop_key)
            self.use_alt_shift_var.set(self.settings.use_alt_shift_hotkey)
            self._on_alt_shift_toggle()

    def _update_time_entries(self):
        self._set_entry_values(1, "key_pressed_time")
        self._set_entry_values(2, "delay_between_loop")

    def _update_num_of_events(self):
        self._set_num_of_events_value()

    def _update_max_key_count(self):
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

    def _on_enable_key_change(self):
        if not self.is_windows:
            key_enabled = self.enable_key_var.get()
            self.settings.toggle_start_stop_mac = key_enabled
            if not key_enabled:
                self.settings.start_stop_key = "DISABLED"
            elif self.settings.start_stop_key == "DISABLED":
                self.settings.start_stop_key = "`"

    def _on_key_press(self, event):
        if not self.is_windows and not self.enable_key_var.get():
            return
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
        return True

    def validate_start_stop_key(self):
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

    def on_reset(self):
        if messagebox.askokcancel(
            "Warning", f"Resets the values.\n설정값이 초기화 됩니다."
        ):
            self.settings = UserSettings()
            self._update_ui_from_settings()
            self.warning_label.config(
                text="Settings have been reset to default values."
            )

    # [수정됨] OK 버튼 클릭 시 Windows Alt+Shift 설정 저장
    def on_ok(self):
        if not self.is_windows:
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
            self.settings.use_alt_shift_hotkey = self.use_alt_shift_var.get()
            if not self.settings.use_alt_shift_hotkey:
                if not self.validate_start_stop_key():
                    return
        if not self.validate_and_set_time_settings():
            return
        self.save_settings()
        self.on_close()

    def on_close(self, event=None):
        self.master.settings_window = None
        self.master.load_settings()
        self.master.setup_event_handlers()
        self.destroy()

    def set_max_key_count(self):
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
