import copy
import os
import pickle
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional, List

from loguru import logger

from keystroke_event_editor import KeystrokeEventEditor
from keystroke_event_importer import EventImporter
from keystroke_models import ProfileModel, EventModel
from keystroke_utils import WindowUtils


class ProfileFrame(ttk.Frame):
    def __init__(self, master, profile_name: str):
        super().__init__(master)
        self.profile_name = profile_name
        self.profile_label = ttk.Label(self, text="Profile name:")
        self.profile_entry = ttk.Entry(self)
        self.profile_label.grid(row=0, column=0, sticky=tk.E)
        self.profile_entry.grid(row=0, column=1, padx=1)
        self.profile_entry.insert(0, profile_name)


class EventListFrame(ttk.Frame):
    def __init__(self, master, profile: ProfileModel, save_callback: Callable):
        super().__init__(master)
        self.master = master
        self.profile = profile
        self.save_callback = save_callback
        self.event_rows: List[ttk.Frame] = []
        self.create_buttons()
        self.load_events()

    def create_buttons(self):
        ttk.Button(self, text="Add Event", command=self.add_event_row).grid(
            row=1, column=0, columnspan=2, pady=5, sticky="we"
        )
        ttk.Button(self, text="Import from", command=self.open_import_gui).grid(
            row=2, column=0, columnspan=2, pady=5, sticky="we"
        )

    def load_events(self):
        if self.profile.event_list:
            for idx, event in enumerate(self.profile.event_list):
                self.add_event_row(row_num=idx, event=event, resize=False)

    def add_event_row(self, row_num=None, event=None, resize=True):
        if row_num is None:
            row_num = len(self.event_rows)

        row_frame = ttk.Frame(self)
        row_frame.grid(row=row_num + 3, column=0, columnspan=2, padx=5, pady=2)

        entry = ttk.Entry(row_frame)
        entry.pack(side=tk.LEFT, padx=5)
        if event and hasattr(event, "event_name"):
            entry.insert(0, event.event_name)

        ttk.Button(
            row_frame,
            text="⚙️",
            command=lambda: self.open_event_settings(row_num, event),
        ).pack(side=tk.LEFT)
        ttk.Button(
            row_frame, text="📝", command=lambda: self.copy_event_row(event)
        ).pack(side=tk.LEFT)
        ttk.Button(
            row_frame,
            text="🗑️",
            command=lambda: self.remove_event_row(row_frame, row_num),
        ).pack(side=tk.LEFT)

        self.event_rows.append(row_frame)

        if resize:
            # Adjust the window size
            self.master.update_idletasks()
            self.adjust_window_height()

    def open_event_settings(self, row_num, event):
        KeystrokeEventEditor(
            self.master,
            row_num=row_num,
            save_callback=self.save_event_callback,
            event_function=lambda: event,
        )

    def save_event_callback(self, event: EventModel, is_edit: bool, row_num: int = 0):
        if is_edit and 0 <= row_num < len(self.profile.event_list):
            self.profile.event_list[row_num] = event
        else:
            self.profile.event_list.append(event)
        self.save_callback(check_profile_name=False)

    def copy_event_row(self, event: Optional[EventModel]):
        if event:
            try:
                new_event = copy.deepcopy(event)
                new_event.event_name = ""  # Clear the event name for the copy
                self.profile.event_list.append(new_event)
                self.add_event_row(event=new_event)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to copy event: {str(e)}")
        else:
            messagebox.showinfo("Info", "Only set events can be copied")

        # Adjust the window size after copying
        self.master.update_idletasks()
        # self.adjust_window_height()

    def remove_event_row(self, row_frame, row_num):
        if len(self.profile.event_list) < 2:
            messagebox.showinfo("Info", "There must be at least one event")
            return

        row_frame.destroy()
        self.event_rows.remove(row_frame)
        if 0 <= row_num < len(self.profile.event_list):
            self.profile.event_list.pop(row_num)
        self.save_callback()

        # Adjust the window size after removing
        self.master.update_idletasks()
        self.adjust_window_height(stretch=False)

    def open_import_gui(self):
        EventImporter(self.master, self.import_events)

    def import_events(self, event_list: List[EventModel]):
        self.profile.event_list.extend(event_list)
        for event in event_list:
            self.add_event_row(event=event)
        self.save_callback()

    def adjust_window_height(self, stretch=True):
        height = 29 if stretch else -29
        current_width = self.master.winfo_width()
        current_height = self.master.winfo_height()
        new_height = current_height + height
        logger.debug(
            f"current width x height: {self.master.winfo_width()} x {self.master.winfo_height()}"
        )
        self.master.update_idletasks()
        self.master.geometry(f"{current_width}x{new_height}")


class KeystrokeProfiles:
    def __init__(
        self,
        main_window: tk.Tk,
        profile_name: str,
        save_callback: Optional[Callable[[], None]],
    ):
        self.main_window = main_window
        self.profile_name = profile_name
        self.external_save_callback = save_callback
        self.profiles_dir = "profiles"

        self.settings_window = tk.Toplevel(main_window)
        self.settings_window.title("Settings")
        self.settings_window.transient(main_window)  # Set parent window
        self.settings_window.grab_set()  # Make the window modal
        self.settings_window.focus_force()
        self.settings_window.attributes("-topmost", True)
        self.settings_window.bind("<Escape>", self.close_settings)

        self.profile = self.load_profile()

        self.profile_frame = ProfileFrame(self.settings_window, profile_name)
        self.profile_frame.pack()

        self.event_list_frame = EventListFrame(
            self.settings_window, self.profile, self.save_profile
        )
        self.event_list_frame.pack()

        self.create_buttons()
        self.settings_window.update_idletasks()

        WindowUtils.center_window(self.settings_window)

    def create_buttons(self):
        button_frame = ttk.Frame(self.settings_window)
        button_frame.pack(side="bottom", pady=10, fill="x")

        ttk.Button(button_frame, text="OK", command=self.handle_ok_button).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(button_frame, text="Cancel", command=self.close_settings).pack(
            side=tk.LEFT, padx=5
        )

    def load_profile(self) -> ProfileModel:
        try:
            with open(f"{self.profiles_dir}/{self.profile_name}.pkl", "rb") as f:
                return pickle.load(f)
        except FileNotFoundError:
            return ProfileModel(name=self.profile_name, event_list=[])

    def save_profile(self, check_profile_name: bool = True):
        if len(self.profile.event_list) < 1:
            messagebox.showerror("Error", "At least one event must be set")
            raise ValueError("Empty event list")

        new_profile_name = self.profile_frame.profile_entry.get()
        if check_profile_name and not new_profile_name:
            messagebox.showerror("Error", "Enter the profile name to save")
            raise ValueError("Invalid profile name")

        if new_profile_name != self.profile_name:
            old_file = f"{self.profiles_dir}/{self.profile_name}.pkl"
            if os.path.exists(old_file):
                os.remove(old_file)
            self.profile_name = new_profile_name

        with open(f"{self.profiles_dir}/{self.profile_name}.pkl", "wb") as f:
            pickle.dump(self.profile, f)

    def handle_ok_button(self):
        try:
            self.save_event_names()
            self.save_profile()
            self.close_settings()
            if self.external_save_callback:
                self.external_save_callback(self.profile_name)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save profile: {e}")

    def save_event_names(self):
        for idx, row_frame in enumerate(self.event_list_frame.event_rows):
            entry = row_frame.winfo_children()[0]
            if idx < len(self.profile.event_list):
                self.profile.event_list[idx].event_name = entry.get()

    def close_settings(self, event=None):
        self.settings_window.grab_release()
        self.settings_window.destroy()
