import tkinter as tk
from typing import Protocol, cast


class WindowLike(Protocol):
    def update_idletasks(self) -> None: ...
    def winfo_screenwidth(self) -> int: ...
    def winfo_screenheight(self) -> int: ...
    def winfo_width(self) -> int: ...
    def winfo_height(self) -> int: ...
    def geometry(self, _new_geometry: str) -> object: ...


class WindowUtils:
    @staticmethod
    def center_window(win: object) -> None:
        window = cast(WindowLike, win)
        window.update_idletasks()
        x = (window.winfo_screenwidth() - window.winfo_width()) // 2
        y = (window.winfo_screenheight() - window.winfo_height()) // 2
        window.geometry(f"+{x}+{y}")

    @staticmethod
    def can_own_modal_grab(widget: object | None) -> bool:
        return isinstance(widget, (tk.Tk, tk.Toplevel))

    @staticmethod
    def restore_modal_grab(parent: object | None) -> None:
        """Re-apply modal grab to a parent window after a child dialog closes."""
        if not WindowUtils.can_own_modal_grab(parent):
            return
        window = cast(tk.Misc, parent)
        try:
            if window.winfo_exists():
                window.grab_set()
        except tk.TclError:
            pass
