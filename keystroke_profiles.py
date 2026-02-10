import copy
import pickle
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, simpledialog
from typing import Callable, Optional, List

from PIL import Image, ImageTk

from keystroke_event_graph import ensure_profile_graph_image
from keystroke_event_editor import KeystrokeEventEditor
from keystroke_event_importer import EventImporter
from keystroke_models import ProfileModel, EventModel
from keystroke_utils import WindowUtils, StateUtils


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
            self._tw, text=self.text, justify=tk.LEFT,
            background="#ffffe0", foreground="#333333",
            relief="solid", borderwidth=1,
            font=("TkDefaultFont", 9), padx=6, pady=4,
        ).pack()

    def _hide(self):
        if self._tw:
            self._tw.destroy()
            self._tw = None

    def update_text(self, text: str):
        self.text = text


class ProfileFrame(ttk.Frame):
    def __init__(
        self, master, name: str, fav: bool,
        on_change: Optional[Callable[[], None]] = None,
        profiles_dir: Optional[Path] = None,
    ):
        super().__init__(master)
        self.on_change = on_change
        self._original_name = name
        self._profiles_dir = profiles_dir or Path("profiles")
        self.fav_var = tk.BooleanVar(value=fav)

        ttk.Label(self, text="Profile Name: ").pack(side=tk.LEFT)
        self.entry = ttk.Entry(self)
        self.entry.pack(side=tk.LEFT, padx=1)
        self.entry.insert(0, name)
        ttk.Checkbutton(self, text="Favorite", variable=self.fav_var).pack(
            side=tk.LEFT, padx=5
        )
        self.lbl_warn = ttk.Label(self, text="", foreground="#b30000")
        self.lbl_warn.pack(side=tk.LEFT, padx=5)

        self.entry.bind("<KeyRelease>", lambda e: self._notify_changed())
        self.entry.bind("<FocusOut>", lambda e: self._notify_changed())
        self.fav_var.trace_add("write", lambda *_: self._notify_changed())

    def get_data(self):
        return self.entry.get(), self.fav_var.get()

    def _validate(self):
        name = self.entry.get().strip()
        if not name:
            self.lbl_warn.config(text="프로필 이름을 입력하세요")
            return
        if name != self._original_name and (self._profiles_dir / f"{name}.pkl").exists():
            self.lbl_warn.config(text=f"'{name}' 이미 존재합니다")
            return
        self.lbl_warn.config(text="")

    def _notify_changed(self):
        self._validate()
        if self.on_change:
            self.on_change()


class GroupSelector(tk.Toplevel):
    """그룹 선택/생성 팝업"""

    def __init__(
        self, master, current_group: str, existing_groups: List[str], callback: Callable
    ):
        super().__init__(master)
        self.callback = callback
        self.result = None
        self.existing_groups = {g.lower(): g for g in existing_groups}

        self.title("Select Group")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        # 현재 그룹 표시
        ttk.Label(self, text=f"Current: {current_group or '(None)'}").pack(pady=5)

        # 그룹 목록
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.listbox = tk.Listbox(frame, height=8, width=25)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        # 목록 채우기: (None) + 기존 그룹들
        self.listbox.insert(tk.END, "(None)")
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

        ttk.Button(btn_frame, text="Select", command=self._on_select).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="New Group", command=self._on_new).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(
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
        self.result = None if value == "(None)" else value
        self.callback(self.result)
        self.destroy()

    def _on_new(self):
        new_name = simpledialog.askstring(
            "New Group", "Enter new group name:", parent=self
        )
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return messagebox.showwarning(
                "Invalid Group", "Group name cannot be empty.", parent=self
            )
        if new_name == "(None)":
            return messagebox.showwarning(
                "Invalid Group", "'(None)' is reserved.", parent=self
            )
        if new_name.lower() in self.existing_groups:
            return messagebox.showwarning(
                "Duplicate Group", f"'{new_name}' already exists.", parent=self
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

        self.title("Manage Groups")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        ttk.Label(
            self, text="Select a group to rename or clear from events."
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
        ttk.Button(btns, text="Rename", command=self._rename_group).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btns, text="Clear Group", command=self._clear_group).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btns, text="Close", command=self.destroy).pack(side=tk.RIGHT, padx=2)

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
            self.listbox.insert(tk.END, f"{name} ({data[name]} events)")

        if not self._name_map:
            self.listbox.insert(tk.END, "(No groups)")
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
            "Rename Group",
            "Enter new group name:",
            initialvalue=group,
            parent=self,
        )
        if new_name is None:
            return
        ok, msg = self.rename_cb(group, new_name)
        if not ok:
            return messagebox.showwarning("Rename Failed", msg, parent=self)
        self._reload_groups(selected_name=new_name.strip())

    def _clear_group(self):
        group = self._selected_group()
        if not group:
            return
        if not messagebox.askyesno(
            "Clear Group",
            f"Clear group '{group}' from all events?",
            parent=self,
        ):
            return
        changed = self.clear_cb(group)
        self._reload_groups()
        messagebox.showinfo(
            "Group Cleared",
            f"'{group}' removed from {changed} event(s).",
            parent=self,
        )


class EventRow(ttk.Frame):
    def __init__(self, master, row_num: int, event: Optional[EventModel], cbs: dict):
        super().__init__(master)
        self.row_num, self.event, self.cbs = row_num, event, cbs
        self.use_var = tk.BooleanVar(value=event.use_event if event else True)

        # 1. Index
        ttk.Label(self, text=str(row_num + 1), width=2, anchor="center").pack(
            side=tk.LEFT
        )

        # 2. Checkbox
        ttk.Checkbutton(self, variable=self.use_var, command=self._on_toggle_use).pack(
            side=tk.LEFT
        )

        # 3. Independent Thread Indicator
        self.lbl_indep = ttk.Label(
            self, text="", width=4, anchor="center", cursor="hand2"
        )
        self.lbl_indep.bind("<Button-1>", self._on_indep_click)
        self.lbl_indep.pack(side=tk.LEFT)
        self._tip_indep = ToolTip(self.lbl_indep)

        # 4. Condition Indicator
        self.lbl_cond = ttk.Label(self, text="", width=6, anchor="center")
        self.lbl_cond.pack(side=tk.LEFT)
        self._tip_cond = ToolTip(self.lbl_cond)

        # 5. Group ID Label (클릭 가능)
        self.lbl_grp = ttk.Label(
            self, text="", width=12, anchor="center", relief="sunken", cursor="hand2"
        )
        self.lbl_grp.pack(side=tk.LEFT, padx=2)
        self.lbl_grp.bind("<Button-1>", self._on_group_click)
        self._tip_grp = ToolTip(self.lbl_grp)

        # 6. Key Display Label (NEW)
        self.lbl_key = ttk.Label(
            self, text="", width=8, anchor="center", relief="groove"
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
        for text, key in [("Edit", "open"), ("Copy", "copy"), ("Delete", "remove")]:
            btn = ttk.Button(
                self, text=text, width=7, command=lambda k=key: self._on_click(k)
            )
            btn.pack(side=tk.LEFT, padx=1)
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
            self.lbl_indep.config(text="")
            self.lbl_cond.config(text="")
            self.lbl_grp.config(text="")
            self.lbl_key.config(text="")
            return

        self.use_var.set(self.event.use_event)

        # Name
        if self.entry.get() != (self.event.event_name or ""):
            self.entry.delete(0, tk.END)
            self.entry.insert(0, self.event.event_name or "")

        # Independent Thread
        is_indep = getattr(self.event, "independent_thread", False)
        self.lbl_indep.config(text="IND" if is_indep else "")
        self._tip_indep.update_text(
            "독립 실행 (다른 이벤트와 병렬 처리)\n클릭하여 해제" if is_indep
            else "클릭하여 독립 실행으로 전환"
        )

        # Condition Only
        is_cond = not getattr(self.event, "execute_action", True)
        self.lbl_cond.config(text="[COND]" if is_cond else "")
        self.entry.config(foreground="gray" if is_cond else "black")
        self._tip_cond.update_text("조건만 평가 (키 입력 없음)" if is_cond else "")

        # Group
        grp = self.event.group_id or ""
        self.lbl_grp.config(text=grp if grp else "---")
        self._tip_grp.update_text(
            f"그룹: {grp}\n클릭하여 변경" if grp else "클릭하여 그룹 지정"
        )

        # Key (NEW)
        key = self.event.key_to_enter or ""
        invert = getattr(self.event, "invert_match", False)
        display = key if key else "---"
        if invert:
            display = f"≠ {display}"
        self.lbl_key.config(text=display)
        if invert:
            self._tip_key.update_text("반전 매칭: 조건 불일치 시 실행\n클릭하여 편집기 열기")
        elif key:
            self._tip_key.update_text(f"{key}\n클릭하여 편집기 열기")
        else:
            self._tip_key.update_text("클릭하여 편집기 열기")

    def _on_indep_click(self, event=None):
        if self.event:
            # 토글
            self.event.independent_thread = not getattr(
                self.event, "independent_thread", False
            )

            # Independent 설정 시 그룹 해제
            if self.event.independent_thread:
                self.event.group_id = None

            self.update_display()
            if "save" in self.cbs:
                self.cbs["save"]()

    def _on_toggle_use(self):
        if self.event:
            self.event.use_event = self.use_var.get()
            if "save" in self.cbs:
                self.cbs["save"]()

    def _on_group_click(self, event=None):
        if self.event:
            if getattr(self.event, "independent_thread", False):
                messagebox.showinfo(
                    "Info",
                    "Independent thread events cannot be grouped.",
                    parent=self.master,
                )
                return
            if "group_select" in self.cbs:
                self.cbs["group_select"](self.row_num, self.event)

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

        # --- Control Buttons ---
        f_ctrl = ttk.Frame(self)
        f_ctrl.grid(row=1, column=0, columnspan=2, pady=5, sticky="we")

        ttk.Button(f_ctrl, text="Add Event (Open Editor)", command=self._add_event).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True
        )
        ttk.Button(
            f_ctrl,
            text="Import Events",
            command=lambda: EventImporter(self.win, self._import),
        ).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)

        # Auto Sort Button
        ttk.Button(f_ctrl, text="Auto Sort", command=self._sort_events).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True
        )

        # Group Management Button (NEW)
        ttk.Button(f_ctrl, text="Manage Groups", command=self._manage_groups).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True
        )

        # Graph Viewer Button (NEW)
        ttk.Button(f_ctrl, text="View Graph", command=self._open_graph).pack(
            side=tk.LEFT, padx=2, fill=tk.X, expand=True
        )

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(
            label="Apply Pixel/Region Info to Similar Areas",
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

    def _sort_events(self):
        """
        이벤트 목록 자동 정렬 로직
        1. Independent Thread (True -> False)
        2. Group ID (String, Empty last)
        3. Priority (Ascending)
        4. Key (0-9 → A-Z → F1-F12 → Special → None)
        5. Name (Ascending)
        """
        if not self.profile.event_list:
            return

        def sort_key(e: EventModel):
            is_indep = 0 if getattr(e, "independent_thread", False) else 1
            grp = getattr(e, "group_id", "") or ""
            grp_order = 0 if grp else 1
            prio = getattr(e, "priority", 0)
            key_order = self._get_key_sort_order(e.key_to_enter)
            name = e.event_name or ""
            return (is_indep, grp_order, grp, prio, key_order, name)

        self.save_names()
        self.profile.event_list.sort(key=sort_key)
        self.update_events()
        self.save_cb()
        messagebox.showinfo(
            "Sorted",
            "Events sorted by:\n"
            "Independent → Group → Priority → Key (0-9→A-Z→F1-F12→Special) → Name",
            parent=self.win,
        )

    def _manage_groups(self):
        """그룹 관리 다이얼로그"""
        if not self._get_existing_groups():
            messagebox.showinfo(
                "Groups",
                "No groups defined yet.\nClick on '---' in any event row to assign a group.",
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
        if not target:
            return False, "Group name cannot be empty."
        if target == "(None)":
            return False, "'(None)' is reserved."
        if target.lower() != old_name.lower() and target.lower() in {
            g.lower() for g in self._get_existing_groups()
        }:
            return False, f"'{target}' already exists."

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
                "Warning", "Invalid source event.", parent=self.win
            )

        if not messagebox.askyesno(
            "Confirm",
            f"Apply Info to all events with Area {src.latest_position}?",
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
            messagebox.showinfo("Success", f"{cnt} events updated.", parent=self.win)
        else:
            messagebox.showinfo("Info", "No matching events found.", parent=self.win)

    def _create_header(self):
        """컬럼 헤더 생성"""
        header = ttk.Frame(self)
        header.grid(row=2, column=0, columnspan=2, padx=5, pady=(5, 0), sticky="ew")

        # 각 컬럼 레이블 (EventRow와 동일한 너비)
        _hdr = [
            ("#",          2,  "center", {},                              "이벤트 순서"),
            ("Use",        3,  "center", {},                              "체크 해제 시 이벤트를 건너뜁니다"),
            ("Ind",        4,  "center", {},                              "독립 실행 (클릭하여 전환)"),
            ("Type",       6,  "center", {},                              "조건 전용 여부"),
            ("Group",     12,  "center", {"padx": 2},                     "이벤트 그룹 (클릭하여 변경)"),
            ("Key",        8,  "center", {"padx": 2},                     "입력할 키 (클릭하여 편집)"),
            ("Event Name", 0,  "w",      {"padx": 5, "fill": tk.X, "expand": True}, "이벤트 이름"),
            ("Actions",   22,  "center", {},                              "편집 / 복사 / 삭제"),
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
            row=2, column=0, columnspan=2, sticky="ew", pady=(25, 0), padx=5
        )

    def _load_events(self):
        for i, evt in enumerate(self.profile.event_list):
            self._add_row(i, evt, resize=False)
        self._update_delete_buttons()

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
        row.grid(row=idx + 3, column=0, columnspan=2, padx=5, pady=2, sticky="ew")
        self.rows.append(row)

    def _open_editor(self, row, evt):
        KeystrokeEventEditor(
            self.win,
            row,
            self._on_editor_save,
            lambda: evt,
            existing_events=self.profile.event_list,
        )

    def _on_editor_save(self, evt, is_edit, row=0):
        if is_edit and 0 <= row < len(self.profile.event_list):
            self.profile.event_list[row] = evt
        else:
            self.profile.event_list.append(evt)
        self.update_events()
        self.save_cb(check_name=False)

    def _copy_row(self, evt):
        if not evt:
            return messagebox.showinfo("Info", "Only set events can be copied")
        try:
            # 수동으로 이벤트 복사
            new = EventModel(
                event_name=f"Copy of {evt.event_name}",
                latest_position=evt.latest_position,
                clicked_position=evt.clicked_position,
                latest_screenshot=(
                    evt.latest_screenshot.copy() if evt.latest_screenshot else None
                ),
                held_screenshot=(
                    evt.held_screenshot.copy() if evt.held_screenshot else None
                ),
                ref_pixel_value=evt.ref_pixel_value,
                key_to_enter=evt.key_to_enter,
                press_duration_ms=getattr(evt, "press_duration_ms", None),
                randomization_ms=getattr(evt, "randomization_ms", None),
                independent_thread=getattr(evt, "independent_thread", False),
                match_mode=getattr(evt, "match_mode", "pixel"),
                invert_match=getattr(evt, "invert_match", False),
                region_size=getattr(evt, "region_size", None),
                execute_action=getattr(evt, "execute_action", True),
                group_id=getattr(evt, "group_id", None),
                priority=getattr(evt, "priority", 0),
                conditions=copy.deepcopy(getattr(evt, "conditions", {})),
            )
            new.use_event = evt.use_event

            self.profile.event_list.append(new)
            self._add_row(event=new)
            self.save_cb()
            self._update_delete_buttons()
            if self.status_cb:
                self.status_cb("이벤트 복사됨")
        except Exception as e:
            messagebox.showerror("Error", f"Copy failed: {e}")

    def _remove_row(self, row_widget, row_num):
        if len(self.profile.event_list) < 2:
            return
        row_widget.destroy()
        self.rows.remove(row_widget)
        if 0 <= row_num < len(self.profile.event_list):
            self.profile.event_list.pop(row_num)
        for i, row in enumerate(self.rows):
            row.row_num = i
        self._update_row_indices()
        self._update_delete_buttons()
        self.save_cb()
        self.win.update_idletasks()

    def _import(self, evts):
        self.profile.event_list.extend(evts)
        for e in evts:
            self._add_row(event=e)
        self.save_cb()

    def _update_row_indices(self):
        """모든 행의 인덱스 라벨 업데이트"""
        for i, row in enumerate(self.rows):
            row.grid(row=i + 3, column=0, columnspan=2, padx=5, pady=2, sticky="ew")
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
        self.win.update_idletasks()

    def save_names(self):
        for i, r in enumerate(self.rows):
            if i < len(self.profile.event_list):
                self.profile.event_list[i].event_name = r.get_name()


class KeystrokeProfiles:
    def __init__(self, main_win, prof_name, save_cb=None):
        self.main_win, self.prof_name, self.ext_save_cb = main_win, prof_name, save_cb
        self.prof_dir = Path("profiles")
        self._dirty = False
        self._autosave_after_id = None

        self.win = tk.Toplevel(main_win)
        self.win.title(f"Profile Manager - {self.prof_name}")
        self.win.transient(main_win)
        self.win.grab_set()
        self.win.bind("<Escape>", self._close)
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        self.profile = self._load()
        self.p_frame = ProfileFrame(
            self.win, prof_name, self.profile.favorite,
            on_change=self._on_changed,
            profiles_dir=self.prof_dir,
        )
        self.p_frame.pack(pady=5)
        self.e_frame = EventListFrame(
            self.win, self.profile, self._on_changed,
            name_getter=lambda: self.prof_name,
            status_cb=self._show_temp_status,
        )
        self.e_frame.pack(fill="both", expand=True)

        f_btn = ttk.Frame(self.win, style="success.TFrame")
        f_btn.pack(side="bottom", anchor="e", pady=10, fill="both")
        self.lbl_status = ttk.Label(f_btn, text="Auto-save enabled", foreground="gray")
        self.lbl_status.pack(side=tk.LEFT, padx=5)
        ttk.Button(f_btn, text="Close", command=self._close).pack(
            side=tk.LEFT, anchor="center", padx=5
        )

        self._load_pos()

    def _load(self):
        try:
            with open(self.prof_dir / f"{self.prof_name}.pkl", "rb") as f:
                p = pickle.load(f)
                # Backward compatibility defaults
                for e in p.event_list:
                    if not hasattr(e, "match_mode"):
                        e.match_mode = "pixel"
                    if not hasattr(e, "invert_match"):
                        e.invert_match = False
                    if not hasattr(e, "execute_action"):
                        e.execute_action = True
                    if not hasattr(e, "group_id"):
                        e.group_id = None
                    if not hasattr(e, "priority"):
                        e.priority = 0
                    if not hasattr(e, "conditions"):
                        e.conditions = {}
                    if not hasattr(e, "independent_thread"):
                        e.independent_thread = False
                p.favorite = getattr(p, "favorite", False)
                return p
        except Exception:
            return ProfileModel(name=self.prof_name, event_list=[], favorite=False)

    def _save(self, check_name=True, reload=True):
        if not self.profile.event_list:
            raise ValueError("At least one event must be set")
        new_name, is_fav = self.p_frame.get_data()
        new_name = (new_name or "").strip()

        if check_name and not new_name:
            raise ValueError("Enter profile name")
        if not new_name:
            # Auto-save 중 임시 공백 입력은 기존 파일명을 유지한다.
            new_name = self.prof_name
        self.profile.favorite = is_fav
        self.profile.name = new_name

        old_name = self.prof_name
        renamed = False
        if new_name != self.prof_name:
            if (self.prof_dir / f"{new_name}.pkl").exists():
                raise ValueError(f"'{new_name}' exists.")
            (self.prof_dir / f"{self.prof_name}.pkl").unlink(missing_ok=True)
            self.prof_name = new_name
            renamed = True

        if reload:
            self.e_frame.update_events()
            self.e_frame.save_names()
        with open(self.prof_dir / f"{self.prof_name}.pkl", "wb") as f:
            pickle.dump(self.profile, f)
        if reload:
            self.e_frame.update_events()
        if renamed and self.ext_save_cb:
            self.ext_save_cb(self.prof_name)
        return old_name != self.prof_name

    def _show_temp_status(self, text: str, duration_ms: int = 2000):
        self.lbl_status.config(text=text, foreground="#006600")
        self.win.after(duration_ms, lambda: self.lbl_status.config(
            text="Auto-save enabled", foreground="gray"
        ))

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        star = "* " if dirty else ""
        self.win.title(f"{star}Profile Manager - {self.prof_name}")

    def _run_autosave(self, check_name=False):
        self._autosave_after_id = None
        try:
            self.e_frame.save_names()
            self._save(check_name=check_name, reload=False)
            self._set_dirty(False)
            self.lbl_status.config(text="Auto-saved", foreground="gray")
        except Exception as e:
            self._set_dirty(True)
            self.lbl_status.config(text=f"Auto-save failed: {e}", foreground="#b30000")

    def _schedule_autosave(self, delay_ms=250, check_name=False):
        if self._autosave_after_id:
            self.win.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        self._autosave_after_id = self.win.after(
            delay_ms, lambda: self._run_autosave(check_name=check_name)
        )

    def _on_changed(self, check_name=False, reload=False):
        self._set_dirty(True)
        self.lbl_status.config(text="Saving...", foreground="gray")
        self._schedule_autosave(check_name=check_name)

    def _flush_autosave(self, check_name=True):
        if self._autosave_after_id:
            self.win.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        try:
            self.e_frame.save_names()
            self._save(check_name=check_name, reload=False)
            self._set_dirty(False)
            self.lbl_status.config(text="Auto-saved", foreground="gray")
            return True
        except Exception as e:
            self._set_dirty(True)
            self.lbl_status.config(text=f"Auto-save failed: {e}", foreground="#b30000")
            messagebox.showerror("Error", str(e), parent=self.win)
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

    def _parse_position(self, pos_str: str) -> tuple[str, str]:
        """위치 문자열을 x, y 좌표로 파싱"""
        parts = pos_str.split("/")
        return parts[0], parts[1]

    def _load_pos(self):
        if pos := StateUtils.load_main_app_state().get("prof_pos"):
            x, y = self._parse_position(pos)
            self.win.geometry(f"+{x}+{y}")
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
        self.win.title("Profile Graph")
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

        ttk.Button(self.toolbar, text="Refresh", command=lambda: self.refresh(True)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(self.toolbar, text="Close", command=self._close).pack(
            side=tk.LEFT, padx=2
        )
        self.lbl_info = ttk.Label(self.toolbar, text="")
        self.lbl_info.pack(side=tk.RIGHT, padx=6)

        frame = ttk.Frame(self.win)
        frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(frame, bg="#f8f7f2")
        self.canvas.pack(side=tk.LEFT, fill="both", expand=True)

        self.scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
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
            messagebox.showerror("Graph Error", str(e), parent=self.win)
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
