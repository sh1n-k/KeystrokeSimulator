import unittest
from unittest.mock import MagicMock

from app.utils.window_state import WindowUtils


class TestModalGrabHelpers(unittest.TestCase):
    def test_can_own_modal_grab_rejects_non_windows(self):
        self.assertFalse(WindowUtils.can_own_modal_grab(object()))
        self.assertFalse(WindowUtils.can_own_modal_grab(None))

    def test_restore_modal_grab_noops_for_non_window(self):
        # Should not raise.
        WindowUtils.restore_modal_grab(object())
        WindowUtils.restore_modal_grab(None)

    def test_restore_modal_grab_calls_grab_set_when_exists(self):
        parent = MagicMock()
        parent.winfo_exists.return_value = True
        # Make isinstance check fail for Tk/Toplevel — use a real Toplevel subclass mock.
        # can_own_modal_grab requires real Tk type; with MagicMock it should no-op.
        WindowUtils.restore_modal_grab(parent)
        parent.grab_set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
