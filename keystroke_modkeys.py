import tkinter as tk
from tkinter import ttk
import pickle
import os
from typing import Dict, Any

from loguru import logger

from keystroke_utils import WindowUtils
from keystroke_models import ProfileModel


class ModificationKeysWindow(tk.Toplevel):
    def __init__(self, master, profile_name):
        super().__init__(master)
        self.master = master
        self.profile_name = profile_name
        self.profiles_dir = "profiles"
        self.title("Modification Keys")
        self.transient(master)
        self.grab_set()
        self.focus_force()

        self.valid_keys = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        self.labels = ("Alt", "Ctrl", "Shift")
        self.rows = []

        self.create_widgets()
        self.load_profile()
        WindowUtils.center_window(self)

    def create_widgets(self):
        for idx, label in enumerate(self.labels):
            self.create_row(idx, label)

        save_button = ttk.Button(self, text="Save(Enter)", command=self.save)
        save_button.grid(row=len(self.labels), column=0, columnspan=6, pady=10)

        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())

    def create_row(self, idx: int, label: str):
        ttk.Label(self, text=label).grid(row=idx, column=1, padx=5, pady=5)

        chk_var = tk.BooleanVar()
        ttk.Checkbutton(self, variable=chk_var).grid(row=idx, column=2, padx=5, pady=5)

        cmb_var = tk.StringVar(value="PressKey")
        cmb = ttk.Combobox(self, textvariable=cmb_var, values=["PressKey"], width=10)
        cmb.grid(row=idx, column=3, padx=5, pady=5)
        cmb.bind(
            "<KeyPress>", lambda e, v=cmb_var, i=idx: self.update_combobox(e, v, i)
        )

        prev_value_var = tk.StringVar(value="PressKey")

        ttk.Label(self, text="Pass").grid(row=idx, column=4, padx=5, pady=5)

        pass_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self,
            variable=pass_var,
            command=lambda v=cmb_var, p=pass_var, i=idx: self.toggle_pass(v, p, i),
        ).grid(row=idx, column=5, padx=5, pady=5)

        self.rows.append((chk_var, cmb_var, prev_value_var, pass_var))

    def load_profile(self):
        profile_path = os.path.join(self.profiles_dir, f"{self.profile_name}.pkl")
        if not os.path.exists(profile_path):
            logger.warning(
                f"Profile '{self.profile_name}' does not exist. This window should not have been opened."
            )
            self.destroy()
            return

        try:
            with open(profile_path, "rb") as f:
                profile = pickle.load(f)

            mod_keys = getattr(profile, "modification_keys", None)

            if mod_keys is None:
                logger.info(
                    f"No modification keys found for profile '{self.profile_name}'. Creating defaults."
                )
                mod_keys = {
                    label.lower(): {"enabled": True, "value": "Pass", "pass": True}
                    for label in self.labels
                }
                profile.modification_keys = mod_keys
                with open(profile_path, "wb") as f:
                    pickle.dump(profile, f)
                logger.info(f"Saved default mod keys for '{self.profile_name}'")

            self.display_saved_values(mod_keys)
            logger.info(
                f"Loaded modification keys for profile '{self.profile_name}'"
            )

        except Exception as e:
            logger.error(f"Error loading profile '{self.profile_name}': {e}", exc_info=True)

    def display_saved_values(self, modification_keys: Dict[str, Any]):
        for idx, key in enumerate(self.labels):
            key = key.lower()
            if key in modification_keys:
                row = self.rows[idx]
                row[0].set(modification_keys[key]["enabled"])  # Set checkbox
                row[1].set(modification_keys[key]["value"])  # Set combobox value
                row[2].set(modification_keys[key]["value"])  # Set previous value
                row[3].set(modification_keys[key]["pass"])  # Set pass checkbox
                if modification_keys[key]["pass"]:
                    self.toggle_pass(row[1], row[3], idx)

    def update_combobox(self, event, var: tk.StringVar, idx: int):
        if not self.rows[idx][3].get():  # Check if Pass checkbox is not checked
            value = event.char.upper()
            if value in self.valid_keys:
                logger.debug(f"value: {value}")
                var.set(value)
                return "break"

    def toggle_pass(self, cmb_var: tk.StringVar, pass_var: tk.BooleanVar, idx: int):
        prev_value_var = self.rows[idx][2]  # Get the previous value variable

        if pass_var.get():
            prev_value_var.set(cmb_var.get())  # Store the current value
            cmb_var.set("Pass")
            self.update_combobox_state(cmb_var, "readonly")
        else:
            cmb_var.set(prev_value_var.get())  # Restore the previous value
            self.update_combobox_state(cmb_var, "normal")

    def update_combobox_state(self, cmb_var: tk.StringVar, state: str):
        for child in self.grid_slaves():
            if isinstance(child, ttk.Combobox) and child.cget("textvariable") == str(
                cmb_var
            ):
                child.config(state=state)
                break

    def save(self):
        modification_keys = {
            label.lower(): {
                "enabled": row[0].get(),
                "value": "Pass" if row[3].get() else row[1].get(),
                "pass": row[3].get(),
            }
            for label, row in zip(self.labels, self.rows)
        }

        profile_path = os.path.join(self.profiles_dir, f"{self.profile_name}.pkl")
        profile = ProfileModel(name=self.profile_name)

        if os.path.exists(profile_path):
            with open(profile_path, "rb") as f:
                profile = pickle.load(f)

        profile.modification_keys = modification_keys

        with open(profile_path, "wb") as f:
            pickle.dump(profile, f)

        logger.info(
            f"Updated modification keys for profile '{self.profile_name}': {modification_keys}"
        )

        self.destroy()
