import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Dict, Any

from loguru import logger
from i18n import dual_text_width, txt
from keystroke_profile_storage import load_profile, save_profile
from keystroke_utils import WindowUtils


class ModificationKeysWindow(tk.Toplevel):
    def __init__(self, master, profile_name):
        super().__init__(master)
        self.prof_name = profile_name
        self.prof_dir = Path("profiles")
        self.title(txt("Modification Keys", "수정 키 설정"))
        self.transient(master)
        self.grab_set()

        self.valid_keys = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        self.labels = ("Alt", "Ctrl", "Shift")
        self.rows = []  # (chk_var, cmb_var, prev_val, pass_var, cmb_widget)

        self._setup_ui()
        self._load_data()

        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_force()
        WindowUtils.center_window(self)

    def _setup_ui(self):
        for i, lbl in enumerate(self.labels):
            ttk.Label(self, text=lbl).grid(row=i, column=1, padx=5, pady=5)

            chk = tk.BooleanVar()
            ttk.Checkbutton(self, variable=chk).grid(row=i, column=2, padx=5)

            cmb_var = tk.StringVar(value="PressKey")
            cmb = ttk.Combobox(
                self, textvariable=cmb_var, values=["PressKey"], width=10
            )
            cmb.grid(row=i, column=3, padx=5)
            cmb.bind("<KeyPress>", lambda e, v=cmb_var, idx=i: self._on_key(e, v, idx))

            ttk.Label(self, text=txt("Pass", "패스")).grid(row=i, column=4, padx=5)

            pas = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                self, variable=pas, command=lambda idx=i: self._toggle_pass(idx)
            ).grid(row=i, column=5, padx=5)

            self.rows.append((chk, cmb_var, tk.StringVar(value="PressKey"), pas, cmb))

        ttk.Button(
            self,
            text=txt("Save (Enter)", "저장 (Enter)"),
            width=dual_text_width("Save (Enter)", "저장 (Enter)", padding=2, min_width=12),
            command=self.save,
        ).grid(
            row=len(self.labels), column=0, columnspan=6, pady=10
        )

    def _load_data(self):
        if not (
            (self.prof_dir / f"{self.prof_name}.json").exists()
            or (self.prof_dir / f"{self.prof_name}.pkl").exists()
        ):
            logger.warning(f"Profile '{self.prof_name}' missing.")
            return self.destroy()

        try:
            p = load_profile(self.prof_dir, self.prof_name, migrate=True)

            # Default initialization if missing
            if not getattr(p, "modification_keys", None):
                p.modification_keys = {
                    l.lower(): {"enabled": True, "value": "Pass", "pass": True}
                    for l in self.labels
                }
                save_profile(self.prof_dir, p, name=self.prof_name)

            for i, lbl in enumerate(self.labels):
                if d := p.modification_keys.get(lbl.lower()):
                    r = self.rows[i]
                    r[0].set(d["enabled"])
                    r[1].set(d["value"])
                    r[2].set(d["value"])
                    r[3].set(d["pass"])
                    if d["pass"]:
                        self._toggle_pass(i)
            logger.info(f"Loaded keys for '{self.prof_name}'")
        except Exception as e:
            logger.error(f"Load failed: {e}")

    def _on_key(self, event, var, idx):
        if (
            not self.rows[idx][3].get()
            and (char := event.char.upper()) in self.valid_keys
        ):
            var.set(char)
            return "break"

    def _toggle_pass(self, idx):
        _, cmb_var, prev, pas, cmb = self.rows[idx]
        if pas.get():
            prev.set(cmb_var.get())
            cmb_var.set("Pass")
            cmb.config(
                state="disabled"
            )  # 'readonly'보다 'disabled'가 명확하나 원본 의도 유지시 'readonly'
        else:
            cmb_var.set(prev.get())
            cmb.config(state="normal")

    def save(self):
        data = {
            lbl.lower(): {
                "enabled": r[0].get(),
                "value": "Pass" if r[3].get() else r[1].get(),
                "pass": r[3].get(),
            }
            for lbl, r in zip(self.labels, self.rows)
        }

        try:
            p = load_profile(self.prof_dir, self.prof_name, migrate=True)
            p.modification_keys = data
            save_profile(self.prof_dir, p, name=self.prof_name)
            logger.info(f"Saved keys for '{self.prof_name}'")
            self.destroy()
        except Exception as e:
            logger.error(f"Save failed: {e}")
