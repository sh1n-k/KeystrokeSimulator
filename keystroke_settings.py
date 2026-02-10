import json
import platform
import tkinter as tk
from dataclasses import asdict, fields
from pathlib import Path
from tkinter import ttk, messagebox

from loguru import logger
from keystroke_models import UserSettings
from keystroke_utils import WindowUtils


class KeystrokeSettings(tk.Toplevel):
    VALID_CHARS = set("`[];',./-=\"")

    def __init__(self, master=None):
        super().__init__(master)
        self.title("Settings")
        self.is_windows = platform.system() == "Windows"
        self.ui_vars: dict[str, tk.Variable] = {}

        self._load_settings()
        self._setup_window()
        self._create_widgets()

    def _setup_window(self):
        self.grid_columnconfigure((1, 2), weight=1)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", self.on_close)
        WindowUtils.center_window(self)

    def _load_settings(self):
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
        except Exception as e:
            logger.error(f"Load failed: {e}")
            self.settings = UserSettings()

    def _save_settings(self):
        try:
            Path("user_settings.json").write_text(
                json.dumps(asdict(self.settings), indent=2), encoding="utf-8"
            )
            logger.debug(f"Saved: {self.settings}")
        except Exception as e:
            logger.error(f"Save failed: {e}")

    def _create_widgets(self):
        # 1. Start/Stop Key Section
        self._create_key_section()

        # 2. Numeric Entries
        v_cmd = (self.register(self._validate_numeric), "%P")
        self._add_range_row(
            1, "Key pressed time (키 누름 시간)", "key_pressed_time", v_cmd
        )
        self._add_range_row(
            2, "Delay between loop (루프 간 지연)", "delay_between_loop", v_cmd
        )

        # 3. Warning
        self.warning_label = ttk.Label(
            self, text="", foreground="red", background="white"
        )
        self.warning_label.grid(row=3, column=0, columnspan=5, pady=5)
        self._update_warning_text()

        # 4. Buttons
        self._create_buttons()

    def _create_key_section(self):
        ttk.Label(self, text="Start/Stop Key (시작/중지 키):").grid(
            row=0, column=0, padx=10, pady=5, sticky="w"
        )
        key_frame = ttk.Frame(self)
        key_frame.grid(row=0, column=1, columnspan=3, padx=10, pady=5, sticky="w")

        self.start_stop_combo = ttk.Combobox(
            key_frame, values=["Press Key"], state="readonly"
        )
        self.start_stop_combo.bind("<Key>", self._on_key_press)

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
            self.start_stop_combo.pack(side="left")

        self._toggle_combo_state()

    def _create_buttons(self):
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=10)
        for text, cmd in [
            ("Reset", self.on_reset),
            ("OK", self.on_ok),
            ("Cancel", self.on_close),
        ]:
            ttk.Button(btn_frame, text=text, command=cmd).pack(side="left", padx=5)

    def _add_range_row(self, row: int, label: str, setting_prefix: str, v_cmd):
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

    def _toggle_combo_state(self):
        if self.is_windows:
            state = "disabled" if self.ui_vars["use_alt_shift"].get() else "readonly"
            self.start_stop_combo.config(state=state)
        else:
            enabled = self.ui_vars["enable_key"].get()
            self.settings.toggle_start_stop_mac = enabled
            self.settings.start_stop_key = (
                "`"
                if enabled and self.settings.start_stop_key == "DISABLED"
                else ("DISABLED" if not enabled else self.settings.start_stop_key)
            )

        current_key = self.settings.start_stop_key
        if current_key not in ("DISABLED", "Press Key", ""):
            self.start_stop_combo.set(current_key)
        else:
            self.start_stop_combo.current(0)

    def _on_key_press(self, event):
        if not self.is_windows and not self.ui_vars["enable_key"].get():
            return

        key = (event.char or event.keysym).upper()
        is_valid = (len(key) == 1 and (key.isalnum() or key in self.VALID_CHARS)) or (
            key.startswith("F") and key[1:].isdigit()
        )
        if is_valid:
            self.start_stop_combo.set(key)
            self.settings.start_stop_key = key

    def on_ok(self):
        # 1. Key Validation
        invalid_keys = ("Press Key", "", "DISABLED")
        if self.is_windows:
            self.settings.use_alt_shift_hotkey = self.ui_vars["use_alt_shift"].get()
            if (
                not self.settings.use_alt_shift_hotkey
                and self.settings.start_stop_key in invalid_keys
            ):
                return self._warn("Please select a Start/Stop key.")
        elif (
            self.ui_vars["enable_key"].get()
            and self.settings.start_stop_key in invalid_keys
        ):
            return self._warn("Please select a Start/Stop key.")

        # 2. Numeric Validation & Update
        try:
            for prefix in ("key_pressed_time", "delay_between_loop"):
                mn = int(self.ui_vars[f"{prefix}_min"].get() or 0)
                mx = int(self.ui_vars[f"{prefix}_max"].get() or 0)
                if mn >= mx:
                    return self._warn("Min must be less than Max.")
                if not (50 <= mn and mx <= 500):
                    return self._warn("Values must be between 50 and 500.")
                setattr(self.settings, f"{prefix}_min", mn)
                setattr(self.settings, f"{prefix}_max", mx)

        except ValueError:
            return self._warn("Invalid numeric input.")

        self._save_settings()
        self.on_close()

    def on_reset(self):
        if messagebox.askokcancel("Warning", "Reset settings?"):
            self.settings = UserSettings()
            self.destroy()
            KeystrokeSettings(self.master)

    def on_close(self, event=None):
        if self.master and hasattr(self.master, "settings_window"):
            self.master.settings_window = None
            if hasattr(self.master, "load_settings"):
                self.master.load_settings()
            if hasattr(self.master, "setup_event_handlers"):
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
        return P == "" or (
            P.isdigit() and not (P.startswith("0") and len(P) > 1) and int(P) < 1000
        )

