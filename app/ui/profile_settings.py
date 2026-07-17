from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any, Literal, Optional, cast

from loguru import logger

from app.core.models import ProfileModel
from app.ui import theme
from app.utils.i18n import txt
from app.utils.runtime_toggle import (
    display_runtime_toggle_trigger,
    normalize_runtime_toggle_capture_key,
    normalize_runtime_toggle_trigger,
    normalize_runtime_toggle_wheel_event,
)

UI_PAD_XS = theme.SPACE_1
UI_PAD_SM = theme.SPACE_1
UI_PAD_MD = theme.SPACE_2

class ProfileFrame(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        name: str,
        fav: bool,
        on_change: Optional[Callable[[], None]] = None,
        *,
        profiles_dir: Path,
    ) -> None:
        super().__init__(master)
        self.on_change = on_change
        self._original_name = name
        self._profiles_dir = profiles_dir
        self.fav_var = tk.BooleanVar(value=fav)

        ttk.Label(self, text=txt("Profile Name:", "프로필 이름:")).pack(
            side=tk.LEFT, padx=(0, UI_PAD_SM)
        )
        self.entry = ttk.Entry(self, width=24)
        self.entry.pack(side=tk.LEFT, padx=(0, UI_PAD_MD))
        self.entry.insert(0, name)
        ttk.Checkbutton(
            self, text=txt("Favorite", "즐겨찾기"), variable=self.fav_var
        ).pack(side=tk.LEFT, padx=(0, UI_PAD_MD))
        self.lbl_warn = ttk.Label(self, text="", foreground=theme.STATUS_ERROR_FG)
        self.lbl_warn.pack(side=tk.LEFT, padx=(UI_PAD_SM, 0))

        def on_entry_changed(_event: tk.Event[tk.Misc]) -> None:
            self._notify_changed()

        def on_favorite_changed(*_args: str) -> None:
            self._notify_changed()

        self.entry.bind("<KeyRelease>", on_entry_changed)
        self.entry.bind("<FocusOut>", on_entry_changed)
        self.fav_var.trace_add("write", on_favorite_changed)

    def get_data(self) -> tuple[str, bool]:
        return self.entry.get(), self.fav_var.get()

    def _validate(self) -> None:
        name = self.entry.get().strip()
        if not name:
            self.lbl_warn.config(
                text=txt("Enter profile name", "프로필 이름을 입력하세요")
            )
            return
        if name != self._original_name and (self._profiles_dir / f"{name}.json").exists():
            self.lbl_warn.config(
                text=txt(f"'{name}' already exists", f"'{name}' 이미 존재합니다")
            )
            return
        self.lbl_warn.config(text="")

    def _notify_changed(self) -> None:
        self._validate()
        if self.on_change:
            self.on_change()


class RuntimeToggleSettingsFrame(ttk.LabelFrame):
    def __init__(
        self,
        master: tk.Misc,
        profile: ProfileModel,
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(
            master, text=txt("Runtime Event Group", "실행 중 추가 이벤트 묶음")
        )
        self.on_change = on_change
        initial_trigger = normalize_runtime_toggle_trigger(
            getattr(profile, "runtime_toggle_key", None)
        )
        self._selected_trigger = initial_trigger
        self._capture_active = False
        self._capture_bindings: list[tuple[tk.Misc, str, str]] = []
        self.enabled_var = tk.BooleanVar(
            value=bool(getattr(profile, "runtime_toggle_enabled", False))
        )
        self.key_var = tk.StringVar(
            value=display_runtime_toggle_trigger(initial_trigger) or ""
        )
        self.capture_status_var = tk.StringVar(value="")

        self.columnconfigure(2, weight=1)

        ttk.Checkbutton(
            self,
            text=txt("Enable", "사용"),
            variable=self.enabled_var,
            command=self._notify_changed,
        ).grid(row=0, column=0, padx=(UI_PAD_MD, UI_PAD_SM), pady=UI_PAD_SM, sticky="w")

        ttk.Label(self, text=txt("Toggle trigger:", "토글 트리거:")).grid(
            row=0, column=1, padx=(0, UI_PAD_SM), pady=UI_PAD_SM, sticky="w"
        )
        self.key_entry = ttk.Entry(
            self,
            textvariable=self.key_var,
            state="readonly",
            width=22,
        )
        self.key_entry.grid(
            row=0, column=2, padx=(0, UI_PAD_SM), pady=UI_PAD_SM, sticky="ew"
        )
        self.key_entry.bind("<Button-1>", self._start_capture)

        self.capture_button = ttk.Button(
            self,
            text=txt("Capture", "입력 받기"),
            command=self._start_capture,
            width=10,
        )
        self.capture_button.grid(
            row=0, column=3, padx=(0, UI_PAD_SM), pady=UI_PAD_SM, sticky="w"
        )

        self.clear_button = ttk.Button(
            self,
            text=txt("Clear", "지우기"),
            command=self._clear_trigger,
            width=8,
        )
        self.clear_button.grid(
            row=0, column=4, padx=(0, UI_PAD_MD), pady=UI_PAD_SM, sticky="w"
        )

        self.lbl_capture = ttk.Label(
            self,
            textvariable=self.capture_status_var,
            foreground=theme.STATUS_READY_FG,
        )
        self.lbl_capture.grid(
            row=1,
            column=0,
            columnspan=5,
            padx=UI_PAD_MD,
            pady=(0, UI_PAD_XS),
            sticky="w",
        )

        self.lbl_help = ttk.Label(
            self,
            text=txt(
                "Checked events start disabled and can be toggled while the target app is active. Click Capture, then press a key or scroll the mouse wheel.",
                "체크된 이벤트는 시작 시 비활성이고, 대상 앱이 활성일 때 토글할 수 있습니다. 입력 받기를 누른 뒤 키를 누르거나 마우스 휠을 움직이세요.",
            ),
            foreground=theme.INK_MUTED,
        )
        self.lbl_help.grid(
            row=2,
            column=0,
            columnspan=5,
            padx=UI_PAD_MD,
            pady=(0, UI_PAD_SM),
            sticky="w",
        )
        self._sync_state()

    def get_data(self) -> tuple[bool, Optional[str]]:
        return self.enabled_var.get(), (self._selected_trigger or None)

    def apply_to_profile(self, profile: ProfileModel) -> None:
        enabled, key = self.get_data()
        profile.runtime_toggle_enabled = enabled
        profile.runtime_toggle_key = key

    def _notify_changed(self) -> None:
        self._sync_state()
        if self.on_change:
            self.on_change()

    def _sync_state(self) -> None:
        enabled = self.enabled_var.get()
        self.key_entry.config(state="readonly" if enabled else "disabled")
        self.capture_button.config(state="normal" if enabled else "disabled")
        self.clear_button.config(state="normal" if enabled else "disabled")
        if not enabled:
            self._stop_capture()
            self.capture_status_var.set("")

    def _bind_capture(
        self,
        widget: tk.Misc,
        sequence: str,
        handler: Callable[[tk.Event[tk.Misc]], object],
    ) -> None:
        func_id = widget.bind(sequence, handler, add="+")
        self._capture_bindings.append((widget, sequence, func_id))

    def _start_capture(
        self, _event: tk.Event[tk.Misc] | None = None
    ) -> Literal["break"]:
        if not self.enabled_var.get():
            return "break"
        if self._capture_active:
            return "break"

        self._capture_active = True
        self.capture_status_var.set(
            txt(
                "Waiting for input... Press a key or scroll the mouse wheel. Press Esc to cancel.",
                "입력을 기다리는 중... 키를 누르거나 마우스 휠을 움직이세요. Esc 로 취소합니다.",
            )
        )
        top = cast(tk.Misc, self.winfo_toplevel())
        self._bind_capture(top, "<KeyPress>", self._on_capture_key_press)
        self._bind_capture(top, "<MouseWheel>", self._on_capture_mouse_wheel)
        self._bind_capture(top, "<Button-4>", self._on_capture_mouse_wheel)
        self._bind_capture(top, "<Button-5>", self._on_capture_mouse_wheel)
        top.focus_force()
        return "break"

    def _stop_capture(self) -> None:
        for widget, sequence, func_id in self._capture_bindings:
            try:
                widget.unbind(sequence, func_id)
            except Exception as exc:
                logger.debug(f"Capture binding cleanup failed: {exc}")
        self._capture_bindings.clear()
        self._capture_active = False

    def _set_trigger(self, trigger: str | None) -> None:
        self._selected_trigger = normalize_runtime_toggle_trigger(trigger)
        self.key_var.set(display_runtime_toggle_trigger(self._selected_trigger) or "")
        self._notify_changed()

    def _clear_trigger(self) -> None:
        self._stop_capture()
        self.capture_status_var.set("")
        self._set_trigger(None)

    def _on_capture_key_press(
        self, event: tk.Event[tk.Misc]
    ) -> Literal["break"]:
        event_obj = cast(Any, event)
        if getattr(event_obj, "keysym", "") == "Escape":
            self._stop_capture()
            self.capture_status_var.set(
                txt("Input capture cancelled.", "입력 받기를 취소했습니다.")
            )
            return "break"

        trigger = normalize_runtime_toggle_capture_key(
            getattr(event_obj, "keysym", None),
            getattr(event_obj, "char", None),
            getattr(event_obj, "keycode", None),
        )
        if not trigger:
            return "break"

        self._stop_capture()
        self.capture_status_var.set(
            txt(
                "Captured: {trigger}",
                "입력됨: {trigger}",
                trigger=display_runtime_toggle_trigger(trigger),
            )
        )
        self._set_trigger(trigger)
        return "break"

    def _on_capture_mouse_wheel(
        self, event: tk.Event[tk.Misc]
    ) -> Literal["break"]:
        event_obj = cast(Any, event)
        trigger = normalize_runtime_toggle_wheel_event(
            delta=getattr(event_obj, "delta", None), num=getattr(event_obj, "num", None)
        )
        if not trigger:
            return "break"

        self._stop_capture()
        self.capture_status_var.set(
            txt(
                "Captured: {trigger}",
                "입력됨: {trigger}",
                trigger=display_runtime_toggle_trigger(trigger),
            )
        )
        self._set_trigger(trigger)
        return "break"
