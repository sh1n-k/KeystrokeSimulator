import base64
import hashlib
import os
import platform
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
from dotenv import load_dotenv, find_dotenv
from loguru import logger

from keystroke_simulator_app import KeystrokeSimulatorApp
from keystroke_utils import WindowUtils


class DeviceManager:
    @staticmethod
    def generate_device_id():
        return str(uuid.uuid4())

    @staticmethod
    def get_machine_id():
        if platform.system() == "Windows":
            bios_serial = DeviceManager._get_windows_serial(
                "wmic bios get serialnumber", "unknown_bios"
            )
            board_serial = DeviceManager._get_windows_serial(
                "wmic baseboard get serialnumber", "unknown_board"
            )
            memory_gb = DeviceManager._get_memory_gb()
        elif platform.system() == "Darwin":
            bios_serial, board_serial, memory_gb = DeviceManager._get_macos_serial()
        else:
            raise

        os_name = os.name
        user_name = os.getlogin()
        machine_id = f"{bios_serial}:{board_serial}:{os_name}:{user_name}:{memory_gb}"
        logger.debug(f"MachineId: {machine_id}")
        return hashlib.md5(machine_id.encode()).hexdigest()

    @staticmethod
    def _get_windows_serial(command, default):
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
    def _get_macos_serial():
        result = subprocess.run(
            ["system_profiler", "SPHardwareDataType"], stdout=subprocess.PIPE
        )
        output = result.stdout.decode()

        bios_serial = None
        board_serial = None
        memory = None

        for line in output.split("\n"):
            if "Serial Number (system)" in line:
                bios_serial = line.split(":")[-1].strip()
            if "Hardware UUID" in line:
                board_serial = line.split(":")[-1].strip()
            if "Memory" in line:
                memory = line.split(":")[-1].strip()

        return bios_serial, board_serial, memory

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
        key = os.getenv("OBFUSCATION_KEY").encode("utf-8")
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


class AuthApp:
    def __init__(self, master):
        self.master = master
        self.setup_ui()
        self.failed_attempts = 0
        self.device_id = self.get_or_create_device_id()

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
            text="Enter your username and click 'OK' or press Enter.",
            fg="black",
            wraplength=250,
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
        self.failed_attempts = 1

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
            "deviceId": self.device_id,
            "timestamp": timestamp,
        }
        resp_json = {}

        try:
            response = requests.post(os.getenv("AUTH_URL"), json=payload, timeout=5)
            resp_json = response.json()
            logger.info(f"{response.status_code}: {resp_json}")
            response.raise_for_status()
            self.launch_keystroke_simulator()
        except requests.Timeout:
            self.show_error_and_reactivate("Authentication request timed out.")
        except requests.RequestException as e:
            err_msg = resp_json.get("message", "") if resp_json else ""
            self.show_error_and_reactivate(f"Failed to login: {err_msg}")

    def show_error_and_reactivate(self, message):
        self.failed_attempts += 1
        if self.failed_attempts >= 2:
            self.lock_inputs()
            self.start_countdown(10, final_message=message)
        else:
            self.show_error(message)
            self.ok_button.config(state="normal")
            self.master.deiconify()
            self.master.after(100, self.set_window_focus)

    def launch_keystroke_simulator(self):
        self.master.withdraw()
        self.master.destroy()
        keystroke_app = KeystrokeSimulatorApp()
        keystroke_app.mainloop()

    @staticmethod
    def get_or_create_device_id():
        try:
            return StorageManager.retrieve_device_id()
        except Exception:
            device_id = DeviceManager.generate_device_id()
            StorageManager.store_device_id(device_id)
            return device_id


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
    load_dotenv(find_dotenv())
    main()
