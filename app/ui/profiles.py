import copy
import os
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, simpledialog
from typing import Callable, Optional, List

from PIL import Image, ImageTk

from app.utils.i18n import txt, dual_text_width
from app.ui.event_graph import ensure_profile_graph_image
from app.ui.event_editor import KeystrokeEventEditor
from app.ui.event_importer import EventImporter
from app.core.models import ProfileModel, EventModel
from app.core.validation import (
    find_duplicate_event_names,
    normalized_event_name,
    runtime_toggle_validation_errors,
)
from app.storage.profile_storage import load_profile, rename_profile_files, save_profile
from app.utils.system import WindowUtils, StateUtils, KeyUtils
from app.utils.runtime_toggle import (
    display_runtime_toggle_trigger,
    normalize_runtime_toggle_trigger,
    normalize_runtime_toggle_capture_key,
    normalize_runtime_toggle_wheel_event,
    runtime_toggle_member_count,
)

UI_PAD_XS = 2
UI_PAD_SM = 4
UI_PAD_MD = 8

BADGE_BG_INFO = "#eef3ff"
BADGE_FG_INFO = "#1e3a8a"
BADGE_BG_OK = "#e6f4ea"
BADGE_FG_OK = "#1e5f3a"
BADGE_BG_WARN = "#fff4cc"
BADGE_FG_WARN = "#7a5b00"
BADGE_BG_ERR = "#fdecea"
BADGE_FG_ERR = "#9f1f1f"


def _autosave_perf_enabled() -> bool:
    return os.getenv("KEYSIM_PROFILE_PERF") == "1"


def _image_identity(img: Image.Image | None):
    if img is None:
        return None
    return (id(img), img.size, img.mode)


def _event_fingerprint(evt: EventModel):
    return (
        getattr(evt, "event_name", None),
        bool(getattr(evt, "use_event", True)),
        getattr(evt, "capture_size", None),
        getattr(evt, "latest_position", None),
        getattr(evt, "clicked_position", None),
        getattr(evt, "ref_pixel_value", None),
        getattr(evt, "key_to_enter", None),
        getattr(evt, "press_duration_ms", None),
        getattr(evt, "randomization_ms", None),
        bool(getattr(evt, "independent_thread", False)),
        getattr(evt, "match_mode", "pixel"),
        bool(getattr(evt, "invert_match", False)),
        getattr(evt, "region_size", None),
        bool(getattr(evt, "execute_action", True)),
        getattr(evt, "group_id", None),
        int(getattr(evt, "priority", 0) or 0),
        tuple(sorted(dict(getattr(evt, "conditions", {}) or {}).items())),
        bool(getattr(evt, "runtime_toggle_member", False)),
        _image_identity(getattr(evt, "held_screenshot", None)),
    )


def _profile_fingerprint(profile: ProfileModel, profile_name: str, favorite: bool):
    return (
        profile_name,
        bool(favorite),
        bool(getattr(profile, "runtime_toggle_enabled", False)),
        getattr(profile, "runtime_toggle_key", None),
        tuple(_event_fingerprint(evt) for evt in (profile.event_list or [])),
    )


def _normalized_event_name(name: str | None) -> str:
    return normalized_event_name(name)


def _profile_runtime_toggle_validation_errors(
    profile: ProfileModel,
    events: list[EventModel],
    settings=None,
) -> list[str]:
    return runtime_toggle_validation_errors(profile, events, settings=settings)


def _find_duplicate_event_names(events: List[EventModel]) -> List[str]:
    return find_duplicate_event_names(events)


class ToolTip:
    """경량 툴팁: 위젯에 마우스를 올리면 설명 텍스트를 표시한다."""

    def __init__(self, widget, text: str = "", delay: int = 400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._tw = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _on_leave(self, event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        self._tw = tk.Toplevel(self.widget)
        self._tw.wm_overrideredirect(True)
        self._tw.wm_attributes("-topmost", True)
        self._tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._tw,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            foreground="#333333",
            relief="solid",
            borderwidth=1,
            font=("TkDefaultFont", 9),
            padx=6,
            pady=4,
        ).pack()

    def _hide(self):
        if self._tw:
            self._tw.destroy()
            self._tw = None

    def update_text(self, text: str):
        self.text = text


class ProfileFrame(ttk.Frame):
    def __init__(
        self,
        master,
        name: str,
        fav: bool,
        on_change: Optional[Callable[[], None]] = None,
        profiles_dir: Optional[Path] = None,
    ):
        super().__init__(master)
        self.on_change = on_change
        self._original_name = name
        self._profiles_dir = profiles_dir or Path("profiles")
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
        self.lbl_warn = ttk.Label(self, text="", foreground="#b30000")
        self.lbl_warn.pack(side=tk.LEFT, padx=(UI_PAD_SM, 0))

        self.entry.bind("<KeyRelease>", lambda e: self._notify_changed())
        self.entry.bind("<FocusOut>", lambda e: self._notify_changed())
        self.fav_var.trace_add("write", lambda *_: self._notify_changed())

    def get_data(self):
        return self.entry.get(), self.fav_var.get()

    def _validate(self):
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

    def _notify_changed(self):
        self._validate()
        if self.on_change:
            self.on_change()


class RuntimeToggleSettingsFrame(ttk.LabelFrame):
    def __init__(
        self,
        master,
        profile: ProfileModel,
        on_change: Optional[Callable[[], None]] = None,
    ):
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
            foreground="#1e5f3a",
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
            foreground="gray",
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

    def _notify_changed(self):
        self._sync_state()
        if self.on_change:
            self.on_change()

    def _sync_state(self):
        enabled = self.enabled_var.get()
        self.key_entry.config(state="readonly" if enabled else "disabled")
        self.capture_button.config(state="normal" if enabled else "disabled")
        self.clear_button.config(state="normal" if enabled else "disabled")
        if not enabled:
            self._stop_capture()
            self.capture_status_var.set("")

    def _bind_capture(self, widget, sequence: str, handler) -> None:
        func_id = widget.bind(sequence, handler, add="+")
        self._capture_bindings.append((widget, sequence, func_id))

    def _start_capture(self, _event=None):
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
        top = self.winfo_toplevel()
        self._bind_capture(top, "<KeyPress>", self._on_capture_key_press)
        self._bind_capture(top, "<MouseWheel>", self._on_capture_mouse_wheel)
        self._bind_capture(top, "<Button-4>", self._on_capture_mouse_wheel)
        self._bind_capture(top, "<Button-5>", self._on_capture_mouse_wheel)
        top.focus_force()
        return "break"

    def _stop_capture(self):
        for widget, sequence, func_id in self._capture_bindings:
            try:
                widget.unbind(sequence, func_id)
            except Exception:
                pass
        self._capture_bindings.clear()
        self._capture_active = False

    def _set_trigger(self, trigger: str | None) -> None:
        self._selected_trigger = normalize_runtime_toggle_trigger(trigger)
        self.key_var.set(display_runtime_toggle_trigger(self._selected_trigger) or "")
        self._notify_changed()

    def _clear_trigger(self):
        self._stop_capture()
        self.capture_status_var.set("")
        self._set_trigger(None)

    def _on_capture_key_press(self, event):
        if getattr(event, "keysym", "") == "Escape":
            self._stop_capture()
            self.capture_status_var.set(
                txt("Input capture cancelled.", "입력 받기를 취소했습니다.")
            )
            return "break"

        trigger = normalize_runtime_toggle_capture_key(
            getattr(event, "keysym", None),
            getattr(event, "char", None),
            getattr(event, "keycode", None),
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

    def _on_capture_mouse_wheel(self, event):
        trigger = normalize_runtime_toggle_wheel_event(
            delta=getattr(event, "delta", None), num=getattr(event, "num", None)
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


class GroupSelector(tk.Toplevel):
    """그룹 선택/생성 팝업"""

    def __init__(
        self, master, current_group: str, existing_groups: List[str], callback: Callable
    ):
        super().__init__(master)
        self.callback = callback
        self.result = None
        self.none_label = txt("(None)", "(없음)")
        self.existing_groups = {g.lower(): g for g in existing_groups}

        self.title(txt("Select Group", "그룹 선택"))
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        # 현재 그룹 표시
        ttk.Label(
            self,
            text=f"{txt('Current:', '현재:')} {current_group or self.none_label}",
        ).pack(pady=5)

        # 그룹 목록
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.listbox = tk.Listbox(frame, height=8, width=25)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        # 목록 채우기: (None) + 기존 그룹들
        self.listbox.insert(tk.END, self.none_label)
        for grp in sorted(existing_groups):
            self.listbox.insert(tk.END, grp)

        # 현재 그룹 선택
        if current_group and current_group in existing_groups:
            idx = sorted(existing_groups).index(current_group) + 1
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
        else:
            self.listbox.selection_set(0)

        self.listbox.bind("<Double-Button-1>", lambda e: self._on_select())

        # 버튼 프레임
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text=txt("Select", "선택"), command=self._on_select).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            btn_frame, text=txt("New Group", "새 그룹"), command=self._on_new
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=txt("Cancel", "취소"), command=self.destroy).pack(
            side=tk.RIGHT, padx=2
        )

        # 위치 조정
        self.update_idletasks()
        x = master.winfo_rootx() + 50
        y = master.winfo_rooty() + 50
        self.geometry(f"+{x}+{y}")

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._on_select())

    def _on_select(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        value = self.listbox.get(sel[0])
        self.result = None if value == self.none_label else value
        self.callback(self.result)
        self.destroy()

    def _on_new(self):
        new_name = simpledialog.askstring(
            txt("New Group", "새 그룹"),
            txt("Enter new group name:", "새 그룹 이름을 입력하세요:"),
            parent=self,
        )
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return messagebox.showwarning(
                txt("Invalid Group", "유효하지 않은 그룹"),
                txt("Group name cannot be empty.", "그룹 이름은 비워둘 수 없습니다."),
                parent=self,
            )
        if new_name in {"(None)", self.none_label}:
            return messagebox.showwarning(
                txt("Invalid Group", "유효하지 않은 그룹"),
                txt(
                    f"'{self.none_label}' is reserved.",
                    f"'{self.none_label}'은 예약어입니다.",
                ),
                parent=self,
            )
        if new_name.lower() in self.existing_groups:
            return messagebox.showwarning(
                txt("Duplicate Group", "중복 그룹"),
                txt(f"'{new_name}' already exists.", f"'{new_name}' 이미 존재합니다."),
                parent=self,
            )
        self.result = new_name
        self.callback(self.result)
        self.destroy()


class GroupManagerDialog(tk.Toplevel):
    def __init__(
        self,
        master,
        get_group_counts: Callable[[], dict[str, int]],
        rename_cb: Callable[[str, str], tuple[bool, str]],
        clear_cb: Callable[[str], int],
    ):
        super().__init__(master)
        self.get_group_counts = get_group_counts
        self.rename_cb = rename_cb
        self.clear_cb = clear_cb
        self._name_map: list[str] = []

        self.title(txt("Manage Groups", "그룹 관리"))
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        ttk.Label(
            self,
            text=txt(
                "Select a group to rename or clear from events.",
                "이벤트에서 이름 변경 또는 해제할 그룹을 선택하세요.",
            ),
        ).pack(anchor="w", padx=10, pady=(10, 5))

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.listbox = tk.Listbox(body, height=10, width=36)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=10, pady=(4, 10))
        ttk.Button(
            btns, text=txt("Rename", "이름 변경"), command=self._rename_group
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            btns, text=txt("Clear Group", "그룹 해제"), command=self._clear_group
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text=txt("Close", "닫기"), command=self.destroy).pack(
            side=tk.RIGHT, padx=2
        )

        self.listbox.bind("<Double-Button-1>", lambda e: self._rename_group())
        self.bind("<Escape>", lambda e: self.destroy())
        self._reload_groups()

        self.update_idletasks()
        x = master.winfo_rootx() + 60
        y = master.winfo_rooty() + 60
        self.geometry(f"+{x}+{y}")

    def _reload_groups(self, selected_name: Optional[str] = None):
        data = self.get_group_counts()
        self.listbox.delete(0, tk.END)
        self._name_map = sorted(data.keys())
        for name in self._name_map:
            self.listbox.insert(
                tk.END,
                txt(f"{name} ({data[name]} events)", f"{name} ({data[name]}개 이벤트)"),
            )

        if not self._name_map:
            self.listbox.insert(tk.END, txt("(No groups)", "(그룹 없음)"))
            self.listbox.config(state=tk.DISABLED)
            return

        self.listbox.config(state=tk.NORMAL)
        sel_idx = 0
        if selected_name and selected_name in self._name_map:
            sel_idx = self._name_map.index(selected_name)
        self.listbox.selection_set(sel_idx)
        self.listbox.see(sel_idx)

    def _selected_group(self) -> Optional[str]:
        if not self._name_map:
            return None
        sel = self.listbox.curselection()
        if not sel:
            return None
        idx = sel[0]
        if 0 <= idx < len(self._name_map):
            return self._name_map[idx]
        return None

    def _rename_group(self):
        group = self._selected_group()
        if not group:
            return
        new_name = simpledialog.askstring(
            txt("Rename Group", "그룹 이름 변경"),
            txt("Enter new group name:", "새 그룹 이름을 입력하세요:"),
            initialvalue=group,
            parent=self,
        )
        if new_name is None:
            return
        ok, msg = self.rename_cb(group, new_name)
        if not ok:
            return messagebox.showwarning(
                txt("Rename Failed", "이름 변경 실패"), msg, parent=self
            )
        self._reload_groups(selected_name=new_name.strip())

    def _clear_group(self):
        group = self._selected_group()
        if not group:
            return
        if not messagebox.askyesno(
            txt("Clear Group", "그룹 해제"),
            txt(
                f"Clear group '{group}' from all events?",
                f"모든 이벤트에서 그룹 '{group}'을(를) 해제할까요?",
            ),
            parent=self,
        ):
            return
        changed = self.clear_cb(group)
        self._reload_groups()
        messagebox.showinfo(
            txt("Group Cleared", "그룹 해제 완료"),
            txt(
                f"'{group}' removed from {changed} event(s).",
                f"'{group}'이(가) {changed}개 이벤트에서 제거되었습니다.",
            ),
            parent=self,
        )


class EventRow(ttk.Frame):
    def __init__(self, master, row_num: int, event: Optional[EventModel], cbs: dict):
        super().__init__(master)
        self.row_num, self.event, self.cbs = row_num, event, cbs
        self.use_var = tk.BooleanVar(value=event.use_event if event else True)
        self.runtime_toggle_var = tk.BooleanVar(
            value=bool(getattr(event, "runtime_toggle_member", False))
            if event
            else False
        )
        self._last_saved_name = event.event_name if event else ""
        self._bound_event_id = id(event) if event else None

        # 1. Index
        ttk.Label(self, text=str(row_num + 1), width=2, anchor="center").pack(
            side=tk.LEFT
        )

        # 2. Checkbox
        ttk.Checkbutton(self, variable=self.use_var, command=self._on_toggle_use).pack(
            side=tk.LEFT
        )

        # 3. Runtime Toggle Membership
        self.chk_runtime_toggle = ttk.Checkbutton(
            self,
            variable=self.runtime_toggle_var,
            command=self._on_toggle_runtime_member,
        )
        self.chk_runtime_toggle.pack(side=tk.LEFT, padx=(0, UI_PAD_XS))
        self._tip_runtime_toggle = ToolTip(self.chk_runtime_toggle)

        # 4. Condition Indicator
        self.lbl_cond = ttk.Label(self, text="", width=9, anchor="center")
        self.lbl_cond.pack(side=tk.LEFT)
        self._tip_cond = ToolTip(self.lbl_cond)

        # 5. Group ID Label (클릭 가능)
        self.lbl_grp = ttk.Label(
            self, text="", width=14, anchor="center", relief="sunken", cursor="hand2"
        )
        self.lbl_grp.pack(side=tk.LEFT, padx=2)
        self.lbl_grp.bind("<Button-1>", self._on_group_click)
        self._tip_grp = ToolTip(self.lbl_grp)

        # 6. Key Display Label
        self.lbl_key = ttk.Label(
            self, text="", width=12, anchor="center", relief="groove"
        )
        self.lbl_key.pack(side=tk.LEFT, padx=2)
        self.lbl_key.bind(
            "<Button-1>", lambda e: self._on_click("open")
        )  # 클릭 바인딩 추가
        self._tip_key = ToolTip(self.lbl_key)

        # 7. Event Name Entry
        self.entry = ttk.Entry(self)
        self.entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        if event:
            self.entry.insert(0, event.event_name or "")

        # 8. Action Buttons
        self.btn_delete = None
        for en, ko, key, min_width in [
            ("Edit", "편집", "open", 7),
            ("Copy", "복사", "copy", 7),
            ("🗑 Delete", "🗑 삭제", "remove", 9),
        ]:
            btn = ttk.Button(
                self,
                text=txt(en, ko),
                width=dual_text_width(en, ko, padding=2, min_width=min_width),
                command=lambda k=key: self._on_click(k),
            )
            btn.pack(side=tk.LEFT, padx=UI_PAD_XS)
            btn.bind("<Button-3>", lambda e: self.cbs["menu"](e, self.row_num))
            if key == "remove":
                self.btn_delete = btn

        # Context Menu Binding
        self.entry.bind("<Button-3>", lambda e: self.cbs["menu"](e, self.row_num))
        self.entry.bind("<KeyRelease>", self._on_name_changed)
        self.entry.bind("<FocusOut>", self._on_name_changed)

        # Initial Display
        self.update_display()

    def update_display(self):
        """이벤트 상태에 따라 UI 갱신"""
        if not self.event:
            runtime_toggle_var = getattr(self, "runtime_toggle_var", None)
            if runtime_toggle_var is not None:
                runtime_toggle_var.set(False)
            self.lbl_cond.config(text="")
            self.lbl_grp.config(text="")
            self.lbl_key.config(text="")
            return

        self.use_var.set(self.event.use_event)
        runtime_toggle_var = getattr(self, "runtime_toggle_var", None)
        runtime_toggle_tip = getattr(self, "_tip_runtime_toggle", None)
        if runtime_toggle_var is not None:
            runtime_toggle_var.set(
                bool(getattr(self.event, "runtime_toggle_member", False))
            )
            if runtime_toggle_tip is not None:
                runtime_toggle_tip.update_text(
                    txt(
                        "This event joins the runtime extra group.",
                        "이 이벤트를 실행 중 추가 이벤트 묶음에 포함합니다.",
                    )
                    if runtime_toggle_var.get()
                    else txt(
                        "Leave unchecked to keep this event always active.",
                        "체크하지 않으면 이 이벤트는 항상 기본 묶음으로 유지됩니다.",
                    )
                )

        # Name
        event_name = self.event.event_name or ""
        event_rebound = getattr(self, "_bound_event_id", None) != id(self.event)
        if self.entry.get() != event_name:
            self.entry.delete(0, tk.END)
            self.entry.insert(0, event_name)
        if event_rebound:
            self._last_saved_name = event_name
        self._bound_event_id = id(self.event)

        # Condition Only
        is_cond = not getattr(self.event, "execute_action", True)
        self.lbl_cond.config(text=txt("🔎 Cond", "🔎 조건") if is_cond else "")
        self.entry.config(foreground="gray" if is_cond else "black")
        self._tip_cond.update_text(
            txt(
                "Condition-only mode checks conditions without pressing keys.",
                "조건만 확인하고 키 입력은 하지 않습니다.",
            )
            if is_cond
            else txt(
                "When conditions match, the key input is executed.",
                "조건이 맞으면 키를 눌러 실행됩니다.",
            )
        )

        # Group
        grp = self.event.group_id or ""
        self.lbl_grp.config(text=grp if grp else txt("No Group", "그룹 없음"))
        self._tip_grp.update_text(
            txt(
                f"Current group: {grp}. Click to change it.",
                f"현재 그룹: {grp}. 클릭하면 변경할 수 있습니다.",
            )
            if grp
            else txt(
                "No group assigned. Click to set a group.",
                "현재 그룹이 없습니다. 클릭해서 그룹을 지정하세요.",
            )
        )

        # Key
        key = self.event.key_to_enter or ""
        invert = getattr(self.event, "invert_match", False)
        if is_cond:
            display = txt("🔎 Condition", "🔎 조건용")
        else:
            display = key if key else txt("⌨️ None", "⌨️ 없음")
        if invert:
            display = f"🔁 {display}"
        self.lbl_key.config(text=display)
        if invert:
            self._tip_key.update_text(
                txt(
                    "Invert match is enabled. It runs when the target does not match.",
                    "반전 매칭이 켜져 있습니다. 기준과 불일치할 때 실행됩니다.",
                )
            )
        elif is_cond:
            self._tip_key.update_text(
                txt(
                    "Condition-only event. No input key is needed.",
                    "조건 전용 이벤트입니다. 입력 키가 필요하지 않습니다.",
                )
            )
        elif key:
            self._tip_key.update_text(
                txt(
                    f"Input key: {key}. Click to open the editor.",
                    f"입력 키: {key}. 클릭하면 편집기를 엽니다.",
                )
            )
        else:
            self._tip_key.update_text(
                txt(
                    "No input key. Click to open the editor.",
                    "입력 키가 없습니다. 클릭하면 편집기를 엽니다.",
                )
            )

    def _on_toggle_use(self):
        if self.event:
            self.event.use_event = self.use_var.get()
            if "save" in self.cbs:
                self.cbs["save"]()

    def _on_group_click(self, event=None):
        if self.event:
            if "group_select" in self.cbs:
                self.cbs["group_select"](self.row_num, self.event)

    def _on_toggle_runtime_member(self):
        if self.event:
            self.event.runtime_toggle_member = self.runtime_toggle_var.get()
            self.update_display()
            if "save" in self.cbs:
                self.cbs["save"]()

    def _on_click(self, key):
        if key == "open":
            self.cbs["open"](self.row_num, self.event)
        elif key == "copy":
            self.cbs["copy"](self.event)
        elif key == "remove":
            self.cbs["remove"](self, self.row_num)

    def _on_name_changed(self, event=None):
        if self.event:
            self.event.event_name = self.entry.get()
            if "save" in self.cbs:
                self.cbs["save"]()

    def get_name(self) -> str:
        return self.entry.get()


class EventListFrame(ttk.Frame):
    # 특수 키 정렬 순서 (클래스 상수)
    SPECIAL_KEYS_ORDER = {
        "SPACE": 0,
        "TAB": 1,
        "ENTER": 2,
        "RETURN": 2,
        "BACKSPACE": 3,
        "DELETE": 4,
        "INSERT": 5,
        "HOME": 6,
        "END": 7,
        "PAGEUP": 8,
        "PAGEDOWN": 9,
        "UP": 10,
        "DOWN": 11,
        "LEFT": 12,
        "RIGHT": 13,
        "ESC": 14,
        "ESCAPE": 14,
    }

    def __init__(
        self,
        win,
        profile: ProfileModel,
        save_cb: Callable,
        name_getter: Optional[Callable[[], str]] = None,
        status_cb: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(win)
        self.win, self.profile, self.save_cb = win, profile, save_cb
        self.rows: List[EventRow] = []
        self.ctx_row = None
        self.profile_name_getter = name_getter
        self.status_cb = status_cb
        self.graph_viewer = None
        self.empty_state_frame: Optional[ttk.LabelFrame] = None
        self.add_event_label = txt("➕ Add Event", "➕ 이벤트 추가")

        # --- Control Buttons ---
        f_ctrl = ttk.Frame(self)
        f_ctrl.grid(
            row=1,
            column=0,
            columnspan=2,
            padx=UI_PAD_MD,
            pady=(UI_PAD_SM, UI_PAD_MD),
            sticky="we",
        )

        f_primary = ttk.Frame(f_ctrl)
        f_primary.pack(side=tk.LEFT, fill=tk.X, expand=True)
        f_secondary = ttk.Frame(f_ctrl)
        f_secondary.pack(side=tk.RIGHT)

        self.btn_add_event = ttk.Button(
            f_primary,
            text=self.add_event_label,
            command=self._add_event,
            width=dual_text_width(
                "➕ Add Event", "➕ 이벤트 추가", padding=2, min_width=18
            ),
        )
        self.btn_add_event.pack(
            side=tk.LEFT, padx=(0, UI_PAD_SM), fill=tk.X, expand=True
        )
        ToolTip(
            self.btn_add_event,
            txt(
                "Add a new event and open its editor.",
                "새 이벤트를 추가하고 편집기를 엽니다.",
            ),
        )

        self.btn_graph = ttk.Button(
            f_primary,
            text=txt("🗺 View Graph", "🗺 그래프 보기"),
            command=self._open_graph,
            width=dual_text_width(
                "🗺 View Graph", "🗺 그래프 보기", padding=2, min_width=13
            ),
        )
        self.btn_graph.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        ToolTip(
            self.btn_graph,
            txt(
                "Open a graph view of the current event flow.",
                "현재 이벤트 흐름을 그래프로 확인합니다.",
            ),
        )

        self.btn_sort_name = ttk.Button(
            f_secondary,
            text=txt("↕ Sort (Name)", "↕ 정렬(이름순서)"),
            command=self._sort_events_by_name,
            width=dual_text_width(
                "↕ Sort (Name)", "↕ 정렬(이름순서)", padding=2, min_width=16
            ),
        )
        self.btn_sort_name.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        ToolTip(
            self.btn_sort_name,
            txt(
                "Sort events automatically by event type and then by name.",
                "이벤트 타입 우선, 그다음 이름순으로 자동 정렬합니다.",
            ),
        )

        self.btn_sort_key = ttk.Button(
            f_secondary,
            text=txt("↕ Sort (Key)", "↕ 정렬(키 순서)"),
            command=self._sort_events_by_key,
            width=dual_text_width(
                "↕ Sort (Key)", "↕ 정렬(키 순서)", padding=2, min_width=16
            ),
        )
        self.btn_sort_key.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        ToolTip(
            self.btn_sort_key,
            txt(
                "Sort events automatically by event type: conditions by name, actions by input key order.",
                "이벤트 타입 우선으로 자동 정렬합니다: 조건은 이름순, 실행은 입력 키 순서입니다.",
            ),
        )

        self.btn_more = ttk.Menubutton(
            f_secondary,
            text=txt("⋯ More", "⋯ 더보기"),
            width=dual_text_width("⋯ More", "⋯ 더보기", padding=2, min_width=12),
        )
        self.btn_more.pack(side=tk.LEFT)
        ToolTip(
            self.btn_more,
            txt(
                "Open additional actions such as import and group management.",
                "가져오기, 그룹 관리 같은 추가 작업을 엽니다.",
            ),
        )
        self.more_menu = tk.Menu(self.btn_more, tearoff=0)
        self.more_menu.add_command(
            label=txt("📥 Import", "📥 가져오기"),
            command=lambda: EventImporter(self.win, self._import),
        )
        self.more_menu.add_command(
            label=txt("🧩 Manage Groups", "🧩 그룹 관리"),
            command=self._manage_groups,
        )
        self.btn_more.configure(menu=self.more_menu)

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(
            label=txt(
                "Apply Pixel/Region Info to Similar Areas",
                "유사 영역에 픽셀/영역 정보 적용",
            ),
            command=self._apply_pixel_batch,
        )

        self._create_header()
        self._load_events()

    def _get_existing_groups(self) -> List[str]:
        """프로필 내 모든 고유 그룹 ID 반환"""
        return list(set(e.group_id for e in self.profile.event_list if e.group_id))

    def _get_profile_name(self) -> str:
        if self.profile_name_getter:
            return self.profile_name_getter()
        if getattr(self.profile, "name", None):
            return self.profile.name
        return "profile"

    def _get_key_sort_order(self, key: str | None) -> tuple:
        """키 정렬 순서 반환: 숫자 → 알파벳 → 펑션키 → 특수문자 → None"""
        if not key:
            return (99, 0, "")

        # 조합키에서 베이스 키 추출 (예: "ctrl+a" -> "A")
        base_key = key.split("+")[-1].strip().upper()

        # 숫자 (0-9)
        if len(base_key) == 1 and base_key.isdigit():
            return (0, int(base_key), base_key)

        # 알파벳 (A-Z)
        if len(base_key) == 1 and base_key.isalpha():
            return (1, ord(base_key), base_key)

        # 펑션키 (F1-F12)
        if base_key.startswith("F") and len(base_key) <= 3:
            try:
                f_num = int(base_key[1:])
                if 1 <= f_num <= 12:
                    return (2, f_num, base_key)
            except ValueError:
                pass

        # 특수 키 매핑 (클래스 상수 사용)
        if base_key in self.SPECIAL_KEYS_ORDER:
            return (3, self.SPECIAL_KEYS_ORDER[base_key], base_key)

        # 기타 특수문자
        return (4, ord(base_key[0]) if base_key else 999, base_key)

    @staticmethod
    def _get_event_type_sort_order(event: EventModel) -> int:
        """조건 전용 이벤트를 먼저, 키 입력 실행 이벤트를 나중에 배치한다."""
        return 0 if not getattr(event, "execute_action", True) else 1

    def _sort_events_with_feedback(
        self, sort_key, title_text: str, message_text: str
    ) -> None:
        if not self.profile.event_list:
            return
        self.save_names()
        self.profile.event_list.sort(key=sort_key)
        self.update_events()
        self.save_cb()
        messagebox.showinfo(
            title_text,
            message_text,
            parent=self.win,
        )

    def _sort_events_by_name(self):
        """이벤트 타입 우선, 같은 타입 내에서는 이름순 정렬."""

        def sort_key(e: EventModel):
            name = e.event_name or ""
            return (self._get_event_type_sort_order(e), name.casefold(), name)

        self._sort_events_with_feedback(
            sort_key,
            txt("Name Sort Complete", "이름순 정렬 완료"),
            txt(
                "Events were sorted by:\nEvent Type (Condition → Action) → Name",
                "이벤트를 다음 순서로 정렬했습니다:\n이벤트 타입(조건 → 실행) → 이름",
            ),
        )

    def _sort_events_by_key(self):
        """이벤트 타입 우선, 조건은 이름순/실행은 입력 키 순서로 정렬."""

        def sort_key(e: EventModel):
            name = e.event_name or ""
            type_order = self._get_event_type_sort_order(e)
            if type_order == 0:
                return (type_order, 0, name.casefold(), name)
            return (
                type_order,
                1,
                *self._get_key_sort_order(getattr(e, "key_to_enter", None)),
                name.casefold(),
                name,
            )

        self._sort_events_with_feedback(
            sort_key,
            txt("Key Sort Complete", "키 순서 정렬 완료"),
            txt(
                "Events were sorted by:\nCondition → Name\nAction → Input Key",
                "이벤트를 다음 순서로 정렬했습니다:\n조건 → 이름\n실행 → 입력 키",
            ),
        )

    def _sort_events(self):
        """기존 호출 호환용: 키 순서 정렬로 연결."""
        self._sort_events_by_key()

    def _manage_groups(self):
        """그룹 관리 다이얼로그"""
        if not self._get_existing_groups():
            messagebox.showinfo(
                txt("Groups", "그룹"),
                txt(
                    "No groups yet.\nClick the 'No Group' cell in an event row to assign one.",
                    "아직 그룹이 없습니다.\n이벤트 행의 '그룹 없음' 칸을 클릭해 그룹을 지정하세요.",
                ),
                parent=self.win,
            )
            return
        GroupManagerDialog(
            master=self.win,
            get_group_counts=self._get_group_counts,
            rename_cb=self._rename_group,
            clear_cb=self._clear_group,
        )

    def _get_group_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.profile.event_list:
            if e.group_id:
                counts[e.group_id] = counts.get(e.group_id, 0) + 1
        return counts

    def _rename_group(self, old_name: str, new_name: str) -> tuple[bool, str]:
        target = new_name.strip()
        none_labels = {"(None)", txt("(None)", "(없음)")}
        if not target:
            return False, txt(
                "Group name cannot be empty.", "그룹 이름은 비워둘 수 없습니다."
            )
        if target in none_labels:
            return False, txt(f"'{target}' is reserved.", f"'{target}'은 예약어입니다.")
        if target.lower() != old_name.lower() and target.lower() in {
            g.lower() for g in self._get_existing_groups()
        }:
            return False, txt(
                f"'{target}' already exists.", f"'{target}' 이미 존재합니다."
            )

        changed = 0
        for e in self.profile.event_list:
            if e.group_id == old_name:
                e.group_id = target
                changed += 1
        if changed:
            self.update_events()
            self.save_cb(check_name=False)
        return True, ""

    def _clear_group(self, group_name: str) -> int:
        changed = 0
        for e in self.profile.event_list:
            if e.group_id == group_name:
                e.group_id = None
                changed += 1
        if changed:
            self.update_events()
            self.save_cb(check_name=False)
        return changed

    def _open_graph(self):
        self.save_names()
        name = self._get_profile_name()
        if self.graph_viewer and self.graph_viewer.is_open():
            self.graph_viewer.set_profile_name(name)
            self.graph_viewer.refresh(force=False)
            self.graph_viewer.lift()
            return
        self.graph_viewer = ProfileGraphViewer(
            parent=self.win,
            profile=self.profile,
            profile_name=name,
            name_getter=self._get_profile_name,
            on_close=lambda: setattr(self, "graph_viewer", None),
        )
        self.graph_viewer.refresh(force=False)

    def _on_group_select(self, row_num: int, event: EventModel):
        """그룹 선택 팝업 열기"""
        existing = self._get_existing_groups()

        def on_selected(new_group):
            event.group_id = new_group
            if 0 <= row_num < len(self.rows):
                self.rows[row_num].update_display()
            self.save_cb(check_name=False)

        GroupSelector(self.win, event.group_id, existing, on_selected)

    def _show_menu(self, event, row_num):
        self.ctx_row = row_num
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _apply_pixel_batch(self):
        if self.ctx_row is None:
            return
        src = self.profile.event_list[self.ctx_row]
        if not (src.latest_position and src.clicked_position):
            return messagebox.showwarning(
                txt("Warning", "경고"),
                txt("Invalid source event.", "유효하지 않은 원본 이벤트입니다."),
                parent=self.win,
            )

        if not messagebox.askyesno(
            txt("Confirm", "확인"),
            txt(
                f"Apply info to all events with area {src.latest_position}?",
                f"영역 {src.latest_position}를 가진 모든 이벤트에 정보를 적용할까요?",
            ),
            parent=self.win,
        ):
            return

        cnt = 0
        for i, evt in enumerate(self.profile.event_list):
            if (
                i != self.ctx_row
                and evt.latest_position == src.latest_position
                and evt.held_screenshot
            ):
                try:
                    evt.clicked_position = src.clicked_position
                    evt.ref_pixel_value = evt.held_screenshot.getpixel(
                        src.clicked_position
                    )
                    evt.match_mode = getattr(src, "match_mode", "pixel")
                    evt.region_size = getattr(src, "region_size", None)
                    cnt += 1
                except Exception:
                    print(f"Skipped {evt.event_name}")

        if cnt:
            self.save_cb()
            messagebox.showinfo(
                txt("Success", "완료"),
                txt(f"{cnt} events updated.", f"{cnt}개 이벤트를 업데이트했습니다."),
                parent=self.win,
            )
        else:
            messagebox.showinfo(
                txt("Info", "안내"),
                txt("No matching events found.", "일치하는 이벤트가 없습니다."),
                parent=self.win,
            )

    def _create_header(self):
        """컬럼 헤더 생성"""
        header = ttk.Frame(self)
        header.grid(
            row=2,
            column=0,
            columnspan=2,
            padx=UI_PAD_MD,
            pady=(UI_PAD_SM, 0),
            sticky="ew",
        )

        # 각 컬럼 레이블 (EventRow와 동일한 너비)
        _hdr = [
            ("#", 2, "center", {}, txt("Event index", "이벤트 순서")),
            (
                txt("Use", "사용"),
                3,
                "center",
                {},
                txt("Uncheck to skip this event.", "체크 해제 시 이벤트를 건너뜁니다"),
            ),
            (
                txt("Extra", "추가"),
                4,
                "center",
                {},
                txt(
                    "Checked events belong to the runtime extra group.",
                    "체크된 이벤트는 실행 중 추가 이벤트 묶음에 속합니다.",
                ),
            ),
            (
                txt("Type", "실행 유형"),
                10,
                "center",
                {},
                txt(
                    "Condition-only or key-input execution.",
                    "조건 전용 또는 키 입력 실행",
                ),
            ),
            (
                txt("Group", "그룹"),
                14,
                "center",
                {"padx": 2},
                txt("Event group (click to change).", "이벤트 그룹 (클릭하여 변경)"),
            ),
            (
                txt("Input Key", "입력 키"),
                10,
                "center",
                {"padx": 2},
                txt("Key to input (click to edit).", "입력할 키 (클릭하여 편집)"),
            ),
            (
                txt("Event Name", "이벤트 이름"),
                0,
                "w",
                {"padx": 5, "fill": tk.X, "expand": True},
                txt("Event name.", "이벤트 이름"),
            ),
            (
                txt("Actions", "동작"),
                22,
                "center",
                {},
                txt("Edit / Copy / Delete", "편집 / 복사 / 삭제"),
            ),
        ]
        for text, width, anchor, pack_kw, tip in _hdr:
            kw = {"text": text, "anchor": anchor}
            if width:
                kw["width"] = width
            lbl = ttk.Label(header, **kw)
            lbl.pack(side=tk.LEFT, **pack_kw)
            ToolTip(lbl, tip)

        # 구분선
        ttk.Separator(self, orient="horizontal").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(18, 0), padx=UI_PAD_MD
        )

    def _load_events(self):
        for i, evt in enumerate(self.profile.event_list):
            self._add_row(i, evt, resize=False)
        self._update_delete_buttons()
        self._sync_empty_state()

    def _sync_empty_state(self):
        has_events = bool(self.profile.event_list)
        if has_events:
            if self.empty_state_frame and self.empty_state_frame.winfo_exists():
                self.empty_state_frame.grid_remove()
            return

        if not self.empty_state_frame or not self.empty_state_frame.winfo_exists():
            self.empty_state_frame = ttk.LabelFrame(
                self, text=txt("Getting Started", "처음 시작 가이드")
            )
            self.empty_state_frame.grid(
                row=3,
                column=0,
                columnspan=2,
                padx=UI_PAD_MD,
                pady=(UI_PAD_MD, UI_PAD_SM),
                sticky="ew",
            )
            ttk.Label(
                self.empty_state_frame,
                text=txt(
                    "1) Add your first event with the ➕ Add Event button.",
                    "1) ➕ Add Event 버튼으로 첫 이벤트를 추가하세요.",
                ),
            ).pack(anchor="w", padx=10, pady=(8, 2))
            ttk.Label(
                self.empty_state_frame,
                text=txt(
                    "2) Configure capture and input key in the event editor.",
                    "2) 🖼 이벤트 편집기에서 캡처와 입력 키를 설정하세요.",
                ),
            ).pack(anchor="w", padx=10, pady=2)
            ttk.Label(
                self.empty_state_frame,
                text=txt(
                    "3) Done when the top save status changes to 'Saved HH:MM:SS'.",
                    "3) ✅ 상단 저장 상태가 'Saved HH:MM:SS'로 바뀌면 완료입니다.",
                ),
            ).pack(anchor="w", padx=10, pady=2)
            ttk.Button(
                self.empty_state_frame,
                text=txt("➕ Add First Event", "➕ 첫 이벤트 추가"),
                command=self._add_event,
            ).pack(anchor="e", padx=10, pady=(6, 8))
        else:
            self.empty_state_frame.grid()

    def _add_event(self):
        row_idx = len(self.profile.event_list)
        KeystrokeEventEditor(
            self.win,
            row_idx,
            self._on_editor_save,
            lambda: None,
            existing_events=self.profile.event_list,
        )

    def _add_row(self, row_num=None, event=None, resize=True):
        if self.empty_state_frame and self.empty_state_frame.winfo_exists():
            self.empty_state_frame.grid_remove()
        idx = len(self.rows) if row_num is None else row_num
        cbs = {
            "open": self._open_editor,
            "copy": self._copy_row,
            "remove": self._remove_row,
            "menu": self._show_menu,
            "group_select": self._on_group_select,  # NEW
            "save": lambda: self.save_cb(check_name=False),  # 추가
        }
        row = EventRow(self, idx, event, cbs)
        row.grid(
            row=idx + 3,
            column=0,
            columnspan=2,
            padx=UI_PAD_MD,
            pady=(UI_PAD_XS, 1),
            sticky="ew",
        )
        self.rows.append(row)

    def _open_editor(self, row, evt):
        KeystrokeEventEditor(
            self.win,
            row,
            self._on_editor_save,
            lambda: evt,
            existing_events=self.profile.event_list,
        )

    def _is_duplicate_event_name(
        self, name: str, ignore_index: int | None = None
    ) -> bool:
        target = _normalized_event_name(name)
        if not target:
            return False
        for idx, evt in enumerate(self.profile.event_list):
            if ignore_index is not None and idx == ignore_index:
                continue
            if _normalized_event_name(getattr(evt, "event_name", None)) == target:
                return True
        return False

    def _on_editor_save(self, evt, is_edit, row=0):
        ignore_index = row if is_edit else None
        if self._is_duplicate_event_name(evt.event_name, ignore_index=ignore_index):
            messagebox.showerror(
                txt("Duplicate Event Name", "중복 이벤트 이름"),
                txt(
                    "Event name '{name}' already exists in this profile.",
                    "이 프로필에 '{name}' 이벤트 이름이 이미 존재합니다.",
                    name=evt.event_name,
                ),
                parent=self.win,
            )
            return
        if is_edit and 0 <= row < len(self.profile.event_list):
            previous_event = self.profile.event_list[row]
            evt.use_event = bool(getattr(previous_event, "use_event", True))
            evt.runtime_toggle_member = bool(
                getattr(previous_event, "runtime_toggle_member", False)
            )
            old_name = previous_event.event_name
            self.profile.event_list[row] = evt
            new_name = evt.event_name
            if old_name and new_name and old_name != new_name:
                self._update_condition_references(old_name, new_name)
        else:
            self.profile.event_list.append(evt)
        self.update_events()
        self.save_cb(check_name=False)

    def _copy_row(self, evt):
        if not evt:
            return messagebox.showinfo(
                txt("Info", "안내"),
                txt(
                    "Only configured events can be copied.",
                    "설정된 이벤트만 복사할 수 있습니다.",
                ),
            )
        try:
            # 수동으로 이벤트 복사
            new = EventModel(
                event_name=f"{txt('Copy of', '복사본')} {evt.event_name}",
                capture_size=getattr(evt, "capture_size", (100, 100)),
                latest_position=evt.latest_position,
                clicked_position=evt.clicked_position,
                latest_screenshot=None,  # not persisted; left preview is always live capture
                held_screenshot=(
                    evt.held_screenshot.copy() if evt.held_screenshot else None
                ),
                ref_pixel_value=evt.ref_pixel_value,
                key_to_enter=evt.key_to_enter,
                press_duration_ms=getattr(evt, "press_duration_ms", None),
                randomization_ms=getattr(evt, "randomization_ms", None),
                independent_thread=False,
                match_mode=getattr(evt, "match_mode", "pixel"),
                invert_match=getattr(evt, "invert_match", False),
                region_size=getattr(evt, "region_size", None),
                execute_action=getattr(evt, "execute_action", True),
                group_id=getattr(evt, "group_id", None),
                priority=getattr(evt, "priority", 0),
                conditions=copy.deepcopy(getattr(evt, "conditions", {})),
                runtime_toggle_member=bool(
                    getattr(evt, "runtime_toggle_member", False)
                ),
            )
            new.use_event = evt.use_event

            self.profile.event_list.append(new)
            self._add_row(event=new)
            self.save_cb()
            self._update_delete_buttons()
            if self.status_cb:
                self.status_cb(txt("Event copied", "이벤트 복사됨"))
        except Exception as e:
            messagebox.showerror(
                txt("Error", "오류"),
                txt(f"Copy failed: {e}", f"복사 실패: {e}"),
            )

    def _remove_row(self, row_widget, row_num):
        if len(self.profile.event_list) < 2:
            return
        row_widget.destroy()
        self.rows.remove(row_widget)
        removed_name = None
        if 0 <= row_num < len(self.profile.event_list):
            removed = self.profile.event_list.pop(row_num)
            removed_name = getattr(removed, "event_name", None)
        if removed_name and all(
            getattr(evt, "event_name", None) != removed_name
            for evt in self.profile.event_list
        ):
            self._remove_condition_references(removed_name)
        for i, row in enumerate(self.rows):
            row.row_num = i
        self._update_row_indices()
        self._update_delete_buttons()
        self._sync_empty_state()
        self.save_cb()
        self.win.update_idletasks()

    def _import(self, evts):
        self.profile.event_list.extend(evts)
        for e in evts:
            self._add_row(event=e)
        self._sync_empty_state()
        self.save_cb()

    def _update_row_indices(self):
        """모든 행의 인덱스 라벨 업데이트"""
        for i, row in enumerate(self.rows):
            row.grid(
                row=i + 3,
                column=0,
                columnspan=2,
                padx=UI_PAD_MD,
                pady=(UI_PAD_XS, 1),
                sticky="ew",
            )
            # Index 라벨 업데이트
            for child in row.winfo_children():
                if isinstance(child, ttk.Label):
                    try:
                        int(child.cget("text"))
                        child.config(text=str(i + 1))
                        break
                    except (ValueError, tk.TclError):
                        continue

    def _update_delete_buttons(self):
        can_delete = len(self.profile.event_list) > 1
        state = "normal" if can_delete else "disabled"
        for row in self.rows:
            if row.btn_delete:
                row.btn_delete.config(state=state)

    def update_events(self):
        curr, new = len(self.rows), len(self.profile.event_list)

        # Update existing rows
        for i in range(min(curr, new)):
            self.rows[i].event = self.profile.event_list[i]
            self.rows[i].row_num = i
            self.rows[i].update_display()

        # Remove excess rows
        for r in self.rows[new:]:
            r.destroy()
        self.rows = self.rows[:new]

        # Add new rows
        for i in range(curr, new):
            self._add_row(i, self.profile.event_list[i], resize=False)

        # Re-grid all rows and update indices
        self._update_row_indices()
        self._update_delete_buttons()
        self._sync_empty_state()
        self.win.update_idletasks()

    def save_names(self):
        for i, r in enumerate(self.rows):
            if i < len(self.profile.event_list):
                old_name = r._last_saved_name
                new_name = r.get_name()
                if old_name and new_name and old_name != new_name:
                    self._update_condition_references(old_name, new_name)
                self.profile.event_list[i].event_name = new_name
                r._last_saved_name = new_name

    def _update_condition_references(self, old_name: str, new_name: str):
        """이벤트 이름 변경 시 조건 참조 업데이트"""
        for evt in self.profile.event_list:
            if hasattr(evt, "conditions") and old_name in evt.conditions:
                evt.conditions[new_name] = evt.conditions.pop(old_name)

    def _remove_condition_references(self, removed_name: str):
        """삭제된 이벤트를 참조하는 조건을 제거"""
        for evt in self.profile.event_list:
            if hasattr(evt, "conditions") and removed_name in evt.conditions:
                evt.conditions.pop(removed_name, None)


class KeystrokeProfiles:
    def __init__(self, main_win, prof_name, save_cb=None):
        self.main_win, self.prof_name, self.ext_save_cb = main_win, prof_name, save_cb
        self.prof_dir = Path("profiles")
        self._dirty = False
        self._autosave_after_id = None
        self._last_saved_fingerprint = None
        self._overview_status_text = ""

        self.win = tk.Toplevel(main_win)
        self.win.title(f"{txt('Profile Manager', '프로필 관리자')} - {self.prof_name}")
        self.win.transient(main_win)
        self.win.grab_set()
        self.win.bind("<Escape>", self._close)
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        self.profile = self._load()
        self.p_frame = ProfileFrame(
            self.win,
            prof_name,
            self.profile.favorite,
            on_change=self._on_changed,
            profiles_dir=self.prof_dir,
        )
        self.p_frame.pack(fill="x", padx=UI_PAD_MD, pady=(UI_PAD_MD, UI_PAD_SM))
        self.runtime_toggle_frame = RuntimeToggleSettingsFrame(
            self.win,
            self.profile,
            on_change=self._on_changed,
        )
        self.runtime_toggle_frame.pack(fill="x", padx=UI_PAD_MD, pady=(0, UI_PAD_SM))

        f_status = ttk.Frame(self.win)
        f_status.pack(fill="x", padx=UI_PAD_MD, pady=(0, UI_PAD_SM))
        ttk.Label(f_status, text=txt("Save status:", "저장 상태:")).pack(side=tk.LEFT)
        self.lbl_save_badge = tk.Label(
            f_status,
            text="",
            relief="groove",
            borderwidth=1,
            padx=8,
            pady=2,
        )
        self.lbl_save_badge.pack(side=tk.LEFT, padx=UI_PAD_SM)
        self.lbl_status = ttk.Label(f_status, text="", foreground="gray")
        self.lbl_status.pack(side=tk.LEFT, padx=UI_PAD_MD)

        f_summary = ttk.Frame(f_status)
        f_summary.pack(side=tk.RIGHT)
        self.lbl_events_badge = self._make_chip(f_summary)
        self.lbl_events_badge.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        self.lbl_groups_badge = self._make_chip(f_summary)
        self.lbl_groups_badge.pack(side=tk.LEFT, padx=(0, UI_PAD_SM))
        self.lbl_attention_badge = self._make_chip(f_summary)
        self.lbl_attention_badge.pack(side=tk.LEFT)

        self.e_frame = EventListFrame(
            self.win,
            self.profile,
            self._on_changed,
            name_getter=lambda: self.prof_name,
            status_cb=self._show_temp_status,
        )
        self.e_frame.pack(fill="both", expand=True, padx=0, pady=(0, UI_PAD_SM))

        f_btn = ttk.Frame(self.win, style="success.TFrame")
        f_btn.pack(side="bottom", fill="x", padx=UI_PAD_MD, pady=(UI_PAD_SM, UI_PAD_MD))
        ttk.Button(f_btn, text=txt("Close", "닫기"), command=self._close).pack(
            side=tk.RIGHT, anchor="center"
        )

        self._load_pos()
        self._refresh_profile_overview()
        self._last_saved_fingerprint = _profile_fingerprint(
            self.profile, self.prof_name, self.profile.favorite
        )
        self._set_save_status("saved")

    @staticmethod
    def _make_chip(parent) -> tk.Label:
        return tk.Label(
            parent,
            text="",
            relief="groove",
            borderwidth=1,
            padx=8,
            pady=2,
        )

    def _load(self):
        try:
            return load_profile(self.prof_dir, self.prof_name, migrate=True)
        except Exception:
            return ProfileModel(name=self.prof_name, event_list=[], favorite=False)

    def _ensure_unique_event_names(self):
        duplicates = _find_duplicate_event_names(self.profile.event_list or [])
        if duplicates:
            dup_text = ", ".join(duplicates)
            raise ValueError(
                txt(
                    "Duplicate event names are not allowed: {names}",
                    "중복 이벤트 이름은 허용되지 않습니다: {names}",
                    names=dup_text,
                )
            )

    def _save(self, check_name=True, reload=True):
        started = time.perf_counter()
        if not self.profile.event_list:
            raise ValueError(
                txt(
                    "At least one event must be set",
                    "최소 1개 이상의 이벤트가 필요합니다",
                )
            )
        new_name, is_fav = self.p_frame.get_data()
        new_name = (new_name or "").strip()

        if check_name and not new_name:
            raise ValueError(txt("Enter profile name", "프로필 이름을 입력하세요"))
        if not new_name:
            # Auto-save 중 임시 공백 입력은 기존 파일명을 유지한다.
            new_name = self.prof_name
        self.profile.favorite = is_fav
        self.profile.name = new_name
        runtime_toggle_frame = getattr(self, "runtime_toggle_frame", None)
        if runtime_toggle_frame is not None:
            runtime_toggle_frame.apply_to_profile(self.profile)

        old_name = self.prof_name
        renamed = False
        if new_name != self.prof_name:
            if (self.prof_dir / f"{new_name}.json").exists():
                raise ValueError(
                    txt(
                        f"'{new_name}' already exists.",
                        f"'{new_name}' 이미 존재합니다.",
                    )
                )

            if (self.prof_dir / f"{self.prof_name}.json").exists():
                rename_profile_files(self.prof_dir, self.prof_name, new_name)
            self.prof_name = new_name
            renamed = True

        if reload:
            self.e_frame.update_events()
            self.e_frame.save_names()
        self._ensure_unique_event_names()
        validation_errors = _profile_runtime_toggle_validation_errors(
            self.profile,
            list(self.profile.event_list or []),
            settings=getattr(getattr(self, "main_win", None), "settings", None),
        )
        if validation_errors:
            raise ValueError(validation_errors[0])
        next_fingerprint = _profile_fingerprint(self.profile, new_name, is_fav)
        if renamed or next_fingerprint != self._last_saved_fingerprint:
            save_profile(self.prof_dir, self.profile, name=self.prof_name)
            self._last_saved_fingerprint = _profile_fingerprint(
                self.profile, self.prof_name, self.profile.favorite
            )
        if reload:
            self.e_frame.update_events()
        if renamed and self.ext_save_cb:
            self.ext_save_cb(self.prof_name)
        if _autosave_perf_enabled():
            print(
                f"[perf] profile_save[{self.prof_name}]: {(time.perf_counter() - started) * 1000.0:.3f}ms"
            )
        return old_name != self.prof_name

    def _show_temp_status(self, text: str, duration_ms: int = 2000):
        self.lbl_status.config(text=text, foreground="#006600")
        self.win.after(
            duration_ms, lambda: self.lbl_status.config(text="", foreground="gray")
        )

    def _refresh_profile_overview(self):
        events = list(self.profile.event_list or [])
        event_count = len(events)
        group_count = len({e.group_id for e in events if e.group_id})
        condition_only_count = sum(
            1 for e in events if not getattr(e, "execute_action", True)
        )
        missing_key_count = sum(
            1
            for e in events
            if getattr(e, "execute_action", True) and not (e.key_to_enter or "").strip()
        )
        toggle_member_count = runtime_toggle_member_count(events)
        validation_errors = _profile_runtime_toggle_validation_errors(
            self.profile,
            events,
            settings=getattr(getattr(self, "main_win", None), "settings", None),
        )
        warning_count = missing_key_count + len(validation_errors)

        self.lbl_events_badge.config(
            text=txt(f"⚙️ Events {event_count}", f"⚙️ 이벤트 {event_count}"),
            bg=BADGE_BG_INFO,
            fg=BADGE_FG_INFO,
        )
        self.lbl_groups_badge.config(
            text=txt(f"🧩 Groups {group_count}", f"🧩 그룹 {group_count}"),
            bg="#f2f7ec",
            fg="#2f6f3e",
        )
        if warning_count:
            warning_parts = []
            if missing_key_count:
                warning_parts.append(
                    txt(
                        "missing key: {count}",
                        "입력 키 없음: {count}",
                        count=missing_key_count,
                    )
                )
            warning_parts.extend(validation_errors)
            self._overview_status_text = txt(
                "Review: {details}",
                "확인 필요: {details}",
                details=", ".join(warning_parts),
            )
            self.lbl_attention_badge.config(
                text=txt(f"⚠ Attention {warning_count}", f"⚠ 주의 {warning_count}"),
                bg=BADGE_BG_WARN,
                fg=BADGE_FG_WARN,
            )
            return
        if condition_only_count:
            if toggle_member_count:
                self._overview_status_text = txt(
                    "Condition-only events: {cond_count}. Runtime extra events: {toggle_count}.",
                    "조건 전용 이벤트: {cond_count}개. 실행 중 추가 이벤트: {toggle_count}개.",
                    cond_count=condition_only_count,
                    toggle_count=toggle_member_count,
                )
            else:
                self._overview_status_text = txt(
                    "Condition-only events are configured: {count}.",
                    "조건 전용 이벤트가 {count}개 설정되어 있습니다.",
                    count=condition_only_count,
                )
        elif toggle_member_count:
            self._overview_status_text = txt(
                "Runtime extra events are configured: {count}.",
                "실행 중 추가 이벤트가 {count}개 설정되어 있습니다.",
                count=toggle_member_count,
            )
        else:
            self._overview_status_text = txt(
                "All events are ready for autosave and run checks.",
                "모든 이벤트가 자동저장 및 실행 점검 기준을 통과했습니다.",
            )
        self.lbl_attention_badge.config(
            text=txt("✅ Attention 0", "✅ 주의 0"),
            bg=BADGE_BG_OK,
            fg=BADGE_FG_OK,
        )

    def _set_save_status(self, status: str, detail: str = ""):
        self._refresh_profile_overview()
        if status == "saving":
            self.lbl_save_badge.config(
                text=txt("💾 Saving...", "💾 저장 중..."),
                bg=BADGE_BG_WARN,
                fg=BADGE_FG_WARN,
            )
            if not detail:
                self.lbl_status.config(text="", foreground="gray")
            return
        if status == "saved":
            saved_at = time.strftime("%H:%M:%S")
            self.lbl_save_badge.config(
                text=txt(f"✅ Saved {saved_at}", f"✅ 저장됨 {saved_at}"),
                bg=BADGE_BG_OK,
                fg=BADGE_FG_OK,
            )
            self.lbl_status.config(
                text=detail if detail else self._overview_status_text,
                foreground="gray",
            )
            return
        if status == "error":
            self.lbl_save_badge.config(
                text=txt("⚠ Save failed", "⚠ 저장 실패"),
                bg=BADGE_BG_ERR,
                fg=BADGE_FG_ERR,
            )
            self.lbl_status.config(
                text=detail if detail else "",
                foreground="#b30000",
            )

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        star = "* " if dirty else ""
        self.win.title(
            f"{star}{txt('Profile Manager', '프로필 관리자')} - {self.prof_name}"
        )

    def _run_autosave(self, check_name=False):
        self._autosave_after_id = None
        started = time.perf_counter()
        try:
            self.e_frame.save_names()
            self._save(check_name=check_name, reload=False)
            self._set_dirty(False)
            self._set_save_status("saved")
        except Exception as e:
            self._set_dirty(True)
            self._set_save_status("error", str(e))
        finally:
            if _autosave_perf_enabled():
                print(
                    f"[perf] autosave[{self.prof_name}]: {(time.perf_counter() - started) * 1000.0:.3f}ms"
                )

    def _schedule_autosave(self, delay_ms=250, check_name=False):
        if self._autosave_after_id:
            self.win.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        self._autosave_after_id = self.win.after(
            delay_ms, lambda: self._run_autosave(check_name=check_name)
        )

    def _on_changed(self, check_name=False, reload=False):
        self._set_dirty(True)
        self._set_save_status("saving")
        self._schedule_autosave(check_name=check_name)

    def _flush_autosave(self, check_name=True):
        if self._autosave_after_id:
            self.win.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        try:
            self.e_frame.save_names()
            self._save(check_name=check_name, reload=False)
            self._set_dirty(False)
            self._set_save_status("saved")
            return True
        except Exception as e:
            self._set_dirty(True)
            self._set_save_status("error", str(e))
            messagebox.showerror(txt("Error", "오류"), str(e), parent=self.win)
            return False

    def _close(self, event=None):
        if not self._flush_autosave(check_name=True):
            return
        StateUtils.save_main_app_state(
            prof_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}"
        )
        if self.ext_save_cb:
            self.ext_save_cb(self.prof_name)
        self.win.destroy()

    def _load_pos(self):
        pos = StateUtils.parse_slash_int_pair(
            StateUtils.load_main_app_state().get("prof_pos")
        )
        if pos is not None:
            self.win.geometry(f"+{pos[0]}+{pos[1]}")
        else:
            WindowUtils.center_window(self.win)


class ProfileGraphViewer:
    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        profile: ProfileModel,
        profile_name: str,
        name_getter: Optional[Callable[[], str]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ):
        self.parent = parent
        self.profile = profile
        self.profile_name = profile_name
        self.name_getter = name_getter
        self.on_close = on_close
        self.cache_dir = Path("profiles") / "_graphs"
        self._auto_sized = False

        self.win = tk.Toplevel(parent)
        self.win.title(txt("Profile Graph", "프로필 그래프"))
        self.win.transient(parent)
        self.win.geometry("900x600")
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        self.win.bind("<Escape>", lambda e: self._close())
        self.win.focus_force()
        try:
            self.parent.grab_release()
        except tk.TclError:
            pass
        try:
            self.win.grab_set()
        except tk.TclError:
            pass

        self.toolbar = ttk.Frame(self.win)
        self.toolbar.pack(fill="x", padx=6, pady=6)

        ttk.Button(
            self.toolbar,
            text=txt("Refresh", "새로고침"),
            command=lambda: self.refresh(True),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.toolbar, text=txt("Close", "닫기"), command=self._close).pack(
            side=tk.LEFT, padx=2
        )
        self.lbl_info = ttk.Label(self.toolbar, text="")
        self.lbl_info.pack(side=tk.RIGHT, padx=6)

        frame = ttk.Frame(self.win)
        frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(frame, bg="#f8f7f2")
        self.canvas.pack(side=tk.LEFT, fill="both", expand=True)

        self.scroll_y = ttk.Scrollbar(
            frame, orient="vertical", command=self.canvas.yview
        )
        self.scroll_y.pack(side=tk.RIGHT, fill="y")
        self.scroll_x = ttk.Scrollbar(
            self.win, orient="horizontal", command=self.canvas.xview
        )
        self.scroll_x.pack(side=tk.BOTTOM, fill="x")

        self.canvas.configure(yscrollcommand=self.scroll_y.set)
        self.canvas.configure(xscrollcommand=self.scroll_x.set)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.win.bind("<MouseWheel>", self._on_mousewheel)
        self.win.bind("<Button-4>", self._on_mousewheel)
        self.win.bind("<Button-5>", self._on_mousewheel)

        self.photo = None

    def is_open(self) -> bool:
        return self.win.winfo_exists()

    def lift(self):
        self.win.lift()
        self.win.focus_force()

    def refresh(self, force: bool = False):
        if self.name_getter:
            self.profile_name = self.name_getter()
        self.profile_name = self.profile_name or "profile"
        path = ensure_profile_graph_image(
            self.profile, self.profile_name, self.cache_dir, force=force
        )
        try:
            with Image.open(path) as img:
                img.load()
                view_img = img.copy()
        except Exception as e:
            messagebox.showerror(
                txt("Graph Error", "그래프 오류"), str(e), parent=self.win
            )
            return

        self.photo = ImageTk.PhotoImage(view_img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.config(scrollregion=(0, 0, view_img.width, view_img.height))
        self.lbl_info.config(text=f"{path.name}  {view_img.width}x{view_img.height}")
        self._apply_window_size(view_img.width, view_img.height, force=force)

    def set_profile_name(self, name: str):
        self.profile_name = name

    def _on_mousewheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
            return
        if event.num == 5:
            self.canvas.yview_scroll(1, "units")
            return
        if not event.delta:
            return
        if abs(event.delta) < 120:
            step = -1 if event.delta > 0 else 1
        else:
            step = int(-event.delta / 120)
        if step != 0:
            self.canvas.yview_scroll(step, "units")

    def _apply_window_size(self, img_w: int, img_h: int, force: bool = False):
        if self._auto_sized and not force:
            return
        self.win.update_idletasks()
        extra_w = self.win.winfo_width() - self.canvas.winfo_width()
        extra_h = self.win.winfo_height() - self.canvas.winfo_height()
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()

        target_w = min(img_w + extra_w, int(screen_w * 0.9))
        target_h = min(img_h + extra_h, int(screen_h * 0.9))
        target_w = max(480, target_w)
        target_h = max(320, target_h)

        self.win.geometry(f"{target_w}x{target_h}")
        WindowUtils.center_window(self.win)
        self._auto_sized = True

    def _close(self):
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        if self.parent and self.parent.winfo_exists():
            try:
                self.parent.grab_set()
            except tk.TclError:
                pass
        if self.on_close:
            self.on_close()
        self.win.destroy()
