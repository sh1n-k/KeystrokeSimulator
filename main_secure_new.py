import os
import re
import shutil
import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk

import requests
from dotenv import load_dotenv, find_dotenv
from loguru import logger

from keystroke_simulator_app import KeystrokeSimulatorApp
from keystroke_utils import WindowUtils


class AuthApp:
    def __init__(self, master):
        self.master = master
        self.setup_ui()
        self.failed_attempts = 0
        self.user_id = None
        self.session_token = None
        self.main_app = None

    def setup_ui(self):
        self.master.title("Authentication")
        self.create_widgets()
        self.setup_bindings()
        WindowUtils.center_window(self.master)

    def create_widgets(self):
        self.id_label = ttk.Label(self.master, text="User ID:")
        self.id_entry = ttk.Entry(self.master)
        self.error_label = tk.Label(
            self.master,
            text="Enter your User ID and click 'OK' or press Enter.",
            fg="black",
            wraplength=300,
        )
        button_frame = ttk.Frame(self.master)
        self.ok_button = ttk.Button(
            button_frame, text="OK", command=self.validate_and_auth
        )
        self.quit_button = ttk.Button(
            button_frame, text="Quit", command=self.master.quit
        )

        self.id_label.grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.id_entry.grid(row=0, column=1, padx=5, pady=5)
        self.error_label.grid(row=2, column=0, columnspan=2, pady=5)
        button_frame.grid(row=1, column=0, columnspan=2, pady=10)
        self.ok_button.pack(side=tk.LEFT, padx=5)
        self.quit_button.pack(side=tk.LEFT, padx=5)

    def setup_bindings(self):
        self.id_entry.config(
            validate="key",
            validatecommand=(self.master.register(self.validate_user_id), "%P"),
        )
        self.master.bind("<Escape>", lambda event: self.master.quit())
        self.id_entry.bind("<Return>", lambda event: self.ok_button.invoke())
        self.master.after(100, self.set_window_focus)

    def set_window_focus(self):
        self.master.focus_force()
        self.master.lift()
        self.id_entry.focus_set()

    def validate_user_id(self, new_value):
        if len(new_value) > 12:
            self.show_error("User ID must be\n12 characters or less")
            return False
        self.clear_error()
        return True

    def validate_input(self):
        if not re.match(r"^[a-zA-Z0-9]{4,12}$", self.user_id):
            self.show_error("User ID must be\n4-12 alphanumeric characters")
            return False
        self.clear_error()
        return True

    def show_error(self, message):
        self.error_label.config(text=message, fg="red")
        self.master.update_idletasks()

    def clear_error(self):
        self.error_label.config(text="")

    def lock_inputs(self):
        self.id_entry.config(state="disabled")
        self.ok_button.config(state="disabled")
        self.start_countdown(10)

    def unlock_inputs(self):
        self.id_entry.config(state="normal")
        self.ok_button.config(state="normal")
        self.clear_error()
        self.failed_attempts = 0

    def start_countdown(self, remaining_time, final_message=""):
        if remaining_time > 0:
            self.show_error(
                f"{final_message}\n\nToo many failed attempts.\nTry again in {remaining_time} seconds."
            )
            self.master.after(
                1000, self.start_countdown, remaining_time - 1, final_message
            )
        else:
            self.unlock_inputs()

    def validate_and_auth(self):
        self.user_id = self.id_entry.get()
        if self.validate_input():
            self.ok_button.config(state="disabled")
            logger.info(f"Attempting authentication for user: {self.user_id}")
            self.request_authentication()
        else:
            logger.warning(f"Invalid input for user ID: {self.user_id}")

    def request_authentication(self):
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        payload = {
            "userId": self.user_id,
            "timestamp": timestamp,
        }
        resp_json = {}

        try:
            response = requests.post(os.getenv("AUTH_URL"), json=payload, timeout=5)
            resp_json = response.json()
            logger.info(f"Authentication response: {response.status_code}: {resp_json}")
            response.raise_for_status()

            # Update the session token in memory
            self.session_token = resp_json.get("sessionToken")
            if self.session_token:
                logger.info(f"Authentication successful for user: {self.user_id}")
                self.launch_next_step()
            else:
                logger.error("No session token received in authentication response")
                raise Exception("No session token received")
        except requests.Timeout:
            logger.error(f"Authentication request timed out for user: {self.user_id}")
            self.show_error_and_reactivate("Authentication request timed out.")
        except requests.HTTPError as e:
            err_msg = resp_json.get("message", "Authentication failed.")
            logger.error(f"HTTP error during authentication for user {self.user_id}: {err_msg}")
            self.show_error_and_reactivate(f"Failed to login: {err_msg}")
        except Exception as e:
            logger.error(f"Unexpected error during authentication for user {self.user_id}: {str(e)}")
            self.show_error_and_reactivate(f"An error occurred: {str(e)}")

    def show_error_and_reactivate(self, message):
        self.failed_attempts += 1
        if self.failed_attempts >= 3:
            logger.warning(f"User {self.user_id} locked out due to too many failed attempts")
            self.lock_inputs()
            self.start_countdown(10, final_message=message)
        else:
            self.show_error(message)
            self.ok_button.config(state="normal")
            self.master.deiconify()
            self.master.after(100, self.set_window_focus)

    def launch_next_step(self):
        self.master.withdraw()

        # Start periodic session validation before launching the main app
        self.check_session_and_schedule()

        self.main_app = KeystrokeSimulatorApp(secure_callback=self.terminate_application)
        self.main_app.mainloop()

    def validate_session_token(self):
        logger.info(f"Validating session for user: {self.user_id}")
        payload = {"userId": self.user_id, "sessionToken": self.session_token}
        try:
            response = requests.post(os.getenv("VALIDATE_URL"), json=payload, timeout=5)
            response.raise_for_status()
            logger.info(f"Session validation successful for user: {self.user_id}")
            return True
        except requests.RequestException as e:
            logger.error(f"Session validation failed for user '{self.user_id}'")
            return False

    def check_session_and_schedule(self):
        if self.validate_session_token():
            self.master.after(300000, self.check_session_and_schedule)
        else:
            logger.info(f"Invalid session token")
            self.force_close_app()

    def terminate_application(self):
        self.master.destroy()
        self.master.quit()
        self.master = None
        logger.info("Application terminated")

    def force_close_app(self):
        if self.main_app:
            self.main_app.on_closing()
        else:
            self.terminate_application()


def main():
    log_path = "logs"
    if not os.path.exists(log_path):
        os.mkdir(log_path)
    if os.path.isfile(log_path):
        shutil.move(log_path, "logs.bak")
        os.makedirs(log_path)
    logger.add(os.path.join(log_path, "auth.log"), rotation="1 MB", level="INFO")

    load_dotenv(find_dotenv())

    root = tk.Tk()
    app = AuthApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
