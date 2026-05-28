import array
import unittest
from unittest.mock import patch, MagicMock

from app.utils.sounds import SoundPlayer


class TestKeystrokeSounds(unittest.TestCase):
    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_sound_player_init_success(self, mock_decode, mock_device):
        mock_decode.return_value.samples = array.array("h", [0, 1, -1, 0])

        player = SoundPlayer()

        self.assertEqual(mock_decode.call_count, 4)
        mock_device.assert_called_once()
        mock_device.return_value.start.assert_called_once()
        self.assertIsNotNone(player.start_sound)
        self.assertIsNotNone(player.stop_sound)
        self.assertIsNotNone(player.runtime_toggle_on_sound)
        self.assertIsNotNone(player.runtime_toggle_off_sound)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_sound_player_init_failure_handled(self, mock_decode, mock_device):
        mock_decode.return_value.samples = array.array("h", [0, 1, -1, 0])
        mock_device.side_effect = Exception("No Audio Device")

        player = SoundPlayer()

        self.assertIsNone(player.start_sound)
        self.assertIsNone(player.stop_sound)
        self.assertIsNone(player.runtime_toggle_on_sound)
        self.assertIsNone(player.runtime_toggle_off_sound)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_play_sound_when_loaded(self, mock_decode, _mock_device):
        mock_decode.return_value.samples = array.array("h", [0, 1, -1, 0])
        player = SoundPlayer()
        player.start_sound = MagicMock()
        player.stop_sound = MagicMock()
        player.runtime_toggle_on_sound = MagicMock()
        player.runtime_toggle_off_sound = MagicMock()

        player.play_start_sound()
        player.start_sound.play.assert_called_once()

        player.play_stop_sound()
        player.stop_sound.play.assert_called_once()

        player.play_runtime_toggle_on_sound()
        player.runtime_toggle_on_sound.play.assert_called_once()

        player.play_runtime_toggle_off_sound()
        player.runtime_toggle_off_sound.play.assert_called_once()

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_play_sound_when_not_loaded(self, mock_decode, _mock_device):
        mock_decode.return_value.samples = array.array("h", [0, 1, -1, 0])
        player = SoundPlayer()
        player.start_sound = None
        player.stop_sound = None
        player.runtime_toggle_on_sound = None
        player.runtime_toggle_off_sound = None

        # Should not raise any attribute errors
        try:
            player.play_start_sound()
            player.play_stop_sound()
            player.play_runtime_toggle_on_sound()
            player.play_runtime_toggle_off_sound()
        except Exception as e:
            self.fail(f"play_sound raised an exception when sounds are None: {e}")

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_play_uses_predecoded_samples(self, mock_decode, _mock_device):
        samples = array.array("h", [0, 1, -1, 0])
        mock_decode.return_value.samples = samples
        player = SoundPlayer()
        mock_decode.reset_mock()

        player.play_start_sound()

        mock_decode.assert_not_called()
        self.assertEqual(len(player._active_sounds), 1)
        self.assertIs(player._active_sounds[0][0], samples)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_mix_stream_keeps_remaining_samples(self, mock_decode, _mock_device):
        samples = array.array("h", [1, 2, 3, 4, 5, 6])
        mock_decode.return_value.samples = samples
        player = SoundPlayer()

        player.play_start_sound()
        mixed = player._stream.send(1)

        self.assertEqual(list(mixed), [1, 2])
        self.assertEqual(len(player._active_sounds), 1)
        self.assertIs(player._active_sounds[0][0], samples)
        self.assertEqual(player._active_sounds[0][1], 2)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_close_releases_device(self, mock_decode, mock_device):
        mock_decode.return_value.samples = array.array("h", [0, 1, -1, 0])
        player = SoundPlayer()

        player.play_start_sound()
        player.close()
        player.play_stop_sound()

        mock_device.return_value.close.assert_called_once()
        self.assertIsNone(player._device)
        self.assertEqual(player._active_sounds, [])


if __name__ == "__main__":
    unittest.main()
