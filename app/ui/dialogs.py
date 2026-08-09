"""In-app modal dialogs (avoid OS-native messagebox where UX consistency matters)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, cast

from app.ui import theme
from app.utils.i18n import dual_text_width, txt
from app.utils.window_state import WindowUtils


class ConfirmDialog(tk.Toplevel):
    """Simple Cancel/OK confirmation dialog styled like the main app."""

    def __init__(
        self,
        master: tk.Misc | None,
        *,
        title: str,
        message: str,
        ok_text: str | None = None,
        cancel_text: str | None = None,
    ) -> None:
        super().__init__(master)
        self.result = False
        self.title(title)
        if master is not None:
            cast(Any, self).transient(master)
        self.grab_set()
        try:
            self.configure(bg=theme.SURFACE_PAPER)
        except tk.TclError:
            pass
        theme.install_styles(self)
        self.resizable(False, False)

        f = theme.fonts()
        body = tk.Frame(self, bg=theme.SURFACE_PAPER, padx=theme.SPACE_3, pady=theme.SPACE_3)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text=message,
            bg=theme.SURFACE_PAPER,
            fg=theme.INK_PRIMARY,
            font=f["body"],
            justify="left",
            wraplength=360,
            anchor="w",
        ).pack(fill="x", pady=(0, theme.SPACE_3))

        btn_row = tk.Frame(body, bg=theme.SURFACE_PAPER)
        btn_row.pack(fill="x")

        cancel_label = cancel_text or txt("Cancel", "취소")
        ok_label = ok_text or txt("OK", "확인")

        # Cancel on the left, OK on the right (matches common confirm UX).
        cancel_btn = ttk.Button(
            btn_row,
            text=cancel_label,
            width=dual_text_width(cancel_label, cancel_label, padding=2, min_width=8),
            command=self._on_cancel,
        )
        cancel_btn.pack(side="left")
        ok_btn = ttk.Button(
            btn_row,
            text=ok_label,
            width=dual_text_width(ok_label, ok_label, padding=2, min_width=8),
            command=self._on_ok,
            style="Accent.TButton",
        )
        ok_btn.pack(side="right")

        self.bind("<Escape>", lambda _e: self._on_cancel())
        self.bind("<Return>", lambda _e: self._on_ok())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.focus_force()
        WindowUtils.center_window(self)
        # Modal wait until closed.
        try:
            if master is not None:
                cast(Any, master).wait_window(self)
            else:
                self.wait_window(self)
        except tk.TclError:
            pass

    def _on_ok(self) -> None:
        self.result = True
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = False
        self.destroy()


def ask_confirm(
    master: tk.Misc | None,
    *,
    title: str,
    message: str,
    ok_text: str | None = None,
    cancel_text: str | None = None,
) -> bool:
    dialog = ConfirmDialog(
        master,
        title=title,
        message=message,
        ok_text=ok_text,
        cancel_text=cancel_text,
    )
    return bool(dialog.result)
