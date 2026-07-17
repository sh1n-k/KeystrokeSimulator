from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Optional, cast

from app.ui import theme
from app.utils.i18n import txt

UI_PAD_SM = theme.SPACE_1
UI_PAD_MD = theme.SPACE_2

class GroupSelector(tk.Toplevel):
    """그룹 선택/생성 팝업"""

    def __init__(
        self,
        master: tk.Misc,
        current_group: str | None,
        existing_groups: Sequence[str],
        callback: Callable[[str | None], object],
    ) -> None:
        super().__init__(master)
        self.callback = callback
        self.result: str | None = None
        self.none_label = txt("(None)", "(없음)")
        self.existing_groups = {g.lower(): g for g in existing_groups}

        self.title(txt("Select Group", "그룹 선택"))
        cast(Any, self).transient(master)
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

        scrollbar = ttk.Scrollbar(
            frame, orient=tk.VERTICAL, command=cast(Any, self.listbox).yview
        )
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

        def on_listbox_double_click(_event: tk.Event[tk.Misc]) -> None:
            self._on_select()

        self.listbox.bind("<Double-Button-1>", on_listbox_double_click)

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

        def on_escape(_event: tk.Event[tk.Misc]) -> None:
            self.destroy()

        def on_return(_event: tk.Event[tk.Misc]) -> None:
            self._on_select()

        self.bind("<Escape>", on_escape)
        self.bind("<Return>", on_return)

    def _on_select(self) -> None:
        listbox = cast(Any, self.listbox)
        sel = cast(tuple[int, ...], listbox.curselection())
        if not sel:
            return
        value = cast(str, listbox.get(sel[0]))
        self.result = None if value == self.none_label else value
        self.callback(self.result)
        self.destroy()

    def _on_new(self) -> None:
        new_name = simpledialog.askstring(
            txt("New Group", "새 그룹"),
            txt("Enter new group name:", "새 그룹 이름을 입력하세요:"),
            parent=self,
        )
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning(
                txt("Invalid Group", "유효하지 않은 그룹"),
                txt("Group name cannot be empty.", "그룹 이름은 비워둘 수 없습니다."),
                parent=self,
            )
            return
        if new_name in {"(None)", self.none_label}:
            messagebox.showwarning(
                txt("Invalid Group", "유효하지 않은 그룹"),
                txt(
                    f"'{self.none_label}' is reserved.",
                    f"'{self.none_label}'은 예약어입니다.",
                ),
                parent=self,
            )
            return
        if new_name.lower() in self.existing_groups:
            messagebox.showwarning(
                txt("Duplicate Group", "중복 그룹"),
                txt(f"'{new_name}' already exists.", f"'{new_name}' 이미 존재합니다."),
                parent=self,
            )
            return
        self.result = new_name
        self.callback(self.result)
        self.destroy()


class GroupManagerDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        get_group_counts: Callable[[], dict[str, int]],
        rename_cb: Callable[[str, str], tuple[bool, str]],
        clear_cb: Callable[[str], int],
    ) -> None:
        super().__init__(master)
        self.get_group_counts = get_group_counts
        self.rename_cb = rename_cb
        self.clear_cb = clear_cb
        self._name_map: list[str] = []

        self.title(txt("Manage Groups", "그룹 관리"))
        cast(Any, self).transient(master)
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

        scrollbar = ttk.Scrollbar(
            body, orient=tk.VERTICAL, command=cast(Any, self.listbox).yview
        )
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

        def on_listbox_double_click(_event: tk.Event[tk.Misc]) -> None:
            self._rename_group()

        def on_escape(_event: tk.Event[tk.Misc]) -> None:
            self.destroy()

        self.listbox.bind("<Double-Button-1>", on_listbox_double_click)
        self.bind("<Escape>", on_escape)
        self._reload_groups()

        self.update_idletasks()
        x = master.winfo_rootx() + 60
        y = master.winfo_rooty() + 60
        self.geometry(f"+{x}+{y}")

    def _reload_groups(self, selected_name: Optional[str] = None) -> None:
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
        listbox = cast(Any, self.listbox)
        sel = cast(tuple[int, ...], listbox.curselection())
        if not sel:
            return None
        idx = sel[0]
        if 0 <= idx < len(self._name_map):
            return self._name_map[idx]
        return None

    def _rename_group(self) -> None:
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
            messagebox.showwarning(
                txt("Rename Failed", "이름 변경 실패"), msg, parent=self
            )
            return
        self._reload_groups(selected_name=new_name.strip())

    def _clear_group(self) -> None:
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
