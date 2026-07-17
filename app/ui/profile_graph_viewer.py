from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, cast

from PIL import Image, ImageTk

from app.core.models import ProfileModel
from app.ui import theme
from app.ui.event_graph import ensure_profile_graph_image
from app.utils.i18n import txt
from app.utils.window_state import WindowUtils


class ProfileGraphViewer:
    def __init__(
        self,
        parent: tk.Misc,
        profile: ProfileModel,
        profile_name: str,
        *,
        profiles_dir: Path,
        name_getter: Callable[[], str] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.parent = parent
        self.profile = profile
        self.profile_name = profile_name
        self.name_getter = name_getter
        self.on_close = on_close
        self.cache_dir = profiles_dir / "_graphs"
        self._auto_sized = False

        self.win = tk.Toplevel(parent)
        self.win.title(txt("Profile Graph", "프로필 그래프"))
        cast(Any, self.win).transient(parent)
        self.win.geometry("900x600")
        self.win.protocol("WM_DELETE_WINDOW", self._close)
        def on_escape(_event: tk.Event[tk.Misc]) -> None:
            self._close()

        self.win.bind("<Escape>", on_escape)
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

        self.canvas = tk.Canvas(frame, bg=theme.SURFACE_PAPER)
        self.canvas.pack(side=tk.LEFT, fill="both", expand=True)

        self.scroll_y = ttk.Scrollbar(
            frame, orient="vertical", command=cast(Any, self.canvas).yview
        )
        self.scroll_y.pack(side=tk.RIGHT, fill="y")
        self.scroll_x = ttk.Scrollbar(
            self.win, orient="horizontal", command=cast(Any, self.canvas).xview
        )
        self.scroll_x.pack(side=tk.BOTTOM, fill="x")

        self.canvas.configure(yscrollcommand=self.scroll_y.set)
        self.canvas.configure(xscrollcommand=self.scroll_x.set)
        def on_canvas_enter(_event: tk.Event[tk.Misc]) -> None:
            self.canvas.focus_set()

        self.canvas.bind("<Enter>", on_canvas_enter)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.win.bind("<MouseWheel>", self._on_mousewheel)
        self.win.bind("<Button-4>", self._on_mousewheel)
        self.win.bind("<Button-5>", self._on_mousewheel)

        self.photo: ImageTk.PhotoImage | None = None

    def is_open(self) -> bool:
        return bool(self.win.winfo_exists())

    def lift(self) -> None:
        cast(Any, self.win).lift()
        self.win.focus_force()

    def refresh(self, force: bool = False) -> None:
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
        cast(Any, self.canvas).create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.config(scrollregion=(0, 0, view_img.width, view_img.height))
        self.lbl_info.config(text=f"{path.name}  {view_img.width}x{view_img.height}")
        self._apply_window_size(view_img.width, view_img.height, force=force)

    def set_profile_name(self, name: str) -> None:
        self.profile_name = name

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        event_obj = cast(Any, event)
        if event_obj.num == 4:
            self.canvas.yview_scroll(-1, "units")
            return
        if event_obj.num == 5:
            self.canvas.yview_scroll(1, "units")
            return
        if not event_obj.delta:
            return
        if abs(event_obj.delta) < 120:
            step = -1 if event_obj.delta > 0 else 1
        else:
            step = int(-event_obj.delta / 120)
        if step != 0:
            self.canvas.yview_scroll(step, "units")

    def _apply_window_size(self, img_w: int, img_h: int, force: bool = False) -> None:
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

    def _close(self) -> None:
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
