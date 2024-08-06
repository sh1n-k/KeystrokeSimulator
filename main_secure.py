import base64
import hashlib
import os
import re
import subprocess
import tkinter as tk
import uuid
from datetime import datetime, timezone
from tkinter import ttk

import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

from keystroke_simulator_app import KeystrokeSimulatorApp
from keystroke_utils import WindowUtils


class DeviceManager:
    @staticmethod
    def generate_device_id():
        return str(uuid.uuid4())

    @staticmethod
    def get_machine_id():
        bios_serial = DeviceManager._get_serial(
            "wmic bios get serialnumber", "unknown_bios"
        )
        board_serial = DeviceManager._get_serial(
            "wmic baseboard get serialnumber", "unknown_board"
        )
        os_name = os.name
        user_name = os.getlogin()
        memory_gb = DeviceManager._get_memory_gb()
        machine_id = f"{bios_serial}:{board_serial}:{os_name}:{user_name}:{memory_gb}"
        print(machine_id)
        return hashlib.md5(machine_id.encode()).hexdigest()

    @staticmethod
    def _get_serial(command, default):
        try:
            return (
                subprocess.check_output(command, shell=True)
                .decode()
                .split("\n")[1]
                .strip()
            )
        except Exception:
            return default

    @staticmethod
    def _get_memory_gb():
        try:
            output = subprocess.check_output(
                ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"]
            ).decode()
            total_memory_str = output.split("\n")[1].strip()
            total_memory_bytes = int(total_memory_str)
            return total_memory_bytes
        except Exception as e:
            return f"Error retrieving memory: {e}"


class CryptoManager:
    @staticmethod
    def derive_key(machine_id, salt):
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000
        )
        return base64.urlsafe_b64encode(kdf.derive(machine_id.encode()))

    @staticmethod
    def obfuscate(data):
        key = b"ObfuscationKey1213"
        return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])


class StorageManager:
    @staticmethod
    def store_device_id(device_id):
        machine_id = DeviceManager.get_machine_id()
        salt = os.urandom(16)
        key = CryptoManager.derive_key(machine_id, salt)
        f = Fernet(key)
        encrypted_data = f.encrypt(device_id.encode())
        obfuscated_data = CryptoManager.obfuscate(encrypted_data)
        file_path = os.path.join(os.path.expanduser("~"), ".secure_app_data")
        with open(file_path, "wb") as file:
            file.write(salt + obfuscated_data)

    @staticmethod
    def retrieve_device_id():
        file_path = os.path.join(os.path.expanduser("~"), ".secure_app_data")
        try:
            with open(file_path, "rb") as file:
                data = file.read()
                salt = data[:16]
                obfuscated_data = data[16:]
        except FileNotFoundError:
            raise Exception("Device ID not found. Please register this device.")

        deobfuscated_data = CryptoManager.obfuscate(obfuscated_data)
        machine_id = DeviceManager.get_machine_id()
        key = CryptoManager.derive_key(machine_id, salt)
        f = Fernet(key)
        try:
            decrypted_data = f.decrypt(deobfuscated_data)
            return decrypted_data.decode()
        except Exception:
            raise Exception(
                "Failed to decrypt device ID. This may not be the original device."
            )


def get_or_create_device_id():
    try:
        return StorageManager.retrieve_device_id()
    except Exception:
        device_id = DeviceManager.generate_device_id()
        StorageManager.store_device_id(device_id)
        return device_id


class AuthApp:
    def __init__(self, master):
        self.master = master
        master.title("Authentication")
        self.device_id = get_or_create_device_id()
        self.config = load_dotenv(".env")

        self.id_label = ttk.Label(master, text="User ID:")
        self.id_label.grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.id_entry = ttk.Entry(master)
        self.id_entry.grid(row=0, column=1, padx=5, pady=5)
        self.id_entry.config(
            validate="key",
            validatecommand=(master.register(self.validate_user_id), "%P"),
        )

        self.error_label = tk.Label(
            master,
            text="Enter your username and click the 'OK' button or press Enter.",
            fg="black",
            wraplength=200,
        )
        self.error_label.grid(row=2, column=0, columnspan=2, pady=5)

        button_frame = ttk.Frame(master)
        button_frame.grid(row=1, column=0, columnspan=2, pady=10)
        self.ok_button = ttk.Button(
            button_frame, text="OK", command=self.validate_and_auth
        )
        self.ok_button.pack(side=tk.LEFT, padx=5)
        self.quit_button = ttk.Button(
            button_frame, text="Quit", command=self.master.quit
        )
        self.quit_button.pack(side=tk.LEFT, padx=5)

        self.master.after(100, self.set_window_focus)
        self.master.bind("<Escape>", lambda event: self.master.quit())
        self.id_entry.bind("<Return>", lambda event: self.ok_button.invoke())

        self.center_window()

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

    def validate_and_auth(self):
        if self.validate_input():
            self.ok_button.config(state="disabled")
            self.request_authentication()

    def request_authentication(self):
        user_id = self.id_entry.get()
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))

        resp_json = None
        try:
            response = requests.post(
                self.config["AUTH_URL"],
                json={
                    "userId": user_id,
                    "deviceId": self.device_id,
                    "timestamp": timestamp,
                },
                timeout=5,
            )
            resp_json = response.json()
            print(response.status_code)
            print(resp_json)
            response.raise_for_status()
            self.launch_keystroke_simulator()
        except requests.Timeout:
            self.show_error_and_reactivate("Authentication request timed out.")
        except requests.RequestException as e:
            err_msg = resp_json["message"] if "message" in resp_json else ""
            self.show_error_and_reactivate(f"Failed to login: {err_msg}")

    def show_error_and_reactivate(self, message):
        self.show_error(message)
        self.ok_button.config(state="normal")
        self.master.deiconify()
        self.master.after(100, self.set_window_focus)

    def launch_keystroke_simulator(self):
        self.master.withdraw()
        self.master.destroy()
        keystroke_app = KeystrokeSimulatorApp()
        keystroke_app.mainloop()

    def center_window(self):
        self.master.update_idletasks()
        width = self.master.winfo_width()
        height = self.master.winfo_height()
        x = (self.master.winfo_screenwidth() // 2) - (width // 2)
        y = (self.master.winfo_screenheight() // 2) - (height // 2)
        self.master.geometry(f"{width}x{height}+{x}+{y}")


class MainApp:
    def __init__(self, master, device_id):
        self.master = master
        self.device_id = device_id
        master.title("Main Application")
        master.geometry("400x300")

        label = ttk.Label(master, text="Welcome to the Main Application!")
        label.pack(pady=20)

        device_label = ttk.Label(master, text=f"Device ID: {self.device_id}")
        device_label.pack(pady=10)

        quit_button = ttk.Button(master, text="Quit", command=self.quit_app)
        quit_button.pack(pady=10)

        master.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.master.after(100, self.set_window_focus)

        WindowUtils.center_window(self.master)

    def set_window_focus(self):
        self.master.focus_force()
        self.master.lift()

    def quit_app(self):
        self.master.quit()
        self.master.destroy()


def main():
    root = tk.Tk()
    app = AuthApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
