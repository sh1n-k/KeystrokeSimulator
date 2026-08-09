import unittest
from unittest.mock import patch

from app.core.processor import ModificationKeyHandler


class TestModificationKeyHandler(unittest.IsolatedAsyncioTestCase):
    async def test_skips_os_poll_when_no_mod_keys_enabled(self) -> None:
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(0.05, 0.05),
            mod_keys={},
            os_type="Darwin",
        )
        self.assertEqual(handler.mod_keys, {})

        with patch("app.core.processor.KeyUtils.mod_key_pressed") as mock_pressed:
            active = await handler.check_and_process()

        self.assertFalse(active)
        mock_pressed.assert_not_called()

    async def test_skips_os_poll_when_all_mod_keys_disabled(self) -> None:
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(0.05, 0.05),
            mod_keys={
                "alt": {"enabled": False, "pass": True, "value": "Pass"},
                "shift": {"enabled": False, "pass": True, "value": "Pass"},
            },
            os_type="Darwin",
        )
        self.assertEqual(handler.mod_keys, {})

        with patch("app.core.processor.KeyUtils.mod_key_pressed") as mock_pressed:
            active = await handler.check_and_process()

        self.assertFalse(active)
        mock_pressed.assert_not_called()

    async def test_polls_when_mod_key_enabled(self) -> None:
        handler = ModificationKeyHandler(
            key_codes={"A": 65},
            default_press_times=(0.05, 0.05),
            mod_keys={
                "alt": {"enabled": True, "pass": True, "value": "Pass"},
            },
            os_type="Darwin",
        )
        self.assertIn("alt", handler.mod_keys)

        with patch(
            "app.core.processor.KeyUtils.mod_key_pressed", return_value=False
        ) as mock_pressed:
            active = await handler.check_and_process()

        self.assertFalse(active)
        mock_pressed.assert_called()


if __name__ == "__main__":
    unittest.main()
