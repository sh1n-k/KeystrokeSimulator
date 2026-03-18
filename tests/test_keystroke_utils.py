import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keystroke_models import EventModel, ProfileModel
from keystroke_utils import KeyUtils, PermissionUtils, StateUtils
from runtime_toggle_utils import (
    MOUSE_BUTTON_3_TRIGGER,
    WHEEL_DOWN_TRIGGER,
    WHEEL_UP_TRIGGER,
    collect_runtime_toggle_validation_errors,
    display_runtime_toggle_trigger,
    normalize_runtime_toggle_capture_key,
    normalize_runtime_toggle_listener_key,
    normalize_runtime_toggle_trigger,
    normalize_runtime_toggle_wheel_event,
)


class TestStateUtils(unittest.TestCase):
    """StateUtils: 앱 상태 저장/로드"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = StateUtils.path
        StateUtils.path = Path(self.tmpdir.name) / "app_state.json"

    def tearDown(self):
        StateUtils.path = self.original_path
        self.tmpdir.cleanup()

    def test_save_and_load_roundtrip(self):
        """save → load roundtrip"""
        StateUtils.save_main_app_state(profile="TestProfile", process="MyApp")
        data = StateUtils.load_main_app_state()
        self.assertEqual(data["profile"], "TestProfile")
        self.assertEqual(data["process"], "MyApp")

    def test_load_nonexistent_returns_empty(self):
        """파일 없을 때 load → 빈 dict"""
        data = StateUtils.load_main_app_state()
        self.assertEqual(data, {})

    def test_merge_behavior(self):
        """기존 데이터와 병합"""
        StateUtils.save_main_app_state(key1="val1")
        StateUtils.save_main_app_state(key2="val2")
        data = StateUtils.load_main_app_state()
        self.assertEqual(data["key1"], "val1")
        self.assertEqual(data["key2"], "val2")

    def test_no_tmp_file_remains(self):
        """atomic write 후 .tmp 파일 미잔존"""
        StateUtils.save_main_app_state(test="data")
        tmp_path = StateUtils.path.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())


class TestKeyUtils(unittest.TestCase):
    """KeyUtils: 키코드 매핑"""

    def test_get_keycode_valid(self):
        """유효한 키 이름 → keycode 반환"""
        code = KeyUtils.get_keycode("A")
        self.assertIsNotNone(code)
        self.assertIsInstance(code, int)

    def test_get_keycode_capitalize(self):
        """소문자 입력 → capitalize 후 매핑"""
        code = KeyUtils.get_keycode("space")
        self.assertIsNotNone(code)
        expected = KeyUtils.CURRENT_KEYS.get("Space")
        self.assertEqual(code, expected)

    def test_get_key_name_list_not_empty(self):
        """키 이름 리스트가 비어있지 않음"""
        names = KeyUtils.get_key_name_list()
        self.assertIsInstance(names, list)
        self.assertGreater(len(names), 0)

    def test_get_key_name_for_keycode_roundtrip(self):
        code = KeyUtils.get_keycode("Q")
        self.assertEqual(KeyUtils.get_key_name_for_keycode(code), "Q")


class TestPermissionUtils(unittest.TestCase):
    @patch("keystroke_utils.IS_MAC", True)
    @patch(
        "keystroke_utils.PermissionUtils.has_screen_capture_access", return_value=False
    )
    @patch(
        "keystroke_utils.PermissionUtils.has_accessibility_access", return_value=True
    )
    def test_missing_macos_permissions_returns_screen_only(
        self, _mock_accessibility, _mock_screen
    ):
        self.assertEqual(PermissionUtils.missing_macos_permissions(), ["screen"])

    @patch("keystroke_utils.IS_MAC", True)
    @patch(
        "keystroke_utils.PermissionUtils.has_screen_capture_access", return_value=False
    )
    @patch(
        "keystroke_utils.PermissionUtils.has_accessibility_access", return_value=False
    )
    def test_missing_macos_permissions_returns_both(
        self, _mock_accessibility, _mock_screen
    ):
        self.assertEqual(
            PermissionUtils.missing_macos_permissions(),
            ["screen", "accessibility"],
        )


class TestRuntimeToggleUtils(unittest.TestCase):
    def test_normalize_runtime_toggle_trigger_accepts_mouse_tokens(self):
        self.assertEqual(normalize_runtime_toggle_trigger("w_up"), "W_UP")
        self.assertEqual(normalize_runtime_toggle_trigger("mb_3"), "MB_3")

    def test_normalize_runtime_toggle_capture_key_prefers_keysym_then_char(self):
        self.assertEqual(normalize_runtime_toggle_capture_key("space", " "), "Space")
        self.assertEqual(normalize_runtime_toggle_capture_key("", "a"), "A")
        self.assertEqual(normalize_runtime_toggle_capture_key("grave", None), "`")
        self.assertEqual(normalize_runtime_toggle_capture_key("won", None), "\\")
        self.assertEqual(normalize_runtime_toggle_capture_key("", "₩"), "\\")

    def test_normalize_runtime_toggle_capture_key_prefers_keycode_over_ime_text(self):
        self.assertEqual(
            normalize_runtime_toggle_capture_key(
                "Hangul", "ㅂ", KeyUtils.get_keycode("Q")
            ),
            "Q",
        )
        self.assertEqual(
            normalize_runtime_toggle_capture_key(
                "BackSpace", "₩", KeyUtils.get_keycode("`")
            ),
            "`",
        )

    def test_normalize_runtime_toggle_capture_key_maps_hangul_2set_letters(self):
        self.assertEqual(
            normalize_runtime_toggle_capture_key("Hangul", "ㅂ", None), "Q"
        )
        self.assertEqual(
            normalize_runtime_toggle_capture_key("Hangul", "ㅈ", None), "W"
        )
        self.assertEqual(
            normalize_runtime_toggle_capture_key("Hangul", "ㅁ", None), "A"
        )

    def test_normalize_runtime_toggle_listener_key_prefers_vk_over_char(self):
        key = type("KeyStub", (), {"vk": KeyUtils.get_keycode("Q"), "char": "ㅂ"})()
        self.assertEqual(normalize_runtime_toggle_listener_key(key), "Q")

    def test_normalize_runtime_toggle_wheel_event_supports_delta_and_button_num(self):
        self.assertEqual(
            normalize_runtime_toggle_wheel_event(delta=120), WHEEL_UP_TRIGGER
        )
        self.assertEqual(
            normalize_runtime_toggle_wheel_event(delta=-120), WHEEL_DOWN_TRIGGER
        )
        self.assertEqual(normalize_runtime_toggle_wheel_event(num=4), WHEEL_UP_TRIGGER)
        self.assertEqual(
            normalize_runtime_toggle_wheel_event(num=5), WHEEL_DOWN_TRIGGER
        )

    def test_display_runtime_toggle_trigger_uses_friendly_mouse_labels(self):
        self.assertEqual(
            display_runtime_toggle_trigger(WHEEL_DOWN_TRIGGER), "Mouse wheel down"
        )
        self.assertEqual(
            display_runtime_toggle_trigger(MOUSE_BUTTON_3_TRIGGER), "Mouse Button 3"
        )

    def test_collect_validation_errors_for_event_key_conflict(self):
        profile = ProfileModel(
            name="P1",
            runtime_toggle_enabled=True,
            runtime_toggle_key="F6",
            event_list=[
                EventModel(event_name="Evt1", key_to_enter="F6"),
                EventModel(
                    event_name="Extra", key_to_enter="A", runtime_toggle_member=True
                ),
            ],
        )

        errors = collect_runtime_toggle_validation_errors(
            profile,
            profile.event_list,
            settings=type(
                "SettingsStub",
                (),
                {
                    "toggle_start_stop_mac": False,
                    "use_alt_shift_hotkey": False,
                    "start_stop_key": "DISABLED",
                },
            )(),
            os_name="Darwin",
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("conflicts with event input key 'F6'", errors[0])

    def test_collect_validation_errors_for_alt_shift_conflict(self):
        profile = ProfileModel(
            name="P1",
            runtime_toggle_enabled=True,
            runtime_toggle_key="Option",
            event_list=[
                EventModel(
                    event_name="Extra", key_to_enter="A", runtime_toggle_member=True
                )
            ],
        )

        errors = collect_runtime_toggle_validation_errors(
            profile,
            profile.event_list,
            settings=type(
                "SettingsStub",
                (),
                {
                    "toggle_start_stop_mac": True,
                    "use_alt_shift_hotkey": False,
                    "start_stop_key": "`",
                },
            )(),
            os_name="Darwin",
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("conflicts with Start/Stop", errors[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
