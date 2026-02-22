import os
import re
import shutil
import threading
import json
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import ttk
from typing import Dict, Optional

import requests
from dotenv import load_dotenv, find_dotenv
from loguru import logger
from i18n import dual_text_width, normalize_language, set_language, txt

from keystroke_simulator_app import KeystrokeSimulatorApp
from keystroke_utils import WindowUtils

load_dotenv(find_dotenv())


def _load_ui_language():
    s_file = Path("user_settings.json")
    try:
        data = json.loads(s_file.read_text(encoding="utf-8")) if s_file.exists() else {}
    except Exception:
        data = {}
    set_language(normalize_language(data.get("language")))


class Config:
    APP_VERSION = "3.0"
    AUTH_URL = os.getenv("AUTH_URL")
    VALIDATE_URL = os.getenv("VALIDATE_URL")
    MAX_USER_ID_LENGTH = 12
    MIN_USER_ID_LENGTH = 4
    MAX_FAILED_ATTEMPTS = 3
    LOCKOUT_TIME = 10  # seconds


class AuthService:
    def __init__(self):
        self.session_token: Optional[str] = None

    def request_authentication(self, user_id: str) -> Dict[str, str]:
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        payload = {
            "userId": user_id,
            "timestamp": timestamp,
            "appVersion": Config.APP_VERSION,
        }
        try:
            response = requests.post(Config.AUTH_URL, json=payload, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            logger.error(
                f"Authentication HTTP error for user {user_id}: {e.response.status_code}"
            )
            # 서버 응답이 있는 경우 message 필드 추출
            try:
                error_data = e.response.json()
                error_message = error_data.get(
                    "message", txt("Authentication failed", "인증에 실패했습니다")
                )
            except:
                error_message = txt(
                    "Server error: {code}",
                    "서버 오류: {code}",
                    code=e.response.status_code,
                )
            raise Exception(error_message)
        except requests.RequestException as e:
            logger.error(f"Authentication network error for user {user_id}: {str(e)}")
            # 네트워크 오류
            raise Exception(txt("Network connection failed", "네트워크 연결에 실패했습니다"))

    def validate_session_token(self, user_id: str) -> bool:
        if not self.session_token:
            return False
        payload = {
            "userId": user_id,
            "sessionToken": self.session_token,
            "appVersion": Config.APP_VERSION,
        }
        try:
            response = requests.post(Config.VALIDATE_URL, json=payload, timeout=5)
            response.raise_for_status()
            return True
        except requests.HTTPError as e:
            logger.error(
                f"Session validation HTTP error for user '{user_id}': {e.response.status_code}"
            )
            return False
        except requests.RequestException as e:
            logger.error(
                f"Session validation network error for user '{user_id}': {str(e)}"
            )
            return False


class AuthUI:
    def __init__(self, master: tk.Tk, auth_service: AuthService, on_success_callback):
        _load_ui_language()
        self.master = master
        self.auth_service = auth_service
        self.on_success_callback = on_success_callback
        self.setup_ui()
        self.failed_attempts = 0
        self.user_id = None

    def setup_ui(self):
        self.master.title(txt("Authentication", "인증"))
        self.create_widgets()
        self.setup_bindings()
        WindowUtils.center_window(self.master)

    def create_widgets(self):
        self.id_label = ttk.Label(self.master, text=txt("User ID:", "사용자 ID:"))
        self.id_entry = ttk.Entry(self.master)
        self.error_label = tk.Label(
            self.master,
            text=txt(
                "Enter your User ID and click 'OK' or press Enter.",
                "사용자 ID를 입력한 뒤 '확인'을 누르거나 Enter를 입력하세요.",
            ),
            fg="black",
            wraplength=300,
        )
        button_frame = ttk.Frame(self.master)
        self.ok_button = ttk.Button(
            button_frame,
            text=txt("OK", "확인"),
            width=dual_text_width("OK", "확인", padding=2, min_width=6),
            command=self.validate_and_auth,
        )
        self.quit_button = ttk.Button(
            button_frame,
            text=txt("Quit", "종료"),
            width=dual_text_width("Quit", "종료", padding=2, min_width=6),
            command=self.master.quit,
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

    def validate_user_id(self, new_value: str) -> bool:
        if len(new_value) > Config.MAX_USER_ID_LENGTH:
            self.show_error(
                txt(
                    "User ID must be\n{max_len} characters or less",
                    "사용자 ID는\n{max_len}자 이하여야 합니다.",
                    max_len=Config.MAX_USER_ID_LENGTH,
                )
            )
            return False
        self.clear_error()
        return True

    def validate_input(self) -> bool:
        if not re.match(
            f"^[a-zA-Z0-9]{{{Config.MIN_USER_ID_LENGTH},{Config.MAX_USER_ID_LENGTH}}}$",
            self.user_id,
        ):
            self.show_error(
                txt(
                    "User ID must be\n{min_len}-{max_len} alphanumeric characters",
                    "사용자 ID는\n{min_len}-{max_len}자의 영문/숫자여야 합니다.",
                    min_len=Config.MIN_USER_ID_LENGTH,
                    max_len=Config.MAX_USER_ID_LENGTH,
                )
            )
            return False
        self.clear_error()
        return True

    def show_error(self, message: str):
        self.error_label.config(text=message, fg="red")
        self.master.update_idletasks()

    def clear_error(self):
        self.error_label.config(text="")

    def lock_inputs(self):
        self.id_entry.config(state="disabled")
        self.ok_button.config(state="disabled")

    def unlock_inputs(self):
        self.id_entry.config(state="normal")
        self.ok_button.config(state="normal")
        self.clear_error()
        self.failed_attempts = 0

    def start_countdown(self, remaining_time: int, final_message: str = ""):
        if remaining_time > 0:
            self.show_error(
                txt(
                    "{final_message}\n\nToo many failed attempts.\nTry again in {remaining_time} seconds.",
                    "{final_message}\n\n실패 횟수가 너무 많습니다.\n{remaining_time}초 후 다시 시도하세요.",
                    final_message=final_message,
                    remaining_time=remaining_time,
                )
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
        try:
            resp_json = self.auth_service.request_authentication(self.user_id)
            session_token = resp_json.get("sessionToken")
            if session_token:
                logger.info(f"Authentication successful for user: {self.user_id}")
                self.auth_service.session_token = session_token
                self.on_success_callback()
            else:
                logger.error("No session token received in authentication response")
                raise Exception(txt("No session token received", "세션 토큰을 받지 못했습니다"))
        except Exception as e:
            self.show_error_and_reactivate(
                txt("Authentication failed: {error}", "인증 실패: {error}", error=str(e))
            )

    def show_error_and_reactivate(self, message: str):
        self.failed_attempts += 1
        if self.failed_attempts >= Config.MAX_FAILED_ATTEMPTS:
            logger.warning(
                f"User {self.user_id} locked out due to too many failed attempts"
            )
            self.lock_inputs()
            self.start_countdown(Config.LOCKOUT_TIME, final_message=message)
        else:
            self.show_error(message)
            self.ok_button.config(state="normal")
            self.master.deiconify()
            self.master.after(100, self.set_window_focus)


def setup_logging():
    # Remove any existing handlers
    log_path = "logs"
    if not os.path.exists(log_path):
        os.mkdir(log_path)
    if os.path.isfile(log_path):
        shutil.move(log_path, "logs.bak")
        os.makedirs(log_path)
    logger.add(os.path.join(log_path, "keysym.log"), rotation="1 MB", level="INFO")


class Application:
    def __init__(self):
        self.root = tk.Tk()
        self.auth_service = AuthService()
        self.auth_ui = AuthUI(self.root, self.auth_service, self.on_auth_success)
        self.main_app = None

    def on_auth_success(self):
        self.root.withdraw()
        self.root.destroy()
        self.main_app = KeystrokeSimulatorApp()
        self.main_app.after(5 * 60 * 1000, self.check_session_and_schedule)
        self.main_app.mainloop()
        logger.info("Application terminated")

    def check_session_and_schedule(self):
        threading.Thread(target=self._validate_session_worker, daemon=True).start()

    def _validate_session_worker(self):
        is_valid = self.auth_service.validate_session_token(self.auth_ui.user_id)
        if self.main_app:
            try:
                self.main_app.after(0, self._on_session_checked, is_valid)
            except Exception:
                pass  # main_app이 닫히는 중

    def _on_session_checked(self, is_valid: bool):
        if not (self.main_app and self.main_app.winfo_exists()):
            return
        if is_valid:
            self.main_app.after(5 * 60 * 1000, self.check_session_and_schedule)
        else:
            self.force_close_app()

    def force_close_app(self):
        if self.main_app:
            self.main_app.on_closing()

    def run(self):
        self.root.mainloop()


def main():
    setup_logging()
    app = Application()
    app.run()


if __name__ == "__main__":
    main()
