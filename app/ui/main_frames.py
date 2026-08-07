from __future__ import annotations

import os
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox
from tkinter import ttk
from typing import Any

from loguru import logger

from app.storage.modkey_sets_storage import (
    DEFAULT_MODKEY_SET_NAME,
    copy_modkey_set,
    delete_modkey_set,
    ensure_default_modkey_set,
    list_modkey_set_names,
)
from app.storage.profile_storage import (
    copy_profile as copy_profile_storage,
    delete_profile_files,
    ensure_quick_profile,
    list_profile_names,
    load_profile_favorites,
    load_profile_meta_favorite,
)
from app.core.run_composition import (
    format_run_profile_summary,
    normalize_run_profile_list,
)
from app.storage.profile_display import QUICK_PROFILE_NAME, build_profile_display_values
from app.ui import theme
from app.utils.i18n import txt
from app.utils.system import ProcessCollector
from app.utils.window_state import WindowUtils

VoidCallback = Callable[[], None]
RunProfilesChanged = Callable[[list[str]], None]

# Shared Target-card grid: equal-width narrow combos + aligned action columns.
_TARGET_LABEL_MIN = 80
_TARGET_COMBO_CHARS = 18
_TARGET_ACTION_MIN = 56
_TARGET_ACTION_COLS = 4  # columns 2..5


def _configure_target_row_grid(frame: tk.Frame) -> None:
    frame.grid_columnconfigure(0, weight=0, minsize=_TARGET_LABEL_MIN)
    frame.grid_columnconfigure(1, weight=0)
    for col in range(2, 2 + _TARGET_ACTION_COLS):
        frame.grid_columnconfigure(
            col, weight=1, minsize=_TARGET_ACTION_MIN, uniform="target_actions"
        )


class ProcessFrame(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        textvariable: tk.StringVar,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        # col0 label | col1 fixed combo | col2-5 refresh (fills remaining)
        _configure_target_row_grid(self)

        self.lbl_process: tk.Label = tk.Label(self, anchor="w", width=8)
        self.lbl_process.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.process_combobox: ttk.Combobox = ttk.Combobox(
            self,
            textvariable=textvariable,
            state="readonly",
            width=_TARGET_COMBO_CHARS,
        )
        self.process_combobox.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self.refresh_button: tk.Button = tk.Button(
            self, command=self.refresh_processes
        )
        self.refresh_button.grid(
            row=0,
            column=2,
            columnspan=_TARGET_ACTION_COLS,
            sticky="we",
        )
        self.refresh_texts()
        self.refresh_processes()

    def refresh_texts(self) -> None:
        self.lbl_process.config(text=txt("Process:", "프로세스:"))
        self.refresh_button.config(text=txt("Refresh", "새로고침"))

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


class ProfileFrame(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        textvariable: tk.StringVar,
        profiles_dir: str | Path,
        edit_cb: VoidCallback | None = None,
        sort_cb: VoidCallback | None = None,
        list_changed_cb: VoidCallback | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.profiles_dir = Path(profiles_dir)
        self.selected_profile_var = textvariable
        self.profile_display_var: tk.StringVar = tk.StringVar()
        self.profile_names: list[str] = []
        self.name_to_index: dict[str, int] = {}
        self.favorite_names: set[str] = set()
        self._edit_cb = edit_cb
        self._sort_cb = sort_cb
        self._list_changed_cb = list_changed_cb

        self._normal_font = tkfont.nametofont("TkTextFont").copy()
        self._bold_font = tkfont.nametofont("TkTextFont").copy()
        self._bold_font.configure(weight="bold")

        # col0 label | col1 fixed combo | edit | copy | delete | sort
        _configure_target_row_grid(self)

        self.lbl_profiles: tk.Label = tk.Label(self, anchor="w", width=8)
        self.lbl_profiles.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.profile_combobox: ttk.Combobox = ttk.Combobox(
            self,
            textvariable=self.profile_display_var,
            state="readonly",
            width=_TARGET_COMBO_CHARS,
        )
        self.profile_combobox.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self.profile_combobox.bind(
            "<<ComboboxSelected>>",
            self._on_profile_selected,
        )
        self.edit_button: tk.Button = tk.Button(
            self, command=self._on_edit_clicked
        )
        self.edit_button.grid(row=0, column=2, sticky="we", padx=(0, 6))
        self.copy_button: tk.Button = tk.Button(self, command=self.copy_profile)
        self.copy_button.grid(row=0, column=3, sticky="we", padx=(0, 6))
        self.del_button: tk.Button = tk.Button(self, command=self.delete_profile)
        self.del_button.grid(row=0, column=4, sticky="we", padx=(0, 6))
        self.sort_button: tk.Button = tk.Button(
            self, command=self._on_sort_clicked
        )
        self.sort_button.grid(row=0, column=5, sticky="we")
        self.refresh_texts()
        self.load_profiles()

    def _on_edit_clicked(self) -> None:
        if self._edit_cb is not None:
            self._edit_cb()

    def _on_sort_clicked(self) -> None:
        if self._sort_cb is not None:
            self._sort_cb()

    def _apply_selected_profile_font(self, profile_name: str) -> None:
        font = (
            self._bold_font
            if profile_name in self.favorite_names
            and profile_name != QUICK_PROFILE_NAME
            else self._normal_font
        )
        self.profile_combobox.configure(font=font)

    def _on_profile_selected(self, _event: object | None = None) -> None:
        idx = self.profile_combobox.current()
        if not (0 <= idx < len(self.profile_names)):
            return
        profile_name = self.profile_names[idx]
        self.selected_profile_var.set(profile_name)
        self._apply_selected_profile_font(profile_name)

    def set_selected_profile(self, profile_name: str) -> bool:
        idx = self.name_to_index.get(profile_name)
        if idx is None:
            return False
        self.profile_combobox.current(idx)
        self._on_profile_selected()
        return True

    def get_selected_profile_name(self) -> str:
        idx = self.profile_combobox.current()
        if 0 <= idx < len(self.profile_names):
            return self.profile_names[idx]
        return self.selected_profile_var.get()

    def load_profiles(self, select_name: str | None = None) -> None:
        started = time.perf_counter()
        self.profiles_dir.mkdir(exist_ok=True)
        ensure_quick_profile(self.profiles_dir)

        names = [
            name
            for name in list_profile_names(self.profiles_dir)
            if name != QUICK_PROFILE_NAME
        ]
        favs: list[str] = []
        non_favs: list[str] = []
        favorite_map: dict[str, bool] = {}
        try:
            favorite_map = load_profile_favorites(self.profiles_dir, names)
        except Exception as e:
            logger.warning(f"Favorite map load failed: {e}")

        for name in names:
            try:
                is_favorite = favorite_map.get(name)
                if is_favorite is None:
                    is_favorite = load_profile_meta_favorite(self.profiles_dir, name)
                (favs if is_favorite else non_favs).append(name)
            except Exception as e:
                logger.warning(f"Load failed {name}: {e}")
                non_favs.append(name)

        self.favorite_names = set(favs)
        sorted_profiles = [QUICK_PROFILE_NAME] + sorted(favs) + sorted(non_favs)
        self.profile_names = sorted_profiles
        self.name_to_index = {name: idx for idx, name in enumerate(sorted_profiles)}

        self.profile_combobox.configure(
            values=build_profile_display_values(
                sorted_profiles,
                self.favorite_names,
                quick_profile_name=QUICK_PROFILE_NAME,
            )
        )

        if not sorted_profiles:
            self.selected_profile_var.set("")
            self.profile_display_var.set("")
            self._apply_selected_profile_font("")
            return

        target_name = (
            select_name or self.selected_profile_var.get() or QUICK_PROFILE_NAME
        )
        if not self.set_selected_profile(target_name):
            self.profile_combobox.current(0)
            self._on_profile_selected()
        if self._list_changed_cb is not None:
            self._list_changed_cb()
        if os.getenv("KEYSIM_PROFILE_PERF") == "1":
            print(
                f"[perf] load_profiles: {(time.perf_counter() - started) * 1000.0:.3f}ms"
            )

    def refresh_texts(self) -> None:
        self.lbl_profiles.config(text=txt("Profiles:", "프로필:"))
        self.edit_button.config(text=txt("Edit", "편집"))
        self.copy_button.config(text=txt("Copy", "복사"))
        self.del_button.config(text=txt("Delete", "삭제"))
        self.sort_button.config(text=txt("Sort", "정렬"))

    def copy_profile(self) -> None:
        if not (curr := self.get_selected_profile_name()):
            return
        dst_name = f"{curr} - Copied"
        if (self.profiles_dir / f"{dst_name}.json").exists():
            messagebox.showwarning(
                txt("Warning", "경고"),
                txt(
                    "Profile '{name}' already exists.",
                    "'{name}' 프로필이 이미 존재합니다.",
                    name=dst_name,
                ),
                parent=self,
            )
            return
        try:
            copy_profile_storage(self.profiles_dir, curr, dst_name)
            self.load_profiles(select_name=dst_name)
            messagebox.showinfo(
                txt("Profile Copied", "프로필 복사 완료"),
                txt(
                    "Copied '{src}' to '{dst}' and selected it.",
                    "'{src}' 프로필을 '{dst}'(으)로 복사하고 선택했습니다.",
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

    def delete_profile(self) -> None:
        curr = self.get_selected_profile_name()
        if not curr:
            return
        if curr == QUICK_PROFILE_NAME:
            messagebox.showinfo(
                txt("Info", "안내"),
                txt(
                    "The default profile cannot be deleted.",
                    "기본 프로필은 삭제할 수 없습니다.",
                ),
                parent=self,
            )
            return
        if messagebox.askokcancel(
            txt("Warning", "경고"),
            txt(
                "Delete profile '{name}'?",
                "프로필 '{name}'을(를) 삭제하시겠습니까?",
                name=curr,
            ),
            parent=self,
        ):
            delete_profile_files(self.profiles_dir, curr)
            self.load_profiles()
            messagebox.showinfo(
                txt("Profile Deleted", "프로필 삭제 완료"),
                txt(
                    "Deleted '{name}'.",
                    "'{name}' 프로필을 삭제했습니다.",
                    name=curr,
                ),
                parent=self,
            )


class RunSetFrame(tk.Frame):
    """Multi-profile run selection (edit profile stays on ProfileFrame)."""

    def __init__(
        self,
        master: tk.Misc,
        profiles_dir: str | Path,
        *,
        on_change: RunProfilesChanged | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.profiles_dir = Path(profiles_dir)
        self._on_change = on_change
        self._run_profiles: list[str] = []
        self._available: list[str] = []

        _configure_target_row_grid(self)

        self.lbl_run_set: tk.Label = tk.Label(self, anchor="w", width=8)
        self.lbl_run_set.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.summary_var: tk.StringVar = tk.StringVar(value="—")
        self.summary_entry: ttk.Entry = ttk.Entry(
            self,
            textvariable=self.summary_var,
            state="readonly",
            width=_TARGET_COMBO_CHARS,
        )
        self.summary_entry.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self.select_button: tk.Button = tk.Button(self, command=self.open_selector)
        self.select_button.grid(
            row=0,
            column=2,
            columnspan=_TARGET_ACTION_COLS,
            sticky="we",
        )
        self.refresh_texts()

    def get_run_profiles(self) -> list[str]:
        return list(self._run_profiles)

    def set_available_profiles(self, names: list[str]) -> None:
        self._available = list(names)
        self.set_run_profiles(self._run_profiles, notify=False)

    def set_run_profiles(
        self, names: list[str] | None, *, notify: bool = True
    ) -> None:
        cleaned = normalize_run_profile_list(names, self._available)
        if not cleaned and self._available:
            fallback = (
                QUICK_PROFILE_NAME
                if QUICK_PROFILE_NAME in self._available
                else self._available[0]
            )
            cleaned = [fallback]
        self._run_profiles = cleaned
        self._refresh_summary()
        if notify and self._on_change is not None:
            self._on_change(list(self._run_profiles))

    def ensure_default_from_profile(self, profile_name: str) -> None:
        if self._run_profiles:
            return
        if profile_name and profile_name in self._available:
            self.set_run_profiles([profile_name], notify=False)
        else:
            self.set_run_profiles([], notify=False)

    def _refresh_summary(self) -> None:
        self.summary_var.set(format_run_profile_summary(self._run_profiles))

    def refresh_texts(self) -> None:
        self.lbl_run_set.config(text=txt("Run set:", "실행 세트:"))
        self.select_button.config(text=txt("Select…", "선택…"))

    def open_selector(self) -> None:
        if not self._available:
            messagebox.showinfo(
                txt("Info", "안내"),
                txt("No profiles available.", "사용 가능한 프로필이 없습니다."),
                parent=self,
            )
            return

        win = tk.Toplevel(self)
        win.title(txt("Select Run Profiles", "실행 프로필 선택"))
        win.configure(bg=theme.SURFACE_PAPER)
        win.transient(self.winfo_toplevel())
        body = tk.Frame(
            win, bg=theme.SURFACE_PAPER, padx=theme.SPACE_3, pady=theme.SPACE_3
        )
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text=txt(
                "Check profiles to run together at Start.",
                "시작 시 함께 실행할 프로필을 선택하세요.",
            ),
            bg=theme.SURFACE_PAPER,
            fg=theme.INK_SECONDARY,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, theme.SPACE_2))

        list_frame = tk.Frame(body, bg=theme.SURFACE_CANVAS, height=220)
        list_frame.pack(fill="both", expand=True)
        list_frame.pack_propagate(False)
        vars_by_name: dict[str, tk.BooleanVar] = {}
        selected = set(self._run_profiles)
        for name in self._available:
            var = tk.BooleanVar(value=name in selected)
            vars_by_name[name] = var
            tk.Checkbutton(
                list_frame,
                text=name,
                variable=var,
                anchor="w",
                bg=theme.SURFACE_CANVAS,
                activebackground=theme.SURFACE_CANVAS,
                fg=theme.INK_PRIMARY,
                selectcolor=theme.SURFACE_PAPER,
            ).pack(fill="x", padx=theme.SPACE_1, pady=1)

        btn_row = tk.Frame(body, bg=theme.SURFACE_PAPER)
        btn_row.pack(fill="x", pady=(theme.SPACE_3, 0))

        def apply_and_close() -> None:
            chosen = [n for n in self._available if vars_by_name[n].get()]
            if not chosen:
                messagebox.showwarning(
                    txt("Warning", "경고"),
                    txt(
                        "Select at least one profile.",
                        "프로필을 하나 이상 선택하세요.",
                    ),
                    parent=win,
                )
                return
            self.set_run_profiles(chosen, notify=True)
            win.destroy()

        def cancel() -> None:
            win.destroy()

        tk.Button(btn_row, text=txt("Cancel", "취소"), command=cancel).pack(
            side=tk.RIGHT, padx=(theme.SPACE_1, 0)
        )
        tk.Button(btn_row, text=txt("Apply", "적용"), command=apply_and_close).pack(
            side=tk.RIGHT
        )

        WindowUtils.center_window(win)
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()


class ButtonFrame(tk.Frame):
    """Tool buttons shown in the main tools card."""

    _BTN_KEYS = (
        ("quick_events", ("Quick Events", "빠른 이벤트")),
        ("settings", ("Settings", "설정")),
        ("clear_logs", ("Clear Logs", "로그 삭제")),
    )

    def __init__(
        self,
        master: tk.Misc,
        events_cb: VoidCallback,
        settings_cb: VoidCallback,
        clear_cb: VoidCallback,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        for col in range(3):
            self.grid_columnconfigure(col, weight=1, uniform="tools")
        commands: dict[str, VoidCallback] = {
            "quick_events": events_cb,
            "settings": settings_cb,
            "clear_logs": clear_cb,
        }
        self.btns: dict[str, tk.Button] = {}
        for col, (key, label_pair) in enumerate(self._BTN_KEYS):
            btn = tk.Button(self, text=txt(*label_pair), height=1, command=commands[key])
            btn.grid(row=0, column=col, sticky="we", padx=theme.SPACE_1)
            self.btns[key] = btn
        self.quick_events_button = self.btns["quick_events"]
        self.settings_button = self.btns["settings"]
        self.clear_logs_button = self.btns["clear_logs"]

    def refresh_texts(self) -> None:
        for key, label_pair in self._BTN_KEYS:
            self.btns[key].config(text=txt(*label_pair))


class ModKeySetFrame(tk.Frame):
    """Independent ModKey set selector (profile-style dropdown + manage actions)."""

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

        # col0 label | col1 fixed combo | edit | copy | delete | (empty slot)
        _configure_target_row_grid(self)

        self.lbl_sets: tk.Label = tk.Label(self, anchor="w", width=8)
        self.lbl_sets.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.sets_combobox: ttk.Combobox = ttk.Combobox(
            self,
            textvariable=self.selected_var,
            state="readonly",
            width=_TARGET_COMBO_CHARS,
        )
        self.sets_combobox.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self.sets_combobox.bind("<<ComboboxSelected>>", self._on_set_selected)
        self.edit_button: tk.Button = tk.Button(self, command=self._edit_cb)
        self.edit_button.grid(row=0, column=2, sticky="we", padx=(0, 6))
        self.copy_button: tk.Button = tk.Button(self, command=self.copy_set)
        self.copy_button.grid(row=0, column=3, sticky="we", padx=(0, 6))
        self.del_button: tk.Button = tk.Button(self, command=self.delete_set)
        self.del_button.grid(row=0, column=4, sticky="we", padx=(0, 6))
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
        self.lbl_sets.config(text=txt("ModKeys:", "수정키:"))
        self.edit_button.config(text=txt("Edit", "편집"))
        self.copy_button.config(text=txt("Copy", "복사"))
        self.del_button.config(text=txt("Delete", "삭제"))

    def copy_set(self) -> None:
        curr = self.get_selected_set_name()
        if not curr:
            return
        dst_name = f"{curr} - Copied"
        if dst_name in self.name_to_index:
            messagebox.showwarning(
                txt("Warning", "경고"),
                txt(
                    "ModKey set '{name}' already exists.",
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
                txt("ModKey Set Copied", "수정키 세트 복사 완료"),
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
                    "The last ModKey set cannot be deleted.",
                    "마지막 수정키 세트는 삭제할 수 없습니다.",
                ),
                parent=self,
            )
            return
        if not messagebox.askokcancel(
            txt("Warning", "경고"),
            txt(
                "Delete ModKey set '{name}'?",
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
                txt("ModKey Set Deleted", "수정키 세트 삭제 완료"),
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


