import unittest

from app.domain.validation import settings_number_entry_valid


class TestValidateNumeric(unittest.TestCase):
    """settings_number_entry_valid: 설정 창 숫자 칸 검증"""

    def test_validate_numeric_basic(self):
        self.assertTrue(settings_number_entry_valid(""))
        self.assertTrue(settings_number_entry_valid("0"))
        self.assertTrue(settings_number_entry_valid("999"))

        self.assertFalse(settings_number_entry_valid("1000"))
        self.assertFalse(settings_number_entry_valid("01"))
        self.assertFalse(settings_number_entry_valid("abc"))
        self.assertFalse(settings_number_entry_valid("-5"))

    def test_validate_numeric_float(self):
        """부동소수점 입력은 거부"""
        self.assertFalse(settings_number_entry_valid("3.14"))

    def test_validate_numeric_very_large(self):
        """매우 큰 수는 거부 (>= 1000)"""
        self.assertFalse(settings_number_entry_valid("99999"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
