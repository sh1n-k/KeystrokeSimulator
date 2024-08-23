import tkinter as tk
from tkinter import ttk
import pickle
import os

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

        self.valid_keys = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

        self.create_widgets()
        self.load_profile()
        WindowUtils.center_window(self)

    def create_widgets(self):
        self.labels = ["Alt", "Ctrl", "Shift"]
        self.rows = []

        for j, label in enumerate(self.labels):
            row = []

            lbl = ttk.Label(self, text=f"{label}")
            lbl.grid(row=j, column=1, padx=5, pady=5)
            row.append(lbl)

            chk_var = tk.BooleanVar()
            chk = ttk.Checkbutton(self, variable=chk_var)
            chk.grid(row=j, column=2, padx=5, pady=5)
            row.append(chk_var)

            cmb_var = tk.StringVar(value="PressKey")
            cmb = ttk.Combobox(
                self, textvariable=cmb_var, values=["PressKey"], width=10
            )
            cmb.grid(row=j, column=3, padx=5, pady=5)
            cmb.bind("<KeyPress>", lambda e, var=cmb_var: self.update_combobox(e, var))
            row.append(cmb_var)
            row.append(tk.StringVar(value="PressKey"))  # Previous value

            pass_lbl = ttk.Label(self, text="Pass")
            pass_lbl.grid(row=j, column=4, padx=5, pady=5)
            row.append(pass_lbl)

            pass_var = tk.BooleanVar(value=False)
            pass_chk = ttk.Checkbutton(
                self,
                variable=pass_var,
                command=lambda v=cmb_var, c=pass_var: self.toggle_pass(v, c),
            )
            pass_chk.grid(row=j, column=5, padx=5, pady=5)
            row.append(pass_var)

            self.rows.append(row)

        save_button = ttk.Button(self, text="Save(Enter)", command=self.save)
        save_button.grid(row=len(self.labels), column=0, columnspan=6, pady=10)

        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())

    def load_profile(self):
        profile_path = os.path.join(self.profiles_dir, f"{self.profile_name}.pkl")
        if os.path.exists(profile_path):
            try:
                with open(profile_path, "rb") as f:
                    profile = pickle.load(f)
                if hasattr(profile, "modification_keys"):
                    self.display_saved_values(profile.modification_keys)
                    logger.info(
                        f"Loaded modification keys for profile '{self.profile_name}'"
                    )
                else:
                    logger.info(
                        f"No modification keys found in profile '{self.profile_name}'"
                    )
            except Exception as e:
                logger.error(f"Error loading profile '{self.profile_name}': {str(e)}")
        else:
            logger.info(
                f"Profile '{self.profile_name}' does not exist. Starting with default values."
            )

    def display_saved_values(self, modification_keys):
        for i, row in enumerate(self.rows):
            key = self.labels[i].lower()
            if key in modification_keys:
                row[1].set(modification_keys[key]["enabled"])  # Set checkbox
                row[2].set(modification_keys[key]["value"])  # Set combobox value
                row[3].set(modification_keys[key]["value"])  # Set previous value
                row[5].set(modification_keys[key]["pass"])  # Set pass checkbox
                if modification_keys[key]["pass"]:
                    self.toggle_pass(row[2], row[5])

    def update_combobox(self, event, var):
        value = event.char.upper()
        if value in self.valid_keys:
            logger.debug(f"value: {value}")
            var.set(value)
            return "break"

    def toggle_pass(self, cmb_var, pass_var):
        index = self.rows.index(next(row for row in self.rows if row[2] == cmb_var))
        prev_value_var = self.rows[index][3]  # Get the previous value variable

        if pass_var.get():
            prev_value_var.set(cmb_var.get())  # Store the current value
            cmb_var.set("Pass")
            for child in self.grid_slaves():
                if isinstance(child, ttk.Combobox) and child.cget(
                    "textvariable"
                ) == str(cmb_var):
                    child.config(state="readonly")
                    break
        else:
            for child in self.grid_slaves():
                if isinstance(child, ttk.Combobox) and child.cget(
                    "textvariable"
                ) == str(cmb_var):
                    child.config(state="normal")
                    cmb_var.set(prev_value_var.get())  # Restore the previous value
                    break

    def save(self):
        modification_keys = {}
        for i, row in enumerate(self.rows):
            key = self.labels[i].lower()
            value = "Pass" if row[5].get() else row[2].get()
            modification_keys[key] = {
                "enabled": row[1].get(),
                "value": value,
                "pass": row[5].get(),
            }

        profile_path = os.path.join(self.profiles_dir, f"{self.profile_name}.pkl")
        if os.path.exists(profile_path):
            with open(profile_path, "rb") as f:
                profile = pickle.load(f)
        else:
            profile = ProfileModel(name=self.profile_name)

        profile.modification_keys = modification_keys

        with open(profile_path, "wb") as f:
            pickle.dump(profile, f)

        logger.info(
            f"Updated modification keys for profile '{self.profile_name}': {modification_keys}"
        )

        self.destroy()
