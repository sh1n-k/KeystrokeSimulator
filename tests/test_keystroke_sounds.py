import unittest
from unittest.mock import patch, MagicMock
from keystroke_sounds import SoundPlayer

class TestKeystrokeSounds(unittest.TestCase):
    @patch("keystroke_sounds.pygame.mixer.Sound")
    @patch("keystroke_sounds.pygame.mixer.init")
    def test_sound_player_init_success(self, mock_init, mock_sound):
        # init should try to load start and stop sounds
        player = SoundPlayer()
        mock_init.assert_called_once()
        self.assertEqual(mock_sound.call_count, 2)
        self.assertIsNotNone(player.start_sound)
        self.assertIsNotNone(player.stop_sound)

    @patch("keystroke_sounds.pygame.mixer.init")
    def test_sound_player_init_failure_handled(self, mock_init):
        # Force pygame to raise an exception
        mock_init.side_effect = Exception("No Audio Device")
        player = SoundPlayer()
        self.assertIsNone(player.start_sound)
        self.assertIsNone(player.stop_sound)

    @patch("keystroke_sounds.pygame.mixer.init")
    def test_play_sound_when_loaded(self, mock_init):
        player = SoundPlayer()
        player.start_sound = MagicMock()
        player.stop_sound = MagicMock()

        player.play_start_sound()
        player.start_sound.play.assert_called_once()

        player.play_stop_sound()
        player.stop_sound.play.assert_called_once()

    @patch("keystroke_sounds.pygame.mixer.init")
    def test_play_sound_when_not_loaded(self, mock_init):
        player = SoundPlayer()
        player.start_sound = None
        player.stop_sound = None
        
        # Should not raise any attribute errors
        try:
            player.play_start_sound()
            player.play_stop_sound()
        except Exception as e:
            self.fail(f"play_sound raised an exception when sounds are None: {e}")

if __name__ == "__main__":
    unittest.main()
