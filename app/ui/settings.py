from __future__ import annotations

import platform
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from collections.abc import Callable
from typing import Any, ClassVar, Protocol, cast

from loguru import logger
from app.utils.i18n import (
    LANGUAGE_LABELS,
    dual_text_width,
    normalize_language,
    set_language,
    txt,
)
from app.core.models import UserSettings
from app.storage.settings_storage import load_user_settings, save_user_settings
from app.utils.system import WindowUtils, StateUtils
from app.ui import theme

SETTINGS_WINDOW_DEFAULT_GEOMETRY = "800x280"
SETTINGS_WINDOW_MIN_SIZE = (700, 260)


class SettingsHost(Protocol):
    settings_window: object | None

    def load_settings(self) -> None: ...
    def setup_event_handlers(self) -> None: ...


class KeystrokeSettings(tk.Toplevel):
    VALID_CHARS: ClassVar[set[str]] = set("`[];',./-=\"")

    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master)
        self.app_master: object | None = master
        self.is_windows = platform.system() == "Windows"
        self.ui_vars: dict[str, tk.BooleanVar | tk.StringVar] = {}
        self.language_code_by_label: dict[str, str] = {
            v: k for k, v in LANGUAGE_LABELS.items()
        }
        self._settings_nav_labels: dict[str, tk.Label] = {}
        self.nav_rail: tk.Frame
        self.content: ttk.Frame
        self.card_keys: ttk.LabelFrame
        self.card_lang: ttk.LabelFrame
        self.card_timing: ttk.LabelFrame
        self.warning_label: ttk.Label
        self.start_stop_combo: ttk.Combobox
        self.language_combo: ttk.Combobox
        self.button_dock: tk.Frame
        self.button_group: tk.Frame
        self._press_key_label = ""

        self._load_settings()
        self.title(txt("Settings", "설정"))
        self._setup_window()
        self._create_widgets()

    def _setup_window(self) -> None:
        if self.master:
            cast(Any, self).transient(self.master)
        try:
            self.configure(bg=theme.SURFACE_PAPER)
        except tk.TclError:
            pass
        theme.install_styles(self)
        self.geometry(SETTINGS_WINDOW_DEFAULT_GEOMETRY)
        self.minsize(*SETTINGS_WINDOW_MIN_SIZE)
        # Top ContextBar mirrors the main window so each dialog reads as
        # part of the same workstation surface.
        self._build_context_bar().grid(
            row=0, column=0, columnspan=2, sticky="we"
        )
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).grid(
            row=1, column=0, columnspan=2, sticky="we"
        )
        # Two-pane layout: left rail (sections) + right content frame.
        # All section widgets are mounted on self.content so the existing
        # _create_*_section helpers keep using grid as before — they just
        # operate on the content frame's grid instead of the window's.
        self.nav_rail = self._build_settings_nav_rail()
        self.nav_rail.grid(row=2, column=0, sticky="ns", padx=(0, theme.SPACE_2))
        self.content = ttk.Frame(self)
        self.content.grid(row=2, column=1, sticky="nsew")
        self.content.grid_columnconfigure((1, 2), weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", self.on_close)
        self._restore_window_position()
        cast(Any, self).lift()
        cast(Any, self).attributes("-topmost", True)
        self.after(10, lambda: cast(Any, self).attributes("-topmost", False))
        self.grab_set()
        self.focus_force()
        self.after(10, cast(Callable[[], None], cast(Any, self).lift))

    def _build_context_bar(self) -> tk.Frame:
        f = theme.fonts()
        bar = tk.Frame(
            self,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_3,
            pady=theme.SPACE_2,
        )
        tk.Label(
            bar,
            text=txt("Settings", "설정"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_PRIMARY,
            font=f["heading"],
        ).pack(side="left")
        tk.Label(
            bar,
            text=txt("Workstation Defaults", "워크스테이션 기본값"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
        ).pack(side="left", padx=(theme.SPACE_3, 0))
        return bar

    def _build_settings_nav_rail(self) -> tk.Frame:
        f = theme.fonts()
        rail = tk.Frame(
            self,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_2,
            pady=theme.SPACE_3,
            width=160,
        )
        rail.pack_propagate(False)
        tk.Label(
            rail,
            text=txt("SECTIONS", "섹션"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
            anchor="w",
        ).pack(fill="x", pady=(0, theme.SPACE_2))
        for key, en, ko in [
            ("keys", "Start / Stop", "시작 / 중지"),
            ("language", "Language", "언어"),
            ("timing", "Timing", "타이밍"),
        ]:
            label = tk.Label(
                rail,
                text=txt(en, ko),
                bg=theme.SURFACE_PANEL,
                fg=theme.INK_SECONDARY,
                font=f["body"],
                anchor="w",
                padx=theme.SPACE_2,
                pady=theme.SPACE_1,
                cursor="hand2",
            )
            label.pack(fill="x", pady=(0, theme.SPACE_1))
            label.bind(
                "<Button-1>",
                lambda _event, section=key: self._show_settings_section(section),
            )
            self._settings_nav_labels[key] = label
        return rail

    def _show_settings_section(self, section: str) -> None:
        sections = {
            "keys": (self.card_keys, self.warning_label),
            "language": (self.card_lang,),
            "timing": (self.card_timing,),
        }
        for key, widgets in sections.items():
            for widget in widgets:
                if key == section:
                    widget.grid()
                else:
                    widget.grid_remove()

        f = theme.fonts()
        for key, label in self._settings_nav_labels.items():
            selected = key == section
            label.config(
                bg=theme.SURFACE_CANVAS if selected else theme.SURFACE_PANEL,
                fg=theme.SIGNAL_BASE if selected else theme.INK_SECONDARY,
                font=f["body_bold"] if selected else f["body"],
            )

    def _restore_window_position(self) -> None:
        state = StateUtils.load_main_app_state() or {}
        pos = StateUtils.parse_slash_int_pair(state.get("settings_position"))
        if pos is not None:
            try:
                self.geometry(f"{SETTINGS_WINDOW_DEFAULT_GEOMETRY}+{pos[0]}+{pos[1]}")
                return
            except tk.TclError:
                pass
        WindowUtils.center_window(self)

    def _save_window_position(self) -> None:
        try:
            StateUtils.save_main_app_state(
                settings_position=f"{self.winfo_x()}/{self.winfo_y()}"
            )
        except tk.TclError:
            pass

    def _load_settings(self) -> None:
        s_file = Path("user_settings.json")
        self.settings, _can_save = load_user_settings(s_file)
        self.settings.language = normalize_language(self.settings.language)
        set_language(self.settings.language)

    def _save_settings(self) -> None:
        try:
            save_user_settings(self.settings)
            logger.debug(f"Saved: {self.settings}")
        except Exception as e:
            logger.error(f"Save failed: {e}")

    def _create_widgets(self) -> None:
        # 3-section card layout: Start/Stop · Language · Timing.
        self.card_keys = ttk.LabelFrame(
            self.content, text=txt("Start / Stop", "시작 / 중지")
        )
        self.card_keys.grid(
            row=0, column=0, columnspan=5, padx=theme.SPACE_2, pady=(theme.SPACE_2, theme.SPACE_1), sticky="we"
        )
        self.card_keys.grid_columnconfigure(1, weight=1)

        self.card_lang = ttk.LabelFrame(
            self.content, text=txt("Language", "언어")
        )
        self.card_lang.grid(
            row=1, column=0, columnspan=5, padx=theme.SPACE_2, pady=theme.SPACE_1, sticky="we"
        )
        self.card_lang.grid_columnconfigure(1, weight=1)

        self.card_timing = ttk.LabelFrame(
            self.content, text=txt("Timing", "타이밍")
        )
        self.card_timing.grid(
            row=2, column=0, columnspan=5, padx=theme.SPACE_2, pady=theme.SPACE_1, sticky="we"
        )
        self.card_timing.grid_columnconfigure((1, 2), weight=1)

        self._create_key_section()
        self._create_language_section()

        # 2. Numeric Entries
        v_cmd = (self.register(self._validate_numeric), "%P")
        self._add_range_row(
            0, txt("Key pressed time", "키 누름 시간"), "key_pressed_time", v_cmd
        )
        self._add_range_row(
            1, txt("Delay between loop", "루프 간 지연"), "delay_between_loop", v_cmd
        )

        # 3. Warning callout (uses status.warn tones for a calmer feel)
        self.warning_label = ttk.Label(
            self.content,
            text="",
            foreground=theme.STATUS_WARN_FG,
            background=theme.STATUS_WARN_BG,
            padding=(theme.SPACE_2, theme.SPACE_1),
        )
        self.warning_label.grid(row=3, column=0, columnspan=5, padx=theme.SPACE_2, pady=theme.SPACE_1, sticky="we")
        self.warning_label.configure(wraplength=420)
        self._update_warning_text()

        # 4. Buttons
        self._create_buttons()
        self._show_settings_section("keys")

    def _create_key_section(self) -> None:
        ttk.Label(self.card_keys, text=txt("Start/Stop Key:", "시작/중지 키:")).grid(
            row=0, column=0, padx=10, pady=5, sticky="w"
        )
        key_frame = ttk.Frame(self.card_keys)
        key_frame.grid(row=0, column=1, columnspan=3, padx=10, pady=5, sticky="w")

        self._press_key_label = txt("Press Key", "키 입력")
        self.start_stop_combo = ttk.Combobox(
            key_frame, values=[self._press_key_label], state="readonly", width=14
        )
        self.start_stop_combo.bind("<Key>", self._on_key_press)

        if self.is_windows:
            self.start_stop_combo.pack(side="left", padx=(0, 10))
            self.ui_vars["use_alt_shift"] = tk.BooleanVar(
                value=self.settings.use_alt_shift_hotkey
            )
            ttk.Checkbutton(
                key_frame,
                text=txt("Use Alt+Shift", "Alt+Shift 사용"),
                variable=self.ui_vars["use_alt_shift"],
                command=self._toggle_combo_state,
            ).pack(side="left")
        else:
            self.ui_vars["enable_key"] = tk.BooleanVar(
                value=self.settings.toggle_start_stop_mac
            )
            ttk.Checkbutton(
                key_frame,
                text=txt(
                    "Enable Start/Stop Key (Option+Shift)",
                    "시작/중지 키 사용 (Option+Shift)",
                ),
                variable=self.ui_vars["enable_key"],
                command=self._toggle_combo_state,
            ).pack(side="left", padx=(0, 10))
            self.start_stop_combo.pack(side="left")

        self._toggle_combo_state()

    def _create_language_section(self) -> None:
        ttk.Label(self.card_lang, text=txt("Language:", "언어:")).grid(
            row=0, column=0, padx=10, pady=5, sticky="w"
        )
        self.language_combo = ttk.Combobox(self.card_lang, state="readonly")
        labels = [LANGUAGE_LABELS[code] for code in ("en", "ko")]
        self.language_combo["values"] = labels
        selected_label = LANGUAGE_LABELS.get(
            normalize_language(self.settings.language), LANGUAGE_LABELS["en"]
        )
        self.language_combo.set(selected_label)
        self.language_combo.grid(row=0, column=1, padx=10, pady=5, sticky="w")

    def _create_buttons(self) -> None:
        # Run-dock (bottom action band) — separator above + panel-tone strip
        # under it so this reads as the same surface as the main window.
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).grid(
            row=3, column=0, columnspan=2, sticky="we"
        )
        dock = tk.Frame(
            self,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_3,
            pady=theme.SPACE_2,
        )
        dock.grid(row=4, column=0, columnspan=2, sticky="we")
        self.button_dock = dock
        button_group = tk.Frame(dock, bg=theme.SURFACE_PANEL)
        button_group.pack(side=tk.RIGHT)
        self.button_group = button_group
        button_defs: list[tuple[str, Callable[[], None], tuple[str, str], str]] = [
            (txt("Reset", "초기화"), self.on_reset, ("Reset", "초기화"), "Danger.TButton"),
            (txt("OK", "확인"), self.on_ok, ("OK", "확인"), "Accent.TButton"),
            (txt("Cancel", "취소"), self.on_close, ("Cancel", "취소"), "Outline.TButton"),
        ]
        for text, cmd, width_pair, style in button_defs:
            ttk.Button(
                button_group,
                text=text,
                width=dual_text_width(*width_pair, padding=3, min_width=7),
                command=cmd,
                style=style,
            ).pack(side="left", padx=5)

    def _add_range_row(
        self, row: int, label: str, setting_prefix: str, v_cmd: tuple[str, str]
    ) -> None:
        ttk.Label(
            self.card_timing, text=f"{label} ({txt('min, max', '최소, 최대')}):"
        ).grid(row=row, column=0, padx=10, pady=5, sticky="w")
        for col, suffix in enumerate(["min", "max"], start=1):
            key = f"{setting_prefix}_{suffix}"
            self.ui_vars[key] = tk.StringVar(value=str(getattr(self.settings, key)))
            ttk.Entry(
                self.card_timing,
                textvariable=self.ui_vars[key],
                validate="key",
                validatecommand=v_cmd,
            ).grid(row=row, column=col, padx=10, pady=5, sticky="w")

    def _bool_var(self, key: str) -> tk.BooleanVar:
        return cast(tk.BooleanVar, self.ui_vars[key])

    def _str_var(self, key: str) -> tk.StringVar:
        return cast(tk.StringVar, self.ui_vars[key])

    def _toggle_combo_state(self) -> None:
        if self.is_windows:
            state = "disabled" if self._bool_var("use_alt_shift").get() else "readonly"
            self.start_stop_combo.config(state=state)
        else:
            enabled = self._bool_var("enable_key").get()
            self.settings.toggle_start_stop_mac = enabled
            self.settings.start_stop_key = (
                "`"
                if enabled and self.settings.start_stop_key == "DISABLED"
                else ("DISABLED" if not enabled else self.settings.start_stop_key)
            )

        current_key = self.settings.start_stop_key
        if current_key not in ("DISABLED", self._press_key_label, ""):
            self.start_stop_combo.set(current_key)
        else:
            self.start_stop_combo.current(0)

    def _on_key_press(self, event: tk.Event[tk.Misc]) -> None:
        if not self.is_windows and not self._bool_var("enable_key").get():
            return

        key = (event.char or event.keysym).upper()
        is_valid = (len(key) == 1 and (key.isalnum() or key in self.VALID_CHARS)) or (
            key.startswith("F") and key[1:].isdigit()
        )
        if is_valid:
            self.start_stop_combo.set(key)
            self.settings.start_stop_key = key

    def on_ok(self) -> None:
        selected_language = self.language_code_by_label.get(
            self.language_combo.get(), "en"
        )
        self.settings.language = normalize_language(selected_language)
        set_language(self.settings.language)

        # 1. Key Validation
        invalid_keys = (self._press_key_label, "", "DISABLED")
        if self.is_windows:
            self.settings.use_alt_shift_hotkey = self._bool_var(
                "use_alt_shift"
            ).get()
            if (
                not self.settings.use_alt_shift_hotkey
                and self.settings.start_stop_key in invalid_keys
            ):
                return self._warn(
                    txt("Please select a Start/Stop key.", "시작/중지 키를 선택하세요.")
                )
        elif (
            self._bool_var("enable_key").get()
            and self.settings.start_stop_key in invalid_keys
        ):
            return self._warn(
                txt("Please select a Start/Stop key.", "시작/중지 키를 선택하세요.")
            )

        # 2. Numeric Validation & Update
        try:
            for prefix in ("key_pressed_time", "delay_between_loop"):
                mn = int(self._str_var(f"{prefix}_min").get() or 0)
                mx = int(self._str_var(f"{prefix}_max").get() or 0)
                if mn >= mx:
                    return self._warn(txt("Min must be less than Max.", "최소값은 최대값보다 작아야 합니다."))
                if not (50 <= mn and mx <= 500):
                    return self._warn(txt("Values must be between 50 and 500.", "값은 50~500 범위여야 합니다."))
                setattr(self.settings, f"{prefix}_min", mn)
                setattr(self.settings, f"{prefix}_max", mx)

        except ValueError:
            return self._warn(txt("Invalid numeric input.", "숫자 입력이 올바르지 않습니다."))

        self._save_settings()
        self.on_close()

    def on_reset(self) -> None:
        if messagebox.askokcancel(
            txt("Warning", "경고"),
            txt("Reset settings?", "설정을 초기화하시겠습니까?"),
            parent=self,
        ):
            self._save_window_position()
            self.settings = UserSettings()
            replacement = KeystrokeSettings(self.master)
            if self.app_master is not None and hasattr(
                self.app_master, "settings_window"
            ):
                cast(SettingsHost, self.app_master).settings_window = replacement
            self.destroy()

    def on_close(self, event: tk.Event[tk.Misc] | None = None) -> None:
        self._save_window_position()
        if self.app_master is not None and hasattr(self.app_master, "settings_window"):
            host = cast(SettingsHost, self.app_master)
            host.settings_window = None
            if hasattr(host, "load_settings"):
                host.load_settings()
            if hasattr(host, "setup_event_handlers"):
                host.setup_event_handlers()
        self.destroy()

    def _warn(self, msg: str) -> None:
        self.warning_label.config(text=msg)

    def _update_warning_text(self) -> None:
        msg = (
            txt("Start/Stop: A-Z, 0-9, special keys only.", "시작/중지: A-Z, 0-9, 특수키만 허용됩니다.")
            if self.is_windows
            else txt("macOS: Start/Stop is Option+Shift.", "macOS: 시작/중지는 Option+Shift입니다.")
        )
        self.warning_label.config(text=msg)

    @staticmethod
    def _validate_numeric(P: str) -> bool:
        return P == "" or (
            P.isdigit() and not (P.startswith("0") and len(P) > 1) and int(P) < 1000
        )
