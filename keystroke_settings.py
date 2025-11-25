import base64
import json
import platform
import tkinter as tk
from dataclasses import asdict
from tkinter import ttk, messagebox
from typing import Any

from loguru import logger
from keystroke_models import UserSettings
from keystroke_utils import WindowUtils


class KeystrokeSettings(tk.Toplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.title("Settings")
        self.settings = UserSettings()
        self.is_windows = platform.system() == "Windows"

        # UI 상태 관리를 위한 변수 딕셔너리 (Data Binding)
        self.ui_vars: dict[str, tk.Variable] = {}

        self._setup_window()
        self._load_settings()  # 설정 로드 후 UI 생성 (변수 초기화 순서 보장)
        self._create_widgets()

    def _setup_window(self):
        self.grid_columnconfigure((1, 2), weight=1)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", self.on_close)
        WindowUtils.center_window(self)

    def _create_widgets(self):
        # 1. Start/Stop Key Section
        ttk.Label(self, text="Start/Stop Key (시작/중지 키):").grid(
            row=0, column=0, padx=10, pady=5, sticky="w"
        )
        key_frame = ttk.Frame(self)
        key_frame.grid(row=0, column=1, columnspan=3, padx=10, pady=5, sticky="w")

        self.start_stop_combo = ttk.Combobox(
            key_frame, values=["Press Key"], state="readonly"
        )
        self.start_stop_combo.bind("<Key>", self._on_key_press)

        # Platform specific UI
        if self.is_windows:
            self.start_stop_combo.pack(side="left", padx=(0, 10))
            self.ui_vars["use_alt_shift"] = tk.BooleanVar(
                value=self.settings.use_alt_shift_hotkey
            )
            ttk.Checkbutton(
                key_frame,
                text="Use Alt+Shift",
                variable=self.ui_vars["use_alt_shift"],
                command=self._toggle_combo_state,
            ).pack(side="left")
        else:
            self.ui_vars["enable_key"] = tk.BooleanVar(
                value=self.settings.toggle_start_stop_mac
            )
            ttk.Checkbutton(
                key_frame,
                text="Enable Start/Stop Key (Alt+Shift)",
                variable=self.ui_vars["enable_key"],
                command=self._toggle_combo_state,
            ).pack(side="left", padx=(0, 10))
            # Mac은 체크박스 해제 시 콤보박스 숨김/비활성 처리가 원본 로직에 없었으나 구조상 필요 시 여기에 배치
            self.start_stop_combo.pack(side="left")  # 원본 유지

        self._toggle_combo_state()  # 초기 상태 반영

        # 2. Numeric Entries (Time & Delay)
        v_cmd = (self.register(self._validate_numeric), "%P")
        self._add_range_row(
            1, "Key pressed time (키 누름 시간)", "key_pressed_time", v_cmd
        )
        self._add_range_row(
            2, "Delay between loop (루프 간 지연)", "delay_between_loop", v_cmd
        )

        # 3. Epsilon Entry
        ttk.Label(self, text="Cluster epsilon value (클러스터 엡실론 값)").grid(
            row=3, column=0, padx=10, pady=5, sticky="w"
        )
        self.ui_vars["epsilon"] = tk.StringVar(
            value=str(self.settings.cluster_epsilon_value)
        )
        ttk.Entry(
            self,
            textvariable=self.ui_vars["epsilon"],
            validate="key",
            validatecommand=(self.register(self._validate_epsilon), "%P"),
        ).grid(row=3, column=1, padx=10, pady=5)

        # 4. Explanation & Warning
        self._create_explanation()
        self.warning_label = ttk.Label(
            self, text="", foreground="red", background="white"
        )
        self.warning_label.grid(row=8, column=0, columnspan=5, pady=5)
        self._update_warning_text()

        # 5. Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=9, column=0, columnspan=3, pady=10)
        for text, cmd in [
            ("Reset", self.on_reset),
            ("OK", self.on_ok),
            ("Cancel", self.on_close),
        ]:
            ttk.Button(btn_frame, text=text, command=cmd).pack(side="left", padx=5)

    def _add_range_row(self, row: int, label: str, setting_prefix: str, v_cmd: str):
        """Helper to create min/max entry pairs."""
        ttk.Label(self, text=f"{label} (min, max):").grid(
            row=row, column=0, padx=10, pady=5, sticky="w"
        )
        for col, suffix in enumerate(["min", "max"], start=1):
            key = f"{setting_prefix}_{suffix}"
            self.ui_vars[key] = tk.StringVar(value=str(getattr(self.settings, key)))
            ttk.Entry(
                self,
                textvariable=self.ui_vars[key],
                validate="key",
                validatecommand=v_cmd,
            ).grid(row=row, column=col, padx=10, pady=5)

    def _create_explanation(self):
        frame = ttk.LabelFrame(
            self, text="클러스터 엡실론 값 설명 (Cluster Epsilon Value Explanation)"
        )
        frame.grid(row=5, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        text = (
            "• 화면 감지 영역 그룹화 값 (권장: 8-40)\n• 기본값: 20 (100x100 캡처 기준)"
        )
        ttk.Label(frame, text=text, justify="left").pack(padx=10, pady=5, anchor="w")

    def _toggle_combo_state(self):
        """UI Interaction Logic"""
        if self.is_windows:
            state = "disabled" if self.ui_vars["use_alt_shift"].get() else "readonly"
            self.start_stop_combo.config(state=state)
        else:
            # Mac Logic: Update settings immediately as per original logic
            enabled = self.ui_vars["enable_key"].get()
            self.settings.toggle_start_stop_mac = enabled
            if not enabled:
                self.settings.start_stop_key = "DISABLED"
            elif self.settings.start_stop_key == "DISABLED":
                self.settings.start_stop_key = "`"

        # Update Combobox text
        current_key = self.settings.start_stop_key
        if current_key not in ["DISABLED", "Press Key", ""]:
            self.start_stop_combo.set(current_key)
        else:
            self.start_stop_combo.current(0)

    def _on_key_press(self, event):
        if not self.is_windows and not self.ui_vars["enable_key"].get():
            return

        key = event.char.upper() or event.keysym.upper()
        valid_chars = set("`[];',./-=\"")
        if (len(key) == 1 and (key.isalnum() or key in valid_chars)) or (
            key.startswith("F") and key[1:].isdigit()
        ):
            self.start_stop_combo.set(key)
            self.settings.start_stop_key = key

    # 변경 후
    def _load_settings(self):
        try:
            with open("user_settings.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                self.settings = UserSettings(**data)
        except Exception as e:
            logger.error(f"Load failed: {e}")
            self.settings = UserSettings()

    def save_settings(self):
        try:
            with open("user_settings.json", "w", encoding="utf-8") as f:
                json.dump(asdict(self.settings), f, indent=2)
            logger.debug(f"Saved: {self.settings}")
        except Exception as e:
            logger.error(f"Save failed: {e}")

    def on_ok(self):
        # 1. Key Validation
        if self.is_windows:
            self.settings.use_alt_shift_hotkey = self.ui_vars["use_alt_shift"].get()
            if (
                not self.settings.use_alt_shift_hotkey
                and self.settings.start_stop_key in ["Press Key", "", "DISABLED"]
            ):
                return self._warn("Please select a Start/Stop key.")
        else:
            if self.ui_vars["enable_key"].get() and self.settings.start_stop_key in [
                "Press Key",
                "",
                "DISABLED",
            ]:
                return self._warn("Please select a Start/Stop key.")

        # 2. Numeric Validation & Update
        try:
            for prefix in ["key_pressed_time", "delay_between_loop"]:
                mn = int(self.ui_vars[f"{prefix}_min"].get() or 0)
                mx = int(self.ui_vars[f"{prefix}_max"].get() or 0)
                if mn >= mx:
                    return self._warn("Min must be less than Max.")
                if not (50 <= mn and mx <= 500):
                    return self._warn("Values must be between 50 and 500.")
                setattr(self.settings, f"{prefix}_min", mn)
                setattr(self.settings, f"{prefix}_max", mx)

            eps = int(self.ui_vars["epsilon"].get() or 0)
            if not (10 <= eps <= 200):
                return self._warn("Epsilon must be between 10-200.")
            self.settings.cluster_epsilon_value = eps

        except ValueError:
            return self._warn("Invalid numeric input.")

        self.save_settings()
        self.on_close()

    def on_reset(self):
        if messagebox.askokcancel("Warning", "Reset settings?"):
            self.settings = UserSettings()
            self.destroy()
            self.__init__(self.master)  # Re-init to refresh UI cleanly

    def on_close(self, event=None):
        if self.master:
            self.master.settings_window = None
            self.master.load_settings()
            self.master.setup_event_handlers()
        self.destroy()

    def _warn(self, msg):
        self.warning_label.config(text=msg)

    def _update_warning_text(self):
        msg = (
            "Start/Stop: A-Z, 0-9, special keys only."
            if self.is_windows
            else "macOS: Start/Stop is Alt+Shift."
        )
        self.warning_label.config(text=msg)

    @staticmethod
    def _validate_numeric(P):
        if P == "":
            return True
        if not P.isdigit():
            return False
        if len(P) > 1 and P.startswith("0"):  # "01", "007" 등 방지
            return False
        return 0 <= int(P) < 1000

    @staticmethod
    def _validate_epsilon(P):
        return P == "" or (
            P.isdigit() and not (P.startswith("0") and len(P) > 1) and int(P) <= 200
        )
