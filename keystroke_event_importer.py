import os
import pickle
import tkinter as tk
from tkinter import ttk
from tkinter.ttk import Scrollbar
from typing import Callable, Optional

from loguru import logger

from keystroke_models import EventModel
from keystroke_utils import WindowUtils, StateUtils


class EventImporter:
    def __init__(
        self,
        profiles_window: tk.Toplevel,
        confirm_callback: Optional[Callable[[list[EventModel]], None]] = None,
    ):
        self.event_importer = tk.Toplevel(profiles_window)
        self.event_importer.title("Load from")
        self.event_importer.focus_force()
        self.event_importer.attributes("-topmost", True)
        self.event_importer.grab_set()
        self.profile_dir = "profiles"
        self.selected_profile = None
        self.confirm_callback = confirm_callback
        self.checkboxes = []
        self.current_profile = None

        self.event_importer.protocol("WM_DELETE_WINDOW", self.cancel_button_clicked)
        self.event_importer.bind("<Escape>", self.cancel_button_clicked)

        self.create_profile_frame()
        self.create_event_frame()
        self.create_button_frame()

        self.load_profiles()
        self.load_latest_position()

    def create_profile_frame(self):
        self.profile_frame = ttk.Frame(self.event_importer)
        self.profile_frame.pack(pady=10)

        self.profile_label = ttk.Entry(self.profile_frame)
        self.profile_label.insert(0, "Profile:")
        self.profile_label.config(state="readonly")
        self.profile_label.pack(side="left", padx=5)

        self.profile_combobox = ttk.Combobox(self.profile_frame)
        self.profile_combobox.bind("<<ComboboxSelected>>", self.load_events)
        self.profile_combobox.config(state="readonly")
        self.profile_combobox.pack(side="left", padx=5)

    def create_event_frame(self):
        self.event_frame = ttk.LabelFrame(self.event_importer, text="Events")
        self.event_frame.pack(pady=20, padx=20, fill="both", expand=True)

    def create_button_frame(self):
        button_frame = ttk.Frame(self.event_importer)
        button_frame.pack(side="bottom", pady=10, fill="x")

        ok_button = ttk.Button(
            button_frame,
            text="OK",
            command=self.ok_button_clicked,
        )
        cancel_button = ttk.Button(
            button_frame,
            text="Cancel",
            command=self.cancel_button_clicked,
        )
        select_button = ttk.Button(
            button_frame,
            text="Select/Deselect All",
            command=self.select_button_clicked,
        )

        ok_button.pack(side="left", padx=5)
        cancel_button.pack(side="left", padx=5)
        select_button.pack(side="right", padx=5)

    def ok_button_clicked(self):
        selected_events = []
        profile_name = self.profile_combobox.get()
        for i, var in enumerate(self.checkboxes):
            if var.get() == 1:
                profile_model = self.get_profile_model(profile_name)
                if profile_model and profile_model.event_list:
                    selected_events.append(profile_model.event_list[i])

        if not selected_events:
            return

        if self.confirm_callback:
            self.confirm_callback(selected_events)
            logger.info(
                f"{len(selected_events)} events selected in profile '{profile_name}'"
            )

        self.event_importer.destroy()

    def save_latest_position(self):
        StateUtils.save_main_app_state(
            importer_position=f"{self.event_importer.winfo_x()}/{self.event_importer.winfo_y()}",
        )

    def load_latest_position(self):
        state = StateUtils.load_main_app_state()
        if state and "importer_position" in state:
            x, y = state["importer_position"].split("/")
            self.event_importer.geometry(f"+{x}+{y}")
            self.event_importer.update_idletasks()

    def cancel_button_clicked(self, event=None):
        self.save_latest_position()
        self.event_importer.destroy()

    def select_button_clicked(self):
        if any(var.get() == 0 for var in self.checkboxes):
            self.select_all()

        elif all(var.get() == 1 for var in self.checkboxes):
            self.deselect_all()

        else:
            self.select_all()

    def select_all(self):
        for var in self.checkboxes:
            var.set(1)

    def deselect_all(self):
        for var in self.checkboxes:
            var.set(0)

    def load_profiles(self):
        profile_names = self.get_profile_names()

        if "_Quick" in profile_names:
            profile_names.insert(0, profile_names.pop(profile_names.index("_Quick")))

        self.profile_combobox["values"] = profile_names

        if profile_names:
            self.profile_combobox.current(0)
            self.load_events(None)

    def get_profile_names(self):
        return [
            os.path.splitext(f)[0]
            for f in os.listdir(self.profile_dir)
            if f.endswith(".pkl")
        ]

    def load_events(self, event):
        profile_name = self.profile_combobox.get()
        profile_model = self.get_profile_model(profile_name)

        # Clear existing event widgets
        for widget in self.event_frame.winfo_children():
            widget.destroy()
        self.checkboxes = []

        if profile_model and profile_model.event_list:
            for idx, event_model in enumerate(profile_model.event_list):
                self.create_event_widget(idx, event_model)

        self.current_profile = profile_model

    def get_profile_model(self, profile_name):
        try:
            with open(f"{self.profile_dir}/{profile_name}.pkl", "rb") as f:
                return pickle.load(f)
        except Exception as e:
            print(f"Failed to load profile: {e}")
            return None

    def create_event_widget(self, row, event_model):
        entry = ttk.Entry(self.event_frame)
        entry.insert(0, event_model.event_name)
        entry.config(state="readonly")
        entry_status = ttk.Entry(self.event_frame, width=2)
        entry_status.insert(0, event_model.key_to_enter or "")
        entry_status.config(state="readonly")
        checkbox_var = tk.IntVar()
        checkbox = ttk.Checkbutton(
            self.event_frame,
            state="",
            text=f"{row + 1}",
            variable=checkbox_var,
            command=lambda: self.checkbox_clicked(
                event_model, entry, entry_status, checkbox_var
            ),
        )
        checkbox.grid(row=row, column=0, sticky="w", padx=10)
        entry.grid(row=row, column=1, padx=10)
        entry_status.grid(row=row, column=2, padx=5)

        self.checkboxes.append(checkbox_var)

    def checkbox_clicked(self, event_model, entry, entry_status, checkbox_var):
        if checkbox_var.get():
            entry.insert(0, event_model.event_name)
            entry_status.insert(0, event_model.key_to_enter or "")
        else:
            entry.delete(0, tk.END)
            entry_status.delete(0, tk.END)
