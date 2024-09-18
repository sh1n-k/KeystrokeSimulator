import hashlib
import os
import re
import secrets
import shutil
import sys
import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk

import requests
from Crypto.Cipher import AES
from dotenv import load_dotenv, find_dotenv
from loguru import logger

from keystroke_simulator_app import KeystrokeSimulatorApp
from keystroke_utils import WindowUtils  # Assuming this is still needed


class CryptoManager:
    @staticmethod
    def derive_key(salt):
        """
        Derive a secure key using PBKDF2 with SHA256.
        """
        iterations = 100000
        key_length = 32  # AES-256 key length
        master_key = os.getenv("MASTER_KEY")
        if not master_key:
            raise Exception("MASTER_KEY not set in environment variables.")
        dk = hashlib.pbkdf2_hmac(
            "sha256", master_key.encode(), salt, iterations, key_length
        )
        return dk  # Return the raw bytes

    @staticmethod
    def encrypt(data):
        """
        Encrypt data using AES-256-CBC.
        """
        salt = secrets.token_bytes(16)
        key = CryptoManager.derive_key(salt)
        iv = secrets.token_bytes(16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_data = CryptoManager._pad(data.encode())
        encrypted_data = cipher.encrypt(padded_data)
        return salt + iv + encrypted_data

    @staticmethod
    def decrypt(encrypted_data):
        """
        Decrypt data using AES-256-CBC.
        """
        salt = encrypted_data[:16]
        iv = encrypted_data[16:32]
        ciphertext = encrypted_data[32:]
        key = CryptoManager.derive_key(salt)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_data = cipher.decrypt(ciphertext)
        return CryptoManager._unpad(padded_data).decode()

    @staticmethod
    def _pad(data):
        """
        Apply PKCS7 padding.
        """
        padding_length = 16 - (len(data) % 16)
        padding = bytes([padding_length] * padding_length)
        return data + padding

    @staticmethod
    def _unpad(padded_data):
        """
        Remove PKCS7 padding.
        """
        padding_length = padded_data[-1]
        return padded_data[:-padding_length]


class AuthApp:
    def __init__(self, master):
        self.master = master
        self.setup_ui()
        self.failed_attempts = 0
        self.session_token = None
        self.check_session_validity()

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
        user_id = self.id_entry.get()
        if not re.match(r"^[a-zA-Z0-9]{4,12}$", user_id):
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
        if self.validate_input():
            self.ok_button.config(state="disabled")
            self.request_authentication()

    def request_authentication(self):
        user_id = self.id_entry.get()
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        payload = {
            "userId": user_id,
            "timestamp": timestamp,
        }
        resp_json = {}

        try:
            response = requests.post(os.getenv("AUTH_URL"), json=payload, timeout=5)
            resp_json = response.json()
            logger.info(f"{response.status_code}: {resp_json}")
            response.raise_for_status()

            # Update the session token in memory
            self.session_token = resp_json.get("sessionToken")
            if self.session_token:
                self.launch_next_step()
            else:
                raise Exception("No session token received")
        except requests.Timeout:
            self.show_error_and_reactivate("Authentication request timed out.")
        except requests.HTTPError as e:
            err_msg = resp_json.get("message", "Authentication failed.")
            self.show_error_and_reactivate(f"Failed to login: {err_msg}")
        except Exception as e:
            self.show_error_and_reactivate(f"An error occurred: {str(e)}")

    def check_session_validity(self):
        if self.session_token and self.validate_session_token(self.session_token):
            self.start_periodic_session_check()
        else:
            self.session_token = None

    def show_error_and_reactivate(self, message):
        self.failed_attempts += 1
        if self.failed_attempts >= 3:
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
        self.start_periodic_session_check()

        main_app = KeystrokeSimulatorApp()
        main_app.mainloop()

    @staticmethod
    def validate_session_token(token):
        logger.info(f"sessionValidation: {token}")
        payload = {"sessionToken": token}
        try:
            response = requests.post(os.getenv("VALIDATE_URL"), json=payload, timeout=5)
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def start_periodic_session_check(self):
        self.check_session_and_schedule()

    def check_session_and_schedule(self):
        if self.session_token and self.validate_session_token(self.session_token):
            # Schedule the next check in 60 seconds (1 minute)
            self.master.after(3000, self.check_session_and_schedule)
        else:
            # Session is invalid, force quit the app
            logger.info(f"Invalid session token: {self.session_token}")
            self.force_close_app()

    def force_close_app(self):
        self.session_token = None
        self.master.destroy()
        sys.exit(0)


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