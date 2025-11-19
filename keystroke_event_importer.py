import pickle
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Optional

from loguru import logger

from keystroke_models import EventModel
from keystroke_utils import StateUtils


class EventImporter:
    def __init__(
        self,
        profiles_window: tk.Toplevel,
        confirm_callback: Optional[Callable[[list[EventModel]], None]] = None,
    ):
        self.win = tk.Toplevel(profiles_window)
        self.win.title("Import events")
        self.win.focus_force()
        self.win.attributes("-topmost", True)
        self.win.grab_set()

        self.profile_dir = Path("profiles")
        self.confirm_cb = confirm_callback
        self.checkboxes = []
        self.current_profile_data = None

        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", self.close)

        self.create_ui()
        self.load_profiles()
        self.load_pos()

    def create_ui(self):
        # Profile Selection
        f_prof = ttk.Frame(self.win)
        f_prof.pack(pady=10)
        ttk.Label(f_prof, text="Profile:").pack(side="left", padx=5)
        self.cb_prof = ttk.Combobox(f_prof, state="readonly")
        self.cb_prof.bind("<<ComboboxSelected>>", self.load_events)
        self.cb_prof.pack(side="left", padx=5)

        # Events Area
        self.f_events = ttk.LabelFrame(self.win, text="Events")
        self.f_events.pack(pady=20, padx=20, fill="both", expand=True)

        # Scrollable Canvas for Events (Optional but good for many events)
        # For simplicity, keeping it packed directly as requested, but using a canvas is better for scalability.
        # Here we stick to the original structure but cleaner.

        # Buttons
        f_btn = ttk.Frame(self.win)
        f_btn.pack(side="bottom", pady=10, fill="x")
        ttk.Button(f_btn, text="OK", command=self.on_ok).pack(side="left", padx=5)
        ttk.Button(f_btn, text="Cancel", command=self.close).pack(side="left", padx=5)
        ttk.Button(f_btn, text="Select/Deselect All", command=self.toggle_all).pack(
            side="right", padx=5
        )

    def load_profiles(self):
        self.profile_dir.mkdir(exist_ok=True)
        names = sorted([p.stem for p in self.profile_dir.glob("*.pkl")])
        if "Quick" in names:  # Assuming 'Quick' or '_Quick' handling
            names.remove("Quick")
            names.insert(0, "Quick")

        self.cb_prof["values"] = names
        if names:
            self.cb_prof.current(0)
            self.load_events()

    def load_events(self, event=None):
        prof_name = self.cb_prof.get()
        try:
            with open(self.profile_dir / f"{prof_name}.pkl", "rb") as f:
                self.current_profile_data = pickle.load(f)
        except Exception as e:
            logger.error(f"Failed to load profile {prof_name}: {e}")
            self.current_profile_data = None

        for w in self.f_events.winfo_children():
            w.destroy()
        self.checkboxes.clear()

        if self.current_profile_data and self.current_profile_data.event_list:
            for i, evt in enumerate(self.current_profile_data.event_list):
                self._add_event_row(i, evt)

    def _add_event_row(self, idx, evt):
        var = tk.IntVar()
        ttk.Checkbutton(self.f_events, text=f"{idx + 1}", variable=var).grid(
            row=idx, column=0, sticky="w", padx=10
        )

        e_name = ttk.Entry(self.f_events)
        e_name.insert(0, evt.event_name)
        e_name.config(state="readonly")
        e_name.grid(row=idx, column=1, padx=10)

        e_key = ttk.Entry(self.f_events, width=5)
        e_key.insert(0, evt.key_to_enter or "")
        e_key.config(state="readonly")
        e_key.grid(row=idx, column=2, padx=5)

        self.checkboxes.append(var)

    def toggle_all(self):
        target = 1 if any(v.get() == 0 for v in self.checkboxes) else 0
        for v in self.checkboxes:
            v.set(target)

    def on_ok(self):
        if not self.current_profile_data:
            return

        selected = [
            self.current_profile_data.event_list[i]
            for i, var in enumerate(self.checkboxes)
            if var.get()
        ]

        if selected and self.confirm_cb:
            self.confirm_cb(selected)
            logger.info(f"Imported {len(selected)} events from '{self.cb_prof.get()}'")

        self.close()

    def close(self, event=None):
        StateUtils.save_main_app_state(
            importer_pos=f"{self.win.winfo_x()}/{self.win.winfo_y()}"
        )
        self.win.destroy()

    def load_pos(self):
        if pos := StateUtils.load_main_app_state().get("importer_pos"):
            self.win.geometry(f"+{pos.split('/')[0]}+{pos.split('/')[1]}")
