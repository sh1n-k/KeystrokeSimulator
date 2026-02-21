import sys
import unittest
from unittest.mock import MagicMock, patch, call

# main_secure imports Tkinter and requests at module level; patch heavy deps before import
sys.modules.setdefault("keystroke_simulator_app", MagicMock())
sys.modules.setdefault("keystroke_utils", MagicMock())

import main_secure  # noqa: E402 — must come after sys.modules patching
from main_secure import Application, AuthService, AuthUI, Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_application() -> Application:
    """Create Application without starting Tk or showing any window."""
    with patch("main_secure.tk.Tk"), patch("main_secure.AuthUI"), patch(
        "main_secure.WindowUtils"
    ):
        app = Application.__new__(Application)
        app.root = MagicMock()
        app.auth_service = MagicMock(spec=AuthService)
        app.auth_ui = MagicMock()
        app.auth_ui.user_id = "testuser"
        app.main_app = MagicMock()
        app.main_app.winfo_exists.return_value = True
        return app


# ---------------------------------------------------------------------------
# Session scheduling tests
# ---------------------------------------------------------------------------

class TestCheckSessionStartsDaemonThread(unittest.TestCase):
    def test_check_session_starts_daemon_thread(self):
        app = _make_application()
        with patch("main_secure.threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            app.check_session_and_schedule()

            mock_thread_cls.assert_called_once_with(
                target=app._validate_session_worker, daemon=True
            )
            mock_thread.start.assert_called_once()


class TestValidateSessionWorker(unittest.TestCase):
    def test_validate_worker_calls_after_on_main_app(self):
        app = _make_application()
        app.auth_service.validate_session_token.return_value = True

        app._validate_session_worker()

        app.main_app.after.assert_called_once_with(0, app._on_session_checked, True)

    def test_validate_worker_noop_if_no_main_app(self):
        app = _make_application()
        app.main_app = None
        app.auth_service.validate_session_token.return_value = True

        # Should not raise
        app._validate_session_worker()

    def test_validate_worker_swallows_after_exception(self):
        app = _make_application()
        app.auth_service.validate_session_token.return_value = True
        app.main_app.after.side_effect = Exception("widget destroyed")

        # Should not propagate
        app._validate_session_worker()


# ---------------------------------------------------------------------------
# _on_session_checked tests
# ---------------------------------------------------------------------------

class TestOnSessionChecked(unittest.TestCase):
    def test_on_session_checked_reschedules_if_valid(self):
        app = _make_application()
        app._on_session_checked(True)
        app.main_app.after.assert_called_once_with(
            5 * 60 * 1000, app.check_session_and_schedule
        )

    def test_on_session_checked_force_closes_if_invalid(self):
        app = _make_application()
        with patch.object(app, "force_close_app") as mock_close:
            app._on_session_checked(False)
            mock_close.assert_called_once()

    def test_on_session_checked_noop_if_app_destroyed(self):
        app = _make_application()
        app.main_app.winfo_exists.return_value = False

        with patch.object(app, "force_close_app") as mock_close:
            app._on_session_checked(True)
            mock_close.assert_not_called()
            app.main_app.after.assert_not_called()

    def test_on_session_checked_noop_if_main_app_none(self):
        app = _make_application()
        app.main_app = None

        # Should not raise
        app._on_session_checked(True)


# ---------------------------------------------------------------------------
# AuthService.request_authentication tests
# ---------------------------------------------------------------------------

import requests  # noqa: E402


class TestAuthServiceRequestAuthentication(unittest.TestCase):
    def setUp(self):
        self.svc = AuthService()

    def test_auth_service_request_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"sessionToken": "tok123"}
        with patch("main_secure.requests.post", return_value=mock_resp):
            result = self.svc.request_authentication("user1")
        self.assertEqual(result["sessionToken"], "tok123")

    def test_auth_service_http_error(self):
        http_err = requests.HTTPError()
        http_err.response = MagicMock()
        http_err.response.status_code = 403
        http_err.response.json.return_value = {"message": "Forbidden"}

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = http_err

        with patch("main_secure.requests.post", return_value=mock_resp):
            with self.assertRaises(Exception) as ctx:
                self.svc.request_authentication("user1")
        self.assertIn("Forbidden", str(ctx.exception))

    def test_auth_service_network_error(self):
        with patch(
            "main_secure.requests.post",
            side_effect=requests.RequestException("timeout"),
        ):
            with self.assertRaises(Exception) as ctx:
                self.svc.request_authentication("user1")
        self.assertIn("Network connection failed", str(ctx.exception))


# ---------------------------------------------------------------------------
# AuthService.validate_session_token tests
# ---------------------------------------------------------------------------

class TestValidateSessionToken(unittest.TestCase):
    def setUp(self):
        self.svc = AuthService()
        self.svc.session_token = "tok123"

    def test_validate_session_true_on_success(self):
        mock_resp = MagicMock()
        with patch("main_secure.requests.post", return_value=mock_resp):
            result = self.svc.validate_session_token("user1")
        self.assertTrue(result)

    def test_validate_session_false_on_http_error(self):
        http_err = requests.HTTPError()
        http_err.response = MagicMock()
        http_err.response.status_code = 401

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = http_err

        with patch("main_secure.requests.post", return_value=mock_resp):
            result = self.svc.validate_session_token("user1")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# AuthUI helpers
# ---------------------------------------------------------------------------

def _make_auth_ui(on_success=None) -> AuthUI:
    """Create AuthUI bypassing __init__ — no real Tkinter widgets."""
    ui = AuthUI.__new__(AuthUI)
    ui.master = MagicMock()
    ui.auth_service = MagicMock(spec=AuthService)
    ui.on_success_callback = on_success or MagicMock()
    ui.failed_attempts = 0
    ui.user_id = "testuser"
    ui.id_entry = MagicMock()
    ui.ok_button = MagicMock()
    ui.error_label = MagicMock()
    return ui


# ---------------------------------------------------------------------------
# AuthUI — validate_user_id (keystroke-level guard)
# ---------------------------------------------------------------------------

class TestAuthUIValidateUserId(unittest.TestCase):
    def test_too_long_returns_false_and_shows_error(self):
        ui = _make_auth_ui()
        result = ui.validate_user_id("a" * (Config.MAX_USER_ID_LENGTH + 1))
        self.assertFalse(result)
        ui.error_label.config.assert_called()

    def test_at_max_length_returns_true(self):
        ui = _make_auth_ui()
        result = ui.validate_user_id("a" * Config.MAX_USER_ID_LENGTH)
        self.assertTrue(result)

    def test_empty_string_returns_true(self):
        # 빈 문자열 허용 (필드 전체 지우기 지원)
        ui = _make_auth_ui()
        self.assertTrue(ui.validate_user_id(""))


# ---------------------------------------------------------------------------
# AuthUI — validate_input (submit-level guard)
# ---------------------------------------------------------------------------

class TestAuthUIValidateInput(unittest.TestCase):
    def test_valid_alphanumeric_returns_true(self):
        ui = _make_auth_ui()
        ui.user_id = "user1234"
        self.assertTrue(ui.validate_input())

    def test_too_short_returns_false(self):
        ui = _make_auth_ui()
        ui.user_id = "abc"  # 3 chars < MIN(4)
        result = ui.validate_input()
        self.assertFalse(result)
        ui.error_label.config.assert_called()

    def test_too_long_returns_false(self):
        ui = _make_auth_ui()
        ui.user_id = "a" * (Config.MAX_USER_ID_LENGTH + 1)
        self.assertFalse(ui.validate_input())

    def test_special_chars_returns_false(self):
        ui = _make_auth_ui()
        ui.user_id = "user!@#"
        self.assertFalse(ui.validate_input())

    def test_exactly_min_length_returns_true(self):
        ui = _make_auth_ui()
        ui.user_id = "a" * Config.MIN_USER_ID_LENGTH
        self.assertTrue(ui.validate_input())


# ---------------------------------------------------------------------------
# AuthUI — validate_and_auth (submit handler)
# ---------------------------------------------------------------------------

class TestAuthUIValidateAndAuth(unittest.TestCase):
    def test_valid_input_disables_ok_button_and_calls_request(self):
        ui = _make_auth_ui()
        ui.id_entry.get.return_value = "validuser"
        with patch.object(ui, "request_authentication") as mock_req:
            ui.validate_and_auth()
        ui.ok_button.config.assert_called_with(state="disabled")
        mock_req.assert_called_once()

    def test_invalid_input_skips_request(self):
        ui = _make_auth_ui()
        ui.id_entry.get.return_value = "ab"  # too short
        with patch.object(ui, "request_authentication") as mock_req:
            ui.validate_and_auth()
        mock_req.assert_not_called()

    def test_user_id_set_from_entry(self):
        ui = _make_auth_ui()
        ui.id_entry.get.return_value = "newuser1"
        with patch.object(ui, "request_authentication"):
            ui.validate_and_auth()
        self.assertEqual(ui.user_id, "newuser1")


# ---------------------------------------------------------------------------
# AuthUI — request_authentication (auth flow)
# ---------------------------------------------------------------------------

class TestAuthUIRequestAuthentication(unittest.TestCase):
    def test_success_stores_token_and_fires_callback(self):
        """인증 성공 → 토큰 저장 + 콜백 호출 (E2E 대체 핵심)"""
        callback = MagicMock()
        ui = _make_auth_ui(on_success=callback)
        ui.auth_service.request_authentication.return_value = {"sessionToken": "tok42"}

        ui.request_authentication()

        self.assertEqual(ui.auth_service.session_token, "tok42")
        callback.assert_called_once()

    def test_success_does_not_show_error(self):
        ui = _make_auth_ui()
        ui.auth_service.request_authentication.return_value = {"sessionToken": "tok42"}
        with patch.object(ui, "show_error_and_reactivate") as mock_err:
            ui.request_authentication()
        mock_err.assert_not_called()

    def test_missing_session_token_shows_error(self):
        ui = _make_auth_ui()
        ui.auth_service.request_authentication.return_value = {}  # sessionToken 없음
        with patch.object(ui, "show_error_and_reactivate") as mock_err:
            ui.request_authentication()
        mock_err.assert_called_once()
        ui.on_success_callback.assert_not_called()

    def test_service_exception_shows_error(self):
        ui = _make_auth_ui()
        ui.auth_service.request_authentication.side_effect = Exception("Server error")
        with patch.object(ui, "show_error_and_reactivate") as mock_err:
            ui.request_authentication()
        mock_err.assert_called_once()
        ui.on_success_callback.assert_not_called()

    def test_error_message_contains_exception_text(self):
        ui = _make_auth_ui()
        ui.auth_service.request_authentication.side_effect = Exception("Forbidden")
        with patch.object(ui, "show_error_and_reactivate") as mock_err:
            ui.request_authentication()
        self.assertIn("Forbidden", mock_err.call_args[0][0])

    def test_missing_token_message_contains_no_session_token(self):
        ui = _make_auth_ui()
        ui.auth_service.request_authentication.return_value = {}
        with patch.object(ui, "show_error_and_reactivate") as mock_err:
            ui.request_authentication()
        self.assertIn("No session token", mock_err.call_args[0][0])


# ---------------------------------------------------------------------------
# AuthUI — show_error_and_reactivate / lockout logic
# ---------------------------------------------------------------------------

class TestAuthUIErrorHandling(unittest.TestCase):
    def test_first_failure_increments_and_reenables_button(self):
        ui = _make_auth_ui()
        ui.show_error_and_reactivate("fail")
        self.assertEqual(ui.failed_attempts, 1)
        ui.ok_button.config.assert_called_with(state="normal")

    def test_second_failure_no_lockout(self):
        ui = _make_auth_ui()
        ui.failed_attempts = 1
        with patch.object(ui, "lock_inputs") as mock_lock:
            ui.show_error_and_reactivate("fail")
        mock_lock.assert_not_called()
        self.assertEqual(ui.failed_attempts, 2)

    def test_third_failure_triggers_lockout(self):
        ui = _make_auth_ui()
        ui.failed_attempts = Config.MAX_FAILED_ATTEMPTS - 1
        with patch.object(ui, "lock_inputs") as mock_lock, \
             patch.object(ui, "start_countdown"):
            ui.show_error_and_reactivate("fail")
        mock_lock.assert_called_once()
        self.assertEqual(ui.failed_attempts, Config.MAX_FAILED_ATTEMPTS)

    def test_lockout_passes_message_to_countdown(self):
        ui = _make_auth_ui()
        ui.failed_attempts = Config.MAX_FAILED_ATTEMPTS - 1
        with patch.object(ui, "lock_inputs"), \
             patch.object(ui, "start_countdown") as mock_cd:
            ui.show_error_and_reactivate("Custom fail msg")
        mock_cd.assert_called_once_with(
            Config.LOCKOUT_TIME, final_message="Custom fail msg"
        )

    def test_lock_inputs_disables_entry_and_button(self):
        ui = _make_auth_ui()
        with patch.object(ui, "start_countdown"):
            ui.lock_inputs()
        ui.id_entry.config.assert_called_with(state="disabled")
        ui.ok_button.config.assert_called_with(state="disabled")

    def test_unlock_inputs_restores_entry_and_button(self):
        ui = _make_auth_ui()
        ui.failed_attempts = 3
        ui.unlock_inputs()
        ui.id_entry.config.assert_called_with(state="normal")
        ui.ok_button.config.assert_called_with(state="normal")

    def test_unlock_inputs_resets_failed_attempts(self):
        ui = _make_auth_ui()
        ui.failed_attempts = 3
        ui.unlock_inputs()
        self.assertEqual(ui.failed_attempts, 0)


# ---------------------------------------------------------------------------
# AuthUI — start_countdown
# ---------------------------------------------------------------------------

class TestAuthUICountdown(unittest.TestCase):
    def test_nonzero_schedules_next_tick(self):
        ui = _make_auth_ui()
        with patch.object(ui, "show_error"), patch.object(ui, "unlock_inputs") as mock_unlock:
            ui.start_countdown(3)
        ui.master.after.assert_called_once_with(1000, ui.start_countdown, 2, "")
        mock_unlock.assert_not_called()

    def test_zero_calls_unlock(self):
        ui = _make_auth_ui()
        with patch.object(ui, "unlock_inputs") as mock_unlock:
            ui.start_countdown(0)
        mock_unlock.assert_called_once()
        ui.master.after.assert_not_called()

    def test_nonzero_shows_error_with_remaining_time(self):
        ui = _make_auth_ui()
        with patch.object(ui, "show_error") as mock_err:
            ui.start_countdown(5, final_message="Too many attempts")
        call_text = mock_err.call_args[0][0]
        self.assertIn("5", call_text)

    def test_countdown_propagates_final_message(self):
        ui = _make_auth_ui()
        with patch.object(ui, "show_error"):
            ui.start_countdown(2, final_message="Locked")
        ui.master.after.assert_called_once_with(1000, ui.start_countdown, 1, "Locked")


if __name__ == "__main__":
    unittest.main()
