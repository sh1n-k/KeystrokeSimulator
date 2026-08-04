import unittest

from app.utils.notification_sound_packs import (
    DEFAULT_NOTIFICATION_SOUND_PACK,
    NOTIFICATION_SOUND_PACKS,
    get_notification_sound_pack,
    normalize_notification_sound_pack,
    notification_sound_pack_choices,
)


class TestNotificationSoundPackCatalog(unittest.TestCase):
    def test_catalog_has_classic_and_soft_packs(self):
        self.assertEqual(
            set(NOTIFICATION_SOUND_PACKS),
            {"classic", "soft_a", "soft_b", "soft_c"},
        )
        choices = notification_sound_pack_choices()
        self.assertEqual(
            [p.pack_id for p in choices],
            ["classic", "soft_a", "soft_b", "soft_c"],
        )
        for pack in choices:
            self.assertTrue(pack.start_b64)
            self.assertTrue(pack.stop_b64)

    def test_normalize_and_get(self):
        self.assertEqual(normalize_notification_sound_pack(None), "classic")
        self.assertEqual(normalize_notification_sound_pack("SOFT_B"), "soft_b")
        self.assertEqual(normalize_notification_sound_pack("nope"), "classic")
        pack = get_notification_sound_pack("soft_c")
        self.assertEqual(pack.pack_id, "soft_c")
        self.assertIs(
            get_notification_sound_pack("missing").pack_id,
            DEFAULT_NOTIFICATION_SOUND_PACK,
        )


if __name__ == "__main__":
    unittest.main()
