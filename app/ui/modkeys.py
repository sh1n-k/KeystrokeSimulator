from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import ClassVar, TypeAlias

from loguru import logger
from app.core.models import ModificationKeys
from app.utils.i18n import dual_text_width, txt
from app.storage.profile_storage import load_profile, save_profile
from app.utils.system import WindowUtils
from app.ui import theme

ModKeyRow: TypeAlias = tuple[
    tk.BooleanVar,
    tk.StringVar,
    tk.StringVar,
    tk.BooleanVar,
    ttk.Combobox,
    tk.Frame,
    tk.Label,
    tk.Label,
    tk.Label,
]


class ModificationKeysWindow(tk.Toplevel):
    def __init__(
        self, master: tk.Tk | tk.Toplevel | None, profile_name: str
    ) -> None:
        super().__init__(master)
        self.prof_name = profile_name
        self.prof_dir = Path("profiles")
        self.title(txt("Modification Keys", "수정 키 설정"))
        if master is not None:
            self.transient(master)
        self.grab_set()
        try:
            self.configure(bg=theme.SURFACE_PAPER)
        except tk.TclError:
            pass
        theme.install_styles(self)

        self.valid_keys: set[str] = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        self.labels: tuple[str, ...] = ("Alt", "Ctrl", "Shift")
        self.rows: list[ModKeyRow] = []

        self._setup_ui()
        self._load_data()

        self.bind("<Return>", lambda _event: self.save())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.focus_force()
        WindowUtils.center_window(self)

    # SOT icon vocabulary for modifier keycaps.
    _KEYCAPS: ClassVar[dict[str, str]] = {"Alt": "⎇", "Ctrl": "⌃", "Shift": "⇧"}

    def _build_context_bar(self) -> tk.Frame:
        f = theme.fonts()
        bar = tk.Frame(
            self,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_3,
            pady=theme.SPACE_2,
        )
        tk.Label(
            bar,
            text=txt("Modifier Keys", "수정 키"),
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_PRIMARY,
            font=f["heading"],
        ).pack(side="left")
        tk.Label(
            bar,
            text=self.prof_name,
            bg=theme.SURFACE_PANEL,
            fg=theme.INK_MUTED,
            font=f["caption"],
        ).pack(side="left", padx=(theme.SPACE_3, 0))
        return bar

    def _setup_ui(self) -> None:
        # Top ContextBar — keeps profile context visible across the dialog.
        bar = self._build_context_bar()
        bar.grid(row=0, column=0, columnspan=7, sticky="we")
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).grid(
            row=1, column=0, columnspan=7, sticky="we"
        )

        # Each modifier becomes its own card with a keycap glyph on the left.
        f = theme.fonts()
        for i, lbl in enumerate(self.labels):
            card = tk.Frame(
                self,
                bg=theme.SURFACE_CANVAS,
                highlightthickness=1,
                highlightbackground=theme.SURFACE_DIVIDER,
            )
            card.grid(
                row=i + 2,
                column=0,
                columnspan=6,
                padx=theme.SPACE_3,
                pady=theme.SPACE_1,
                sticky="we",
            )
            keycap = self._KEYCAPS.get(lbl, "")
            # Big monospace keycap glyph
            lbl_cap = tk.Label(
                card,
                text=keycap,
                width=2,
                bg=theme.SURFACE_SUNKEN,
                fg=theme.INK_PRIMARY,
                font=f["display"],
                padx=theme.SPACE_2,
                pady=theme.SPACE_1,
            )
            lbl_cap.grid(row=0, column=0, padx=(theme.SPACE_2, theme.SPACE_1), pady=theme.SPACE_2)
            lbl_name = tk.Label(
                card,
                text=lbl,
                width=8,
                bg=theme.SURFACE_CANVAS,
                fg=theme.INK_PRIMARY,
                font=f["body_bold"],
            )
            lbl_name.grid(row=0, column=1, padx=theme.SPACE_1, pady=theme.SPACE_2)

            chk = tk.BooleanVar()
            ttk.Checkbutton(card, variable=chk).grid(
                row=0, column=2, padx=theme.SPACE_1
            )

            cmb_var = tk.StringVar(value="PressKey")
            cmb = ttk.Combobox(
                card, textvariable=cmb_var, values=["PressKey"], width=10
            )
            cmb.grid(row=0, column=3, padx=theme.SPACE_1)
            cmb.bind(
                "<KeyPress>", lambda e, v=cmb_var, idx=i: self._on_key(e, v, idx)
            )

            tk.Label(
                card,
                text=txt("Pass through", "패스"),
                bg=theme.SURFACE_CANVAS,
                fg=theme.INK_MUTED,
                font=f["caption"],
            ).grid(row=0, column=4, padx=(theme.SPACE_3, theme.SPACE_1))

            pas = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                card, variable=pas, command=lambda idx=i: self._toggle_pass(idx)
            ).grid(row=0, column=5, padx=theme.SPACE_1)

            # "PASS" chip surfaces alongside the keycap when Pass mode is on
            # so users can tell at a glance which keys are pass-through.
            chip = tk.Label(
                card,
                text=txt("PASS", "패스"),
                bg=theme.SURFACE_CANVAS,
                fg=theme.SURFACE_CANVAS,
                font=f["caption"],
                padx=theme.SPACE_2,
                pady=0,
            )
            chip.grid(row=0, column=6, padx=(theme.SPACE_2, theme.SPACE_3))

            self.rows.append(
                (
                    chk,
                    cmb_var,
                    tk.StringVar(value="PressKey"),
                    pas,
                    cmb,
                    card,
                    lbl_cap,
                    lbl_name,
                    chip,
                )
            )

        # Bottom RunDock — separator + panel-tone band hosting Save.
        tk.Frame(self, bg=theme.SURFACE_DIVIDER, height=1).grid(
            row=len(self.labels) + 2,
            column=0,
            columnspan=7,
            sticky="we",
            pady=(theme.SPACE_2, 0),
        )
        dock = tk.Frame(
            self,
            bg=theme.SURFACE_PANEL,
            padx=theme.SPACE_3,
            pady=theme.SPACE_2,
        )
        dock.grid(
            row=len(self.labels) + 3,
            column=0,
            columnspan=7,
            sticky="we",
        )
        ttk.Button(
            dock,
            text=txt("Save (Enter)", "저장 (Enter)"),
            width=dual_text_width(
                "Save (Enter)", "저장 (Enter)", padding=2, min_width=12
            ),
            command=self.save,
            style="Accent.TButton",
        ).pack(side="right")

    def _load_data(self) -> None:
        if not (self.prof_dir / f"{self.prof_name}.json").exists():
            logger.warning(f"Profile '{self.prof_name}' missing.")
            return self.destroy()

        try:
            p = load_profile(self.prof_dir, self.prof_name, migrate=True)

            # Default initialization if missing
            if not getattr(p, "modification_keys", None):
                p.modification_keys = {
                    label.lower(): {"enabled": True, "value": "Pass", "pass": True}
                    for label in self.labels
                }
                save_profile(self.prof_dir, p, name=self.prof_name)

            mod_keys = p.modification_keys or {}
            for i, lbl in enumerate(self.labels):
                if d := mod_keys.get(lbl.lower()):
                    r = self.rows[i]
                    value = str(d.get("value", "PressKey"))
                    enabled = bool(d.get("enabled", True))
                    pass_through = bool(d.get("pass", False))
                    r[0].set(enabled)
                    r[1].set(value)
                    r[2].set(value)
                    r[3].set(pass_through)
                    if pass_through:
                        self._toggle_pass(i)
            logger.info(f"Loaded keys for '{self.prof_name}'")
        except Exception as e:
            logger.error(f"Load failed: {e}")

    def _on_key(
        self, event: tk.Event[tk.Misc], var: tk.StringVar, idx: int
    ) -> str | None:
        if (
            not self.rows[idx][3].get()
            and (char := event.char.upper()) in self.valid_keys
        ):
            var.set(char)
            return "break"

    def _toggle_pass(self, idx: int) -> None:
        row = self.rows[idx]
        _, cmb_var, prev, pas, cmb = row[:5]
        card, lbl_cap, lbl_name, chip = row[5:9]
        if pas.get():
            prev.set(cmb_var.get())
            cmb_var.set("Pass")
            cmb.config(
                state="disabled"
            )  # 'readonly'보다 'disabled'가 명확하나 원본 의도 유지시 'readonly'
            # Dim card chrome and surface the PASS chip.
            card.config(
                bg=theme.SURFACE_PANEL, highlightbackground=theme.SURFACE_DIVIDER
            )
            lbl_cap.config(fg=theme.INK_MUTED, bg=theme.SURFACE_SUNKEN)
            lbl_name.config(fg=theme.INK_MUTED, bg=theme.SURFACE_PANEL)
            chip.config(bg=theme.SIGNAL_TINT, fg=theme.SIGNAL_BASE)
        else:
            cmb_var.set(prev.get())
            cmb.config(state="normal")
            card.config(
                bg=theme.SURFACE_CANVAS, highlightbackground=theme.SURFACE_DIVIDER
            )
            lbl_cap.config(fg=theme.INK_PRIMARY, bg=theme.SURFACE_SUNKEN)
            lbl_name.config(fg=theme.INK_PRIMARY, bg=theme.SURFACE_CANVAS)
            chip.config(bg=theme.SURFACE_CANVAS, fg=theme.SURFACE_CANVAS)

    def save(self) -> None:
        data: ModificationKeys = {
            lbl.lower(): {
                "enabled": r[0].get(),
                "value": "Pass" if r[3].get() else r[1].get(),
                "pass": r[3].get(),
            }
            for lbl, r in zip(self.labels, self.rows, strict=True)
        }

        try:
            p = load_profile(self.prof_dir, self.prof_name, migrate=True)
            p.modification_keys = data
            save_profile(self.prof_dir, p, name=self.prof_name)
            logger.info(f"Saved keys for '{self.prof_name}'")
            self.destroy()
        except Exception as e:
            logger.error(f"Save failed: {e}")
