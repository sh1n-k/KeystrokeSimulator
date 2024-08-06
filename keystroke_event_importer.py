import os
import pickle
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from keystroke_models import EventModel
from keystroke_utils import WindowUtils


class EventImporter:
    def __init__(
        self,
        parent_window: tk.Toplevel,
        confirm_callback: Optional[Callable[[list[EventModel]], None]] = None,
    ):
        self.master = tk.Toplevel(parent_window)
        self.master.title("Load from")
        self.master.focus_force()
        self.master.attributes("-topmost", True)
        self.master.grab_set()
        self.profile_dir = "profiles"
        self.selected_profile = None
        self.confirm_callback = confirm_callback
        self.checkboxes = []
        self.current_profile = None

        # Get the font settings from the parent window
        parent_font_size = 16

        self.master.protocol("WM_DELETE_WINDOW", self.cancel_button_clicked)
        self.master.bind("<Escape>", self.cancel_button_clicked)

        self.create_profile_frame(parent_font_size)
        self.create_event_frame(parent_font_size)
        self.create_button_frame(parent_font_size)
        self.load_profiles()

        WindowUtils.center_window(self.master)

    def create_profile_frame(self, parent_font_size):
        self.profile_frame = ttk.Frame(self.master)
        self.profile_frame.pack(pady=10)

        self.profile_label = ttk.Entry(
            self.profile_frame, font=("Arial", parent_font_size)
        )
        self.profile_label.insert(0, "Profile:")
        self.profile_label.config(state="readonly")
        self.profile_label.pack(side="left", padx=5)

        self.profile_combobox = ttk.Combobox(
            self.profile_frame, font=("Arial", parent_font_size)
        )
        self.profile_combobox.bind("<<ComboboxSelected>>", self.load_events)
        self.profile_combobox.config(state="readonly")
        self.profile_combobox.pack(side="left", padx=5)

    def create_event_frame(self, parent_font_size):
        self.event_frame = ttk.LabelFrame(self.master, text="Events")
        self.event_frame.pack(pady=20, padx=20)

    def create_button_frame(self, parent_font_size):
        button_frame = ttk.Frame(self.master)
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
        for i, var in enumerate(self.checkboxes):
            if var.get() == 1:
                profile_name = self.profile_combobox.get()
                profile_model = self.get_profile_model(profile_name)
                if profile_model and profile_model.event_list:
                    selected_events.append(profile_model.event_list[i])

        if not selected_events:
            return

        if self.confirm_callback:
            self.confirm_callback(selected_events)

        self.master.destroy()

    def cancel_button_clicked(self, event=None):
        self.master.destroy()

    def select_button_clicked(self):
        if any(var.get() == 0 for var in self.checkboxes):
            # If any checkbox is unchecked, select all
            self.select_all()

        elif all(var.get() == 1 for var in self.checkboxes):
            # If all checkboxes are checked, deselect all
            self.deselect_all()

        else:
            # If some checkboxes are checked and some are not, select all
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
        entry_status = ttk.Entry(self.event_frame, width=1)
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

        self.checkboxes.append(checkbox_var)  # Store the checkbox variable

    def checkbox_clicked(self, event_model, entry, entry_status, checkbox_var):
        if checkbox_var.get():
            entry.insert(0, event_model.event_name)
            entry_status.insert(0, event_model.key_to_enter or "")
        else:
            entry.delete(0, tk.END)
            entry_status.delete(0, tk.END)
