import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keystroke_utils import KeyUtils, StateUtils


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
