import os
import tempfile
import unittest
from unittest.mock import patch

from src.audio import extract_audio, separate_vocals


class AudioExtractionTests(unittest.TestCase):
    def test_extracts_16khz_mono_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "video.mkv")
            output = os.path.join(directory, "audio.wav")
            open(source, "wb").close()
            sample_rates = []

            def fake_run(command, check):
                sample_rates.append(command[command.index("-ar") + 1])
                self.assertEqual(command[command.index("-ac") + 1], "1")
                with open(command[-1], "wb") as handle:
                    handle.write(b"wav")

            with patch("src.audio.subprocess.run", side_effect=fake_run) as run:
                extract_audio(source, output, audio_track_index=1)
                extract_audio(source, output, audio_track_index=1)
                extract_audio(source, output, audio_track_index=1, sample_rate=8000)

            self.assertEqual(run.call_count, 2)
            self.assertEqual(sample_rates, ["16000", "8000"])
            self.assertTrue(os.path.isfile(output))
            self.assertTrue(os.path.isfile(f"{output}.manifest.json"))

    def test_separates_and_caches_resampled_vocals(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "audio.wav")
            output = os.path.join(directory, "audio_vocals.wav")
            open(source, "wb").close()

            def fake_run(command, check):
                if "demucs" in command:
                    model = command[command.index("-n") + 1]
                    demucs_output = command[command.index("-o") + 1]
                    stem_dir = os.path.join(demucs_output, model, "audio")
                    os.makedirs(stem_dir)
                    with open(os.path.join(stem_dir, "vocals.wav"), "wb") as handle:
                        handle.write(b"stem")
                else:
                    self.assertEqual(command[command.index("-ar") + 1], "16000")
                    self.assertEqual(command[command.index("-ac") + 1], "1")
                    with open(command[-1], "wb") as handle:
                        handle.write(b"wav")

            with patch("src.audio.subprocess.run", side_effect=fake_run) as run:
                self.assertEqual(separate_vocals(source, output, device="cuda"), output)
                self.assertEqual(separate_vocals(source, output, device="cpu"), output)

            self.assertEqual(run.call_count, 2)
            self.assertTrue(os.path.isfile(output))
            self.assertTrue(os.path.isfile(f"{output}.manifest.json"))


if __name__ == "__main__":
    unittest.main()
