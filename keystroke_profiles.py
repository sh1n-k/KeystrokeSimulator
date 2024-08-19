import copy
import os
import pickle
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional, List

from keystroke_event_editor import KeystrokeEventEditor
from keystroke_event_importer import EventImporter
from keystroke_models import ProfileModel, EventModel
from keystroke_utils import WindowUtils, StateUtils


class ProfileFrame(ttk.Frame):
    def __init__(self, master, profile_name: str):
        super().__init__(master)
        self.profile_name = profile_name
        self.profile_label = ttk.Label(self, text="Profile Name: ")
        self.profile_entry = ttk.Entry(self)
        self.profile_label.grid(row=0, column=0, sticky=tk.E)
        self.profile_entry.grid(row=0, column=1, padx=1)
        self.profile_entry.insert(0, profile_name)


class EventListFrame(ttk.Frame):
    def __init__(self, settings_window, profile: ProfileModel, save_callback: Callable):
        super().__init__(settings_window)
        self.settings_window = settings_window
        self.profile = profile
        self.save_callback = save_callback
        self.event_rows: List[ttk.Frame] = []
        self.create_buttons()
        self.load_events()

    def create_buttons(self):
        ttk.Button(self, text="Add Event", command=self.add_event_row).grid(
            row=1, column=0, columnspan=1, pady=5, sticky="we"
        )
        ttk.Button(self, text="Import From", command=self.open_importer).grid(
            row=1, column=1, columnspan=1, pady=5, sticky="we"
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

        ttk.Label(row_frame, text=row_num + 1, width=2, anchor="center").pack(
            side=tk.LEFT
        )
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

    def open_event_settings(self, row_num, event):
        KeystrokeEventEditor(
            self.settings_window,
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
                self.save_callback()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to copy event: {str(e)}")
        else:
            messagebox.showinfo("Info", "Only set events can be copied")

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
        self.settings_window.update_idletasks()

    def open_importer(self):
        EventImporter(self.settings_window, self.import_events)

    def import_events(self, event_list: List[EventModel]):
        self.profile.event_list.extend(event_list)
        for event in event_list:
            self.add_event_row(event=event)
        self.save_callback()


class KeystrokeProfiles:
    def __init__(
        self,
        main_window: tk.Tk,
        profile_name: str,
        save_callback: Optional[Callable[[str], None]] = None,
    ):
        self.main_window = main_window
        self.profile_name = profile_name
        self.external_save_callback = save_callback
        self.profiles_dir = "profiles"

        self.settings_window = self._create_settings_window()
        self.profile = self._load_profile()

        self.profile_frame = ProfileFrame(self.settings_window, profile_name)
        self.event_list_frame = EventListFrame(
            self.settings_window, self.profile, self._save_profile
        )

        self._pack_frames()
        self._create_buttons()
        self._load_latest_position()

        self.settings_window.protocol("WM_DELETE_WINDOW", self._close_settings)

    def _create_settings_window(self) -> tk.Toplevel:
        window = tk.Toplevel(self.main_window)
        window.title("Profile Manager")
        window.transient(self.main_window)
        window.grab_set()
        window.focus_force()
        # window.attributes("-topmost", True)
        window.bind("<Escape>", self._close_settings)
        return window

    def _load_profile(self) -> ProfileModel:
        try:
            with open(f"{self.profiles_dir}/{self.profile_name}.pkl", "rb") as f:
                return pickle.load(f)
        except FileNotFoundError:
            return ProfileModel(name=self.profile_name, event_list=[])

    def _pack_frames(self):
        self.profile_frame.pack()
        self.event_list_frame.pack()

    def _create_buttons(self):
        button_frame = ttk.Frame(self.settings_window, style="success.TFrame")
        button_frame.pack(side="bottom", anchor="e", pady=10, fill="both")

        ttk.Button(
            button_frame, text="Save Names", command=self._handle_ok_button
        ).pack(side=tk.LEFT, anchor="center", padx=5)

    def _save_profile(
        self, check_profile_name: bool = True, reload_event_frame: bool = True
    ):
        if not self.profile.event_list:
            raise ValueError("At least one event must be set")

        new_profile_name = self.profile_frame.profile_entry.get()
        if check_profile_name and not new_profile_name:
            raise ValueError("Enter the profile name to save")

        if new_profile_name != self.profile_name:
            self._remove_old_profile()
            self.profile_name = new_profile_name

        with open(f"{self.profiles_dir}/{self.profile_name}.pkl", "wb") as f:
            pickle.dump(self.profile, f)

        if reload_event_frame:
            self._save_event_names()
            self.event_list_frame.destroy()
            self.event_list_frame = EventListFrame(
                self.settings_window, self.profile, self._save_profile
            )
            self.event_list_frame.pack()

    def _remove_old_profile(self):
        old_file = f"{self.profiles_dir}/{self.profile_name}.pkl"
        if os.path.exists(old_file):
            os.remove(old_file)

    def _handle_ok_button(self):
        try:
            self._save_event_names()
            self._save_profile(reload_event_frame=False)
            self._close_settings()
            if self.external_save_callback:
                self.external_save_callback(self.profile_name)
        except ValueError as e:
            messagebox.showerror("Error", str(e))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save profile: {e}")

    def _save_event_names(self):
        for idx, row_frame in enumerate(self.event_list_frame.event_rows):
            entry = row_frame.winfo_children()[1]
            if idx < len(self.profile.event_list):
                self.profile.event_list[idx].event_name = entry.get()

    def _save_latest_position(self):
        StateUtils.save_main_app_state(
            profile_position=f"{self.settings_window.winfo_x()}/{self.settings_window.winfo_y()}",
        )

    def _load_latest_position(self):
        state = StateUtils.load_main_app_state()
        if not state or "profile_position" not in state:
            WindowUtils.center_window(self.settings_window)
            return
        else:
            x, y = state["profile_position"].split("/")
            self.settings_window.geometry(f"+{x}+{y}")

    def _close_settings(self, event=None):
        self._save_latest_position()
        self.settings_window.grab_release()
        self.settings_window.destroy()
