import unittest

from profile_display import (
    FAVORITE_PREFIX,
    QUICK_PROFILE_NAME,
    build_profile_display_values,
    to_profile_display_name,
)


class TestToProfileDisplayName(unittest.TestCase):
    """to_profile_display_name: 단일 프로필 표시 이름"""

    def test_favorite_profile(self):
        """일반 프로필 + favorite → 별 접두사"""
        result = to_profile_display_name("MyProfile", True)
        self.assertEqual(result, f"{FAVORITE_PREFIX}MyProfile")

    def test_non_favorite_profile(self):
        """일반 프로필 + non-favorite → 그대로"""
        result = to_profile_display_name("MyProfile", False)
        self.assertEqual(result, "MyProfile")

    def test_quick_favorite_no_star(self):
        """Quick 프로필은 favorite이어도 별 없음"""
        result = to_profile_display_name(QUICK_PROFILE_NAME, True)
        self.assertEqual(result, QUICK_PROFILE_NAME)

    def test_quick_non_favorite(self):
        """Quick 프로필 + non-favorite → 그대로"""
        result = to_profile_display_name(QUICK_PROFILE_NAME, False)
        self.assertEqual(result, QUICK_PROFILE_NAME)


class TestBuildProfileDisplayValues(unittest.TestCase):
    """build_profile_display_values: 프로필 목록 표시"""

    def test_mixed_list(self):
        """Quick + favorite + non-favorite 혼합 목록"""
        names = [QUICK_PROFILE_NAME, "Alpha", "Beta"]
        favorites = {QUICK_PROFILE_NAME, "Alpha"}
        result = build_profile_display_values(names, favorites)
        self.assertEqual(result, [
            QUICK_PROFILE_NAME,           # Quick은 star 없음
            f"{FAVORITE_PREFIX}Alpha",    # favorite
            "Beta",                        # non-favorite
        ])

    def test_empty_list(self):
        """빈 목록"""
        result = build_profile_display_values([], set())
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
