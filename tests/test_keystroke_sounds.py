import array
import unittest
from unittest.mock import patch, MagicMock

from app.utils.sounds import SoundPlayer, _ActiveSound


class TestKeystrokeSounds(unittest.TestCase):
    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_sound_player_init_does_not_start_device(self, mock_decode, mock_device):
        mock_decode.return_value.samples = array.array("h", [0, 1, -1, 0])

        player = SoundPlayer()

        self.assertEqual(mock_decode.call_count, 4)
        mock_device.assert_not_called()
        self.assertIsNone(player._device)
        self.assertIsNotNone(player.start_sound)
        self.assertIsNotNone(player.stop_sound)
        self.assertIsNotNone(player.runtime_toggle_on_sound)
        self.assertIsNotNone(player.runtime_toggle_off_sound)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_sound_player_init_failure_handled(self, mock_decode, mock_device):
        mock_decode.side_effect = Exception("decode failed")

        player = SoundPlayer()

        self.assertIsNone(player.start_sound)
        self.assertIsNone(player.stop_sound)
        self.assertIsNone(player.runtime_toggle_on_sound)
        self.assertIsNone(player.runtime_toggle_off_sound)
        mock_device.assert_not_called()

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_play_starts_device_on_demand(self, mock_decode, mock_device):
        mock_decode.return_value.samples = array.array("h", [0, 1, -1, 0])
        player = SoundPlayer()
        mock_device.assert_not_called()

        player.play_start_sound()

        mock_device.assert_called_once()
        mock_device.return_value.start.assert_called_once()
        self.assertIsNotNone(player._device)
        self.assertEqual(len(player._active_sounds), 1)

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
        self.assertIs(player._active_sounds[0].samples, samples)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_mix_stream_keeps_remaining_samples(self, mock_decode, _mock_device):
        samples = array.array("h", [1, 2, 3, 4, 5, 6])
        mock_decode.return_value.samples = samples
        player = SoundPlayer()

        player.play_start_sound()
        assert player._stream is not None
        mixed = player._stream.send(1)

        self.assertEqual(list(mixed), [1, 2])
        self.assertEqual(len(player._active_sounds), 1)
        self.assertIs(player._active_sounds[0].samples, samples)
        self.assertEqual(player._active_sounds[0].position, 2)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_idle_mix_releases_device(self, mock_decode, mock_device):
        samples = array.array("h", [1, 2])
        mock_decode.return_value.samples = samples
        player = SoundPlayer()
        player.play_start_sound()
        self.assertIsNotNone(player._device)
        assert player._stream is not None

        # Drain all samples (1 frame = 2 channels).
        mixed = player._stream.send(1)
        self.assertEqual(list(mixed), [1, 2])
        self.assertEqual(player._active_sounds, [])

        # Next empty cycle yields silence then stops the device.
        silence = player._stream.send(1)
        self.assertEqual(silence, b"\x00" * 4)
        self.assertIsNone(player._device)
        mock_device.return_value.close.assert_called()

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_play_after_idle_restarts_device(self, mock_decode, mock_device):
        samples = array.array("h", [1, 2])
        mock_decode.return_value.samples = samples
        player = SoundPlayer()
        player.play_start_sound()
        assert player._stream is not None
        player._stream.send(1)
        player._stream.send(1)
        self.assertIsNone(player._device)
        mock_device.reset_mock()

        player.play_stop_sound()
        mock_device.assert_called_once()
        mock_device.return_value.start.assert_called_once()
        self.assertIsNotNone(player._device)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_close_releases_device(self, mock_decode, mock_device):
        mock_decode.return_value.samples = array.array("h", [0, 1, -1, 0])
        player = SoundPlayer()

        player.play_start_sound()
        player.close()
        player.play_stop_sound()

        self.assertGreaterEqual(mock_device.return_value.close.call_count, 1)
        # After close, a later play starts a fresh device.
        self.assertIsNotNone(player._device)
        self.assertEqual(len(player._active_sounds), 1)

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_concurrent_queue_during_empty_cycle_does_not_orphan_device(
        self, mock_decode, mock_device
    ):
        """Regression for dead generator + live device after concurrent queue.

        If samples arrive after an empty snapshot but before idle exit, the mix
        loop must keep playing them (not return while leaving _device set).
        """
        samples = array.array("h", [1, 2])
        concurrent = array.array("h", [5, 6])
        mock_decode.return_value.samples = samples
        player = SoundPlayer()
        player.play_start_sound()
        stream = player._stream
        assert stream is not None
        stream.send(1)  # drain first clip; device still running

        real_lock = player._lock
        injected = {"done": False}
        arm = {"on": False}

        class RaceLock:
            def acquire(self, *args, **kwargs):
                return real_lock.acquire(*args, **kwargs)

            def release(self) -> bool:
                # Inject after the empty-snapshot lock releases, before re-check.
                if (
                    arm["on"]
                    and not injected["done"]
                    and player._device is not None
                    and not player._active_sounds
                ):
                    injected["done"] = True
                    player._active_sounds.append(_ActiveSound(concurrent, 0))
                return real_lock.release()

            def __enter__(self) -> "RaceLock":
                self.acquire()
                return self

            def __exit__(self, *exc: object) -> bool:
                self.release()
                return False

        player._lock = RaceLock()  # type: ignore[assignment]
        arm["on"] = True

        mixed = stream.send(1)
        self.assertTrue(injected["done"])
        self.assertEqual(list(mixed), [5, 6])
        self.assertIsNotNone(player._device)

        # True idle then must clear device so later play restarts PlaybackDevice.
        silence = stream.send(1)
        self.assertEqual(silence, b"\x00" * 4)
        self.assertIsNone(player._device)

        mock_device.reset_mock()
        player.play_start_sound()
        mock_device.assert_called_once()
        mock_device.return_value.start.assert_called_once()
        self.assertIsNotNone(player._device)


if __name__ == "__main__":
    unittest.main()


class TestNotificationSoundPacks(unittest.TestCase):
    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_set_pack_fallback_and_selection_changes_samples(
        self, mock_decode, mock_device
    ):
        # Distinct sample arrays per decode call order so pack switch is observable.
        sample_seq = [
            array.array("h", [1, 1]),
            array.array("h", [2, 2]),
            array.array("h", [3, 3]),
            array.array("h", [4, 4]),
            array.array("h", [5, 5]),
            array.array("h", [6, 6]),
            array.array("h", [7, 7]),
            array.array("h", [8, 8]),
            array.array("h", [9, 9]),
            array.array("h", [10, 10]),
            array.array("h", [11, 11]),
            array.array("h", [12, 12]),
        ]
        mock_decode.side_effect = [
            type("D", (), {"samples": s})() for s in sample_seq
        ]

        player = SoundPlayer("classic")
        self.assertEqual(player.notification_sound_pack, "classic")
        classic_start = player.start_sound
        classic_stop = player.stop_sound
        self.assertIsNotNone(classic_start)
        self.assertIsNotNone(classic_stop)

        applied = player.set_notification_pack("soft_a")
        self.assertEqual(applied, "soft_a")
        self.assertIsNot(player.start_sound, classic_start)
        self.assertIsNot(player.stop_sound, classic_stop)
        soft_start_samples = player.start_sound._samples  # type: ignore[union-attr]

        applied = player.set_notification_pack("not-real")
        self.assertEqual(applied, "classic")
        self.assertIs(player.start_sound, classic_start)

        # Re-select soft_a uses cache (no extra decode beyond initial soft pair + classic pair + toggles)
        player.set_notification_pack("soft_a")
        self.assertIs(player.start_sound._samples, soft_start_samples)  # type: ignore[union-attr]

    @patch("app.utils.sounds.miniaudio.PlaybackDevice")
    @patch("app.utils.sounds.miniaudio.decode")
    def test_play_start_stop_use_selected_pack_samples(
        self, mock_decode, mock_device
    ):
        samples_by_call: list[array.array] = []

        def decode_side_effect(*_args, **_kwargs):
            arr = array.array("h", [len(samples_by_call) + 1, 0])
            samples_by_call.append(arr)
            return type("D", (), {"samples": arr})()

        mock_decode.side_effect = decode_side_effect
        player = SoundPlayer("classic")
        player.play_start_sound()
        classic_queued = player._active_sounds[0].samples
        player.close()

        player = SoundPlayer("soft_b")
        player.play_start_sound()
        soft_queued = player._active_sounds[0].samples
        self.assertIsNot(classic_queued, soft_queued)
        player.play_stop_sound()
        self.assertEqual(len(player._active_sounds), 2)
