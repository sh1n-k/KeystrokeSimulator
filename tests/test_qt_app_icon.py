import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QIcon

from app.platform.system import set_windows_app_user_model_id
from app.ui.application import APP_ICON_PATH
from tests.qt_support import qt_app


class TestAppIcon(unittest.TestCase):
    def test_app_icon_svg_loads_and_renders(self):
        qt_app()
        icon = QIcon(str(APP_ICON_PATH))
        self.assertFalse(icon.isNull())
        image = icon.pixmap(32, 32).toImage()
        self.assertFalse(image.isNull())
        # Center of the keycap is opaque, not a blank render.
        self.assertGreater(image.pixelColor(16, 16).alpha(), 0)

    @patch("app.platform.system.IS_WIN", True)
    def test_sets_app_user_model_id_on_windows(self):
        windll = MagicMock()
        with patch("app.platform.system.windows_windll", return_value=windll):
            set_windows_app_user_model_id("KeystrokeSimulator.App")
        windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(
            "KeystrokeSimulator.App"
        )

    @patch("app.platform.system.IS_WIN", False)
    def test_app_user_model_id_is_noop_off_windows(self):
        with patch("app.platform.system.windows_windll") as windll:
            set_windows_app_user_model_id("KeystrokeSimulator.App")
        windll.assert_not_called()


if __name__ == "__main__":
    unittest.main()
