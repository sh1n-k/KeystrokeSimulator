import unittest

from profile_display import (
    QUICK_PROFILE_NAME,
    build_profile_display_values,
    to_profile_display_name,
)


class TestProfileDisplay(unittest.TestCase):
    def test_to_profile_display_name(self):
        self.assertEqual(
            to_profile_display_name("Work", is_favorite=True),
            "⭐ Work",
        )
        self.assertEqual(
            to_profile_display_name("Work", is_favorite=False),
            "Work",
        )
        self.assertEqual(
            to_profile_display_name(QUICK_PROFILE_NAME, is_favorite=True),
            QUICK_PROFILE_NAME,
        )

    def test_build_profile_display_values_preserves_order_and_quick_rule(self):
        names = [QUICK_PROFILE_NAME, "A", "B", "C"]
        favorites = {"A", QUICK_PROFILE_NAME}
        self.assertEqual(
            build_profile_display_values(names, favorites),
            [QUICK_PROFILE_NAME, "⭐ A", "B", "C"],
        )

    def test_build_profile_display_values_respects_custom_quick_name(self):
        names = ["Fast", "A"]
        favorites = {"Fast", "A"}
        self.assertEqual(
            build_profile_display_values(
                names,
                favorites,
                quick_profile_name="Fast",
            ),
            ["Fast", "⭐ A"],
        )


if __name__ == "__main__":
    unittest.main()
