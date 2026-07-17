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

from app.storage.profile_storage import (
    copy_profile as copy_profile_storage,
    delete_profile_files,
    ensure_quick_profile,
    list_profile_names,
    load_profile_favorites,
    load_profile_meta_favorite,
)
from app.storage.profile_display import QUICK_PROFILE_NAME, build_profile_display_values
from app.ui import theme
from app.utils.i18n import txt
from app.utils.system import ProcessCollector

VoidCallback = Callable[[], None]


class ProcessFrame(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        textvariable: tk.StringVar,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        # 4-column grid keeps Process/Profile/Tools rows visually aligned.
        # col 0: label (fixed width)
        # col 1: combobox (stretches)
        # col 2..: buttons (fixed width)
        self.grid_columnconfigure(0, weight=0, minsize=80)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0, minsize=120)
        self.grid_columnconfigure(3, weight=0, minsize=120)

        self.lbl_process: tk.Label = tk.Label(self, anchor="w", width=8)
        self.lbl_process.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.process_combobox: ttk.Combobox = ttk.Combobox(
            self, textvariable=textvariable, state="readonly"
        )
        self.process_combobox.grid(row=0, column=1, sticky="we", padx=(0, 6))
        self.refresh_button: tk.Button = tk.Button(
            self, command=self.refresh_processes
        )
        self.refresh_button.grid(row=0, column=2, sticky="we", padx=(0, 6))
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
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self.profiles_dir = Path(profiles_dir)
        self.selected_profile_var = textvariable
        self.profile_display_var: tk.StringVar = tk.StringVar()
        self.profile_names: list[str] = []
        self.name_to_index: dict[str, int] = {}
        self.favorite_names: set[str] = set()

        self._normal_font = tkfont.nametofont("TkTextFont").copy()
        self._bold_font = tkfont.nametofont("TkTextFont").copy()
        self._bold_font.configure(weight="bold")

        # Same 4-column grid as ProcessFrame so labels/combos/buttons line up.
        self.grid_columnconfigure(0, weight=0, minsize=80)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0, minsize=120)
        self.grid_columnconfigure(3, weight=0, minsize=120)

        self.lbl_profiles: tk.Label = tk.Label(self, anchor="w", width=8)
        self.lbl_profiles.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.profile_combobox: ttk.Combobox = ttk.Combobox(
            self, textvariable=self.profile_display_var, state="readonly"
        )
        self.profile_combobox.grid(row=0, column=1, sticky="we", padx=(0, 6))
        self.profile_combobox.bind(
            "<<ComboboxSelected>>",
            self._on_profile_selected,
        )
        self.copy_button: tk.Button = tk.Button(self, command=self.copy_profile)
        self.copy_button.grid(row=0, column=2, sticky="we", padx=(0, 6))
        self.del_button: tk.Button = tk.Button(self, command=self.delete_profile)
        self.del_button.grid(row=0, column=3, sticky="we")
        self.refresh_texts()
        self.load_profiles()

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
        if os.getenv("KEYSIM_PROFILE_PERF") == "1":
            print(
                f"[perf] load_profiles: {(time.perf_counter() - started) * 1000.0:.3f}ms"
            )

    def refresh_texts(self) -> None:
        self.lbl_profiles.config(text=txt("Profiles:", "프로필:"))
        self.copy_button.config(text=txt("Copy", "복사"))
        self.del_button.config(text=txt("Delete", "삭제"))

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


class ProfileButtonFrame(tk.Frame):
    """Profile tools share the same 3-column rhythm as the main tools."""

    _BTN_KEYS = (
        ("modkeys", ("ModKeys", "수정키")),
        ("edit_profile", ("Edit Profile", "프로필 편집")),
        ("sort_profile", ("Sort Profile", "프로필 정렬")),
    )

    def __init__(
        self,
        master: tk.Misc,
        mod_cb: VoidCallback,
        edit_cb: VoidCallback,
        sort_cb: VoidCallback,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        for col in range(3):
            self.grid_columnconfigure(col, weight=1, uniform="tools")
        commands: dict[str, VoidCallback] = {
            "modkeys": mod_cb,
            "edit_profile": edit_cb,
            "sort_profile": sort_cb,
        }
        self.btns: dict[str, tk.Button] = {}
        for col, (key, label_pair) in enumerate(self._BTN_KEYS):
            btn = tk.Button(self, text=txt(*label_pair), height=1, command=commands[key])
            btn.grid(row=0, column=col, sticky="we", padx=theme.SPACE_1)
            self.btns[key] = btn
        self.edit_profile_button = self.btns["edit_profile"]
        self.modkeys_button = self.btns["modkeys"]
        self.sort_button = self.btns["sort_profile"]

    def refresh_texts(self) -> None:
        for key, label_pair in self._BTN_KEYS:
            self.btns[key].config(text=txt(*label_pair))
