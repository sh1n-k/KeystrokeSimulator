import sys
import unittest
from unittest.mock import MagicMock, patch, call

# main_secure imports Tkinter and requests at module level; patch heavy deps before import
sys.modules.setdefault("keystroke_simulator_app", MagicMock())
sys.modules.setdefault("keystroke_utils", MagicMock())

import main_secure  # noqa: E402 — must come after sys.modules patching
from main_secure import Application, AuthService


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


if __name__ == "__main__":
    unittest.main()
