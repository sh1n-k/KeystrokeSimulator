from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox
from tkinter import ttk
from typing import Any, Literal

from app.domain.display_text import (
    TARGET_COMBO_CHARS,
    ellipsize_display,
    run_set_display,
)
from app.storage.modkey_sets_storage import (
    DEFAULT_MODKEY_SET_NAME,
    copy_modkey_set,
    delete_modkey_set,
    ensure_default_modkey_set,
    list_modkey_set_names,
)
from app.storage.profile_display import QUICK_PROFILE_NAME, build_profile_display_values
from app.storage.profile_storage import ordered_profile_names
from app.storage.run_sets_storage import (
    CURRENT_RUN_SET_ID,
    get_run_set,
    is_current_run_set,
    list_run_set_names,
)
from app.ui import theme
from app.utils.i18n import txt
from app.platform.system import ProcessCollector

VoidCallback = Callable[[], None]
TargetKind = Literal["profile", "run_set"]
RunTarget = tuple[TargetKind, str]

_TARGET_LABEL_MIN = 84
_TARGET_ACTION_MIN = 84
_SEPARATOR = "─" * 14


def _configure_target_row_grid(frame: tk.Frame) -> None:
    # Same column widths on every row so the combos line up, with or without
    # a button in the last column.
    frame.grid_columnconfigure(0, weight=0, minsize=_TARGET_LABEL_MIN)
    frame.grid_columnconfigure(1, weight=1)
    frame.grid_columnconfigure(2, weight=0, minsize=_TARGET_ACTION_MIN)


class HoverTip:
    """마우스를 올리면 전체 문구를 보여주는 작은 말풍선."""

    def __init__(self, widget: tk.Misc, text: str = "") -> None:
        self.widget = widget
        self.text = text
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def update_text(self, text: str) -> None:
        self.text = text

    def _show(self, _event: object | None = None) -> None:
        self._hide()
        if not self.text:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tk.Label(
            tip,
            text=self.text,
            bg=theme.INK_PRIMARY,
            fg=theme.INK_INVERSE,
            padx=theme.SPACE_2,
            pady=theme.SPACE_1,
            justify="left",
            wraplength=420,
            font=theme.fonts()["caption"],
        ).pack()
        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 2
            tip.geometry(f"+{x}+{y}")
        except tk.TclError:
            tip.destroy()
            return
        self._tip = tip

    def _hide(self, _event: object | None = None) -> None:
        tip, self._tip = self._tip, None
        if tip is not None:
            try:
                tip.destroy()
            except tk.TclError:
                pass


class ProcessFrame(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        textvariable: tk.StringVar,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        # col0 label | col1 combo | col2 refresh
        _configure_target_row_grid(self)

        self.lbl_process: tk.Label = tk.Label(self, anchor="w")
        self.lbl_process.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.process_combobox: ttk.Combobox = ttk.Combobox(
            self,
            textvariable=textvariable,
            state="readonly",
            width=TARGET_COMBO_CHARS,
        )
        self.process_combobox.grid(row=0, column=1, sticky="we", padx=(0, 6))
        self.refresh_button: tk.Button = tk.Button(
            self, command=self.refresh_processes
        )
        self.refresh_button.grid(row=0, column=2, sticky="we")
        self.refresh_texts()
        self.refresh_processes()

    def refresh_texts(self) -> None:
        self.lbl_process.config(text=txt("Target", "대상"))
        self.refresh_button.config(text="⟳")

    def refresh_processes(self) -> None:
        curr_val = self.process_combobox.get()
        curr_name = (
            curr_val.rsplit(" (", 1)[0] if curr_val and "(" in curr_val else None
        )

        procs = sorted(ProcessCollector.get(), key=lambda x: x[0].lower())
        self.process_combobox.configure(values=[f"{n} ({p})" for n, p, _ in procs])

        idx = next((i for i, (n, _, _) in enumerate(procs) if n == curr_name), 0)
        if procs:
            self.process_combobox.current(idx)
            self.process_combobox.event_generate("<<ComboboxSelected>>")


class RunTargetFrame(tk.Frame):
    """"실행" 콤보: 프로필과 저장된 실행 세트를 구분선으로 함께 보여준다.

    프로필을 고르면 그 프로필 하나를 실행한다. 선택은 `profile_var`(프로필)와
    `run_set_var`(세트 이름, 프로필 실행이면 CURRENT_RUN_SET_ID)에 쓴다.
    """

    def __init__(
        self,
        master: tk.Misc,
        profile_var: tk.StringVar,
        run_set_var: tk.StringVar,
        *,
        profiles_dir: str | Path,
        sets_path: Path,
        edit_cb: Callable[[RunTarget], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.profiles_dir = Path(profiles_dir)
        self.sets_path = Path(sets_path)
        self.profile_var = profile_var
        self.run_set_var = run_set_var
        self._edit_cb = edit_cb
        self.profile_names: list[str] = []
        self.run_set_names: list[str] = []
        self.targets: list[RunTarget | None] = []
        self._favorites: set[str] = set()
        self.display_var = tk.StringVar(master=self)
        _configure_target_row_grid(self)

        self.lbl_target: tk.Label = tk.Label(self, anchor="w")
        self.lbl_target.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.combobox: ttk.Combobox = ttk.Combobox(
            self,
            textvariable=self.display_var,
            state="readonly",
            width=TARGET_COMBO_CHARS,
        )
        self.combobox.grid(row=0, column=1, sticky="we", padx=(0, 6))
        self.combobox.bind("<<ComboboxSelected>>", self._on_selected)
        self.edit_button: tk.Button = tk.Button(self, command=self._on_edit)
        self.edit_button.grid(row=0, column=2, sticky="we")
        self.refresh_texts()
        self.load()

    def refresh_texts(self) -> None:
        self.lbl_target.config(text=txt("Run", "실행"))
        self.edit_button.config(text=txt("Edit…", "편집…"))
        self._apply_values()

    def load(self, select: RunTarget | None = None) -> None:
        self.profile_names, favorites = ordered_profile_names(self.profiles_dir)
        self.run_set_names = list_run_set_names(self.sets_path)
        self.targets = [("profile", name) for name in self.profile_names]
        self._favorites = favorites
        if self.run_set_names:
            self.targets.append(None)
            self.targets.extend(("run_set", name) for name in self.run_set_names)
        self._apply_values()
        wanted = select or self.get_target()
        if not self.set_target(*wanted):
            fallback = self.profile_var.get()
            if not self.set_target("profile", fallback):
                self.set_target("profile", QUICK_PROFILE_NAME)

    def _apply_values(self) -> None:
        profile_values = build_profile_display_values(
            self.profile_names, self._favorites
        )
        values = [ellipsize_display(v) for v in profile_values]
        if self.run_set_names:
            values.append(_SEPARATOR)
            values.extend(run_set_display(n) for n in self.run_set_names)
        self.combobox.configure(values=values)
        index = self._index_of(self.get_target())
        if index is not None:
            self.combobox.current(index)

    def _index_of(self, target: RunTarget) -> int | None:
        return next((i for i, t in enumerate(self.targets) if t == target), None)

    def get_target(self) -> RunTarget:
        run_set = (self.run_set_var.get() or "").strip()
        if run_set and not is_current_run_set(run_set):
            return ("run_set", run_set)
        return ("profile", self.profile_var.get())

    def set_target(self, kind: TargetKind, name: str) -> bool:
        index = self._index_of((kind, name))
        if index is None:
            return False
        self.combobox.current(index)
        if kind == "profile":
            self.profile_var.set(name)
            self.run_set_var.set(CURRENT_RUN_SET_ID)
        else:
            self.run_set_var.set(name)
        return True

    def get_run_profiles(self) -> list[str]:
        kind, name = self.get_target()
        if kind == "profile":
            return [name] if name else []
        available = set(self.profile_names)
        return [n for n in get_run_set(name, self.sets_path) if n in available]

    def _on_selected(self, _event: object | None = None) -> None:
        index = self.combobox.current()
        target = self.targets[index] if 0 <= index < len(self.targets) else None
        if target is None:
            # 구분선은 고를 수 없다. 이전 선택으로 되돌린다.
            self._apply_values()
            return
        self.set_target(*target)

    def _on_edit(self) -> None:
        if self._edit_cb is not None:
            self._edit_cb(self.get_target())


class ModKeySetFrame(tk.Frame):
    """Independent modifier key set selector. Edit/copy/delete live in the ⚙ menu."""

    def __init__(
        self,
        master: tk.Misc,
        textvariable: tk.StringVar,
        *,
        sets_path: Path,
        edit_cb: VoidCallback,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.sets_path = Path(sets_path)
        self.selected_var = textvariable
        self._edit_cb = edit_cb
        self.set_names: list[str] = []
        self.name_to_index: dict[str, int] = {}

        _configure_target_row_grid(self)

        self.lbl_sets: tk.Label = tk.Label(self, anchor="w")
        self.lbl_sets.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.sets_combobox: ttk.Combobox = ttk.Combobox(
            self,
            textvariable=self.selected_var,
            state="readonly",
            width=TARGET_COMBO_CHARS,
        )
        self.sets_combobox.grid(row=0, column=1, sticky="we", padx=(0, 6))
        self.sets_combobox.bind("<<ComboboxSelected>>", self._on_set_selected)
        self.refresh_texts()
        self.load_sets()

    def _on_set_selected(self, _event: object | None = None) -> None:
        idx = self.sets_combobox.current()
        if not (0 <= idx < len(self.set_names)):
            return
        self.selected_var.set(self.set_names[idx])

    def set_selected_set(self, set_name: str) -> bool:
        idx = self.name_to_index.get(set_name)
        if idx is None:
            return False
        self.sets_combobox.current(idx)
        self._on_set_selected()
        return True

    def get_selected_set_name(self) -> str:
        idx = self.sets_combobox.current()
        if 0 <= idx < len(self.set_names):
            return self.set_names[idx]
        return self.selected_var.get()

    def load_sets(self, select_name: str | None = None) -> None:
        ensure_default_modkey_set(self.sets_path)
        names = list_modkey_set_names(self.sets_path)
        self.set_names = names
        self.name_to_index = {name: idx for idx, name in enumerate(names)}
        self.sets_combobox.configure(values=names)
        if not names:
            self.selected_var.set("")
            return
        target = select_name or self.selected_var.get() or DEFAULT_MODKEY_SET_NAME
        if not self.set_selected_set(target):
            self.sets_combobox.current(0)
            self._on_set_selected()

    def refresh_texts(self) -> None:
        self.lbl_sets.config(text=txt("Modifier keys", "수정키"))

    def copy_set(self) -> None:
        curr = self.get_selected_set_name()
        if not curr:
            return
        dst_name = f"{curr} - Copied"
        if dst_name in self.name_to_index:
            messagebox.showwarning(
                txt("Warning", "경고"),
                txt(
                    "Modifier key set '{name}' already exists.",
                    "수정키 세트 '{name}'이(가) 이미 존재합니다.",
                    name=dst_name,
                ),
                parent=self,
            )
            return
        try:
            copy_modkey_set(curr, dst_name, self.sets_path)
            self.load_sets(select_name=dst_name)
            messagebox.showinfo(
                txt("Modifier Key Set Copied", "수정키 세트 복사 완료"),
                txt(
                    "Copied '{src}' to '{dst}' and selected it.",
                    "'{src}' 세트를 '{dst}'(으)로 복사하고 선택했습니다.",
                    src=curr,
                    dst=dst_name,
                ),
                parent=self,
            )
        except Exception as e:
            messagebox.showerror(
                txt("Error", "오류"),
                txt("Copy failed: {error}", "복사 실패: {error}", error=e),
                parent=self,
            )

    def delete_set(self) -> None:
        curr = self.get_selected_set_name()
        if not curr:
            return
        if len(self.set_names) <= 1:
            messagebox.showinfo(
                txt("Info", "안내"),
                txt(
                    "The last modifier key set cannot be deleted.",
                    "마지막 수정키 세트는 삭제할 수 없습니다.",
                ),
                parent=self,
            )
            return
        if not messagebox.askokcancel(
            txt("Warning", "경고"),
            txt(
                "Delete modifier key set '{name}'?",
                "수정키 세트 '{name}'을(를) 삭제하시겠습니까?",
                name=curr,
            ),
            parent=self,
        ):
            return
        try:
            next_name = delete_modkey_set(curr, self.sets_path)
            self.load_sets(select_name=next_name)
            messagebox.showinfo(
                txt("Modifier Key Set Deleted", "수정키 세트 삭제 완료"),
                txt(
                    "Deleted '{name}'.",
                    "'{name}' 세트를 삭제했습니다.",
                    name=curr,
                ),
                parent=self,
            )
        except Exception as e:
            messagebox.showerror(
                txt("Error", "오류"),
                txt("Delete failed: {error}", "삭제 실패: {error}", error=e),
                parent=self,
            )


